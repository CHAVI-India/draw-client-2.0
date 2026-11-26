"""In-memory RBS runner: evaluate a list of rules against an existing RTStruct.

This is the bridge that lets the auto-segmentation / reidentification path
(``dicom_handler`` task2) generate derived structures using the RBS engine
*without* the job / work-dir / approval lifecycle. It reuses
:class:`SegmentationEngine`'s per-rule evaluation (so operation semantics stay
in one place) and mutates the caller's ``RTStruct`` in place, so the generated
ROIs are folded into the very structure set being exported.

Only non-intermediate rules (``CREATE_NEW`` / ``REPLACE_EXISTING``) write to the
RTStruct; ``INTERMEDIATE`` rules are held in memory and referenced by later
rules, so intermediate structures are never exported.
"""

import logging
from typing import Dict, List, Optional, Set

import SimpleITK as sitk

from .engine import SegmentationEngine
from .expression_evaluator import RuleEvaluationError

logger = logging.getLogger(__name__)


class InlineSegmentationRunner:
    """Evaluate an ordered list of rules against an already-loaded RTStruct.

    Args:
        rtstruct: an ``rt_utils`` RTStruct (what ``RTStructBuilder.create_from``
            returns). The runner mutates it in place.
        image: reference CT/MR/PT image (``SimpleITK.Image``) for geometry.
        series: optional ``DICOMSeries`` (not required for rule evaluation).
    """

    def __init__(self, rtstruct, image: sitk.Image, series=None):
        self.rtstruct = rtstruct
        self.image = image
        self.series = series
        self.engine = SegmentationEngine.from_rtstruct(rtstruct, image, series)

    def run_rules(
        self,
        rules: List,
        skip_existing: Optional[Set[str]] = None,
    ) -> Dict[str, list]:
        """Evaluate ``rules`` (in order) against the RTStruct.

        Args:
            rules: ordered ``PipelineRule`` objects (each with its config
                attached). They may be unsaved model instances.
            skip_existing: optional set of ROI names that must not be created
                (e.g. names already present in the structure set). Matching
                rules are skipped; their name is still available to later rules
                because it is an existing ROI.

        Returns:
            ``{"created": [...], "replaced": [...], "intermediate": [...],
               "skipped": [...], "failed": [...]}``. ``intermediate`` names are
            held in memory only and are NOT written to the RTStruct.

        Raises:
            RuleEvaluationError: if a rule references a structure that is not
                available (from the input or a preceding rule).
        """
        skip_existing = set(skip_existing or set())
        summary: Dict[str, list] = {
            "created": [],
            "replaced": [],
            "intermediate": [],
            "skipped": [],
            "failed": [],
        }

        for rule in rules:
            if rule.name in skip_existing:
                summary["skipped"].append(rule.name)
                # It is an existing ROI, so it is already in available_masks and
                # resolvable by later rules; nothing to do.
                continue

            try:
                output_name = self.engine.run_rule(rule)
            except RuleEvaluationError as e:
                summary["failed"].append({"name": rule.name, "error": str(e)})
                raise

            if rule.output_action == "INTERMEDIATE":
                summary["intermediate"].append(output_name)
            elif rule.output_action == "REPLACE_EXISTING":
                summary["replaced"].append(output_name)
            else:
                summary["created"].append(output_name)

        return summary
