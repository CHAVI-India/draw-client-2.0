"""Pipeline execution engine for rule-based segmentation."""

import logging
import os
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import numpy as np
import SimpleITK as sitk

from dicom_handler.models import DICOMSeries
from dicom_handler.utils.structure_generation import (
    execute_operation,
)

from ..models import PipelineRule
from .expression_evaluator import (
    RuleEvaluationError,
    collect_boolean_roi_names,
    evaluate_boolean_tree,
    get_boolean_root,
)
from .rtstruct_io import (
    RTStructBuilder,
    add_mask_as_roi,
    load_roi_masks,
    load_rtstruct_and_image,
    regenerate_instance_uids,
    save_rtstruct,
)

logger = logging.getLogger(__name__)


class SegmentationEngine:
    """Execute a SegmentationPipeline on an RTStruct."""

    def __init__(self, rtstruct_path: str, series_instance_uid: str):
        self.rtstruct_path = rtstruct_path
        self.rtstruct, self.image, self.series = load_rtstruct_and_image(
            rtstruct_path, series_instance_uid
        )
        self.available_masks: Dict[str, sitk.Image] = load_roi_masks(
            self.rtstruct, self.image
        )
        self.summary: Dict[str, Any] = {
            "created_rois": [],
            "replaced_rois": [],
            "failed_rules": [],
        }

    @classmethod
    def from_workdir(cls, workdir_root: str) -> "SegmentationEngine":
        """
        Load engine state from a job work dir (see utils/job_workdir.py).

        Loads working.dcm (all previously completed rules applied) against the
        persisted instance copies in <workdir_root>/images, and the reference
        image from the NifTI cache. self.series is None — no rule evaluation
        path requires the DICOMSeries object.
        """
        images_dir = os.path.join(workdir_root, "images")
        working_path = os.path.join(workdir_root, "working.dcm")
        rtstruct = RTStructBuilder.create_from(
            dicom_series_path=images_dir,
            rt_struct_path=working_path,
        )
        image = sitk.ReadImage(os.path.join(workdir_root, "image.nii.gz"))
        engine = cls.__new__(cls)
        engine.rtstruct_path = working_path
        engine.rtstruct = rtstruct
        engine.image = image
        engine.series = None
        engine.available_masks = load_roi_masks(rtstruct, image)
        engine.summary = {
            "created_rois": [],
            "replaced_rois": [],
            "failed_rules": [],
        }
        return engine

    def run_pipeline(
        self,
        pipeline,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        output_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Execute all rules in the pipeline in order.

        Args:
            pipeline: SegmentationPipeline instance.
            progress_callback: Optional callback(current, total, message).
            output_path: Optional path to save the modified RTStruct. If not
                provided, the input file is overwritten in-place.

        Returns:
            Summary dictionary.
        """
        rules = list(pipeline.rules.all().order_by("order"))
        self._validate_rule_inputs(rules)

        total = len(rules)
        for idx, rule in enumerate(rules, start=1):
            if progress_callback:
                progress_callback(idx, total, f"Processing rule {idx}/{total}: {rule.name}")

            try:
                output_name = self.run_rule(rule)
                if rule.output_action == "REPLACE_EXISTING":
                    self.summary["replaced_rois"].append(output_name)
                else:
                    self.summary["created_rois"].append(output_name)
            except Exception as e:
                logger.error(f"Rule {rule.order} ({rule.name}) failed: {e}")
                self.summary["failed_rules"].append(
                    {"order": rule.order, "name": rule.name, "error": str(e)}
                )
                raise

        self.summary["sop_instance_uid"], self.summary["series_instance_uid"] = (
            regenerate_instance_uids(self.rtstruct)
        )
        save_rtstruct(self.rtstruct, output_path or self.rtstruct_path)
        return self.summary

    def _validate_rule_inputs(self, rules: List[PipelineRule]) -> None:
        """Ensure all referenced structures exist or are produced by earlier rules."""
        produced: Set[str] = set(self.available_masks.keys())

        for rule in rules:
            required = self._collect_required_structures(rule)
            missing = required - produced
            if missing:
                raise RuleEvaluationError(
                    f"Rule '{rule.name}' references missing structures: {sorted(missing)}"
                )
            produced.add(rule.name)

    def _collect_required_structures(self, rule: PipelineRule) -> Set[str]:
        """Collect all structure names referenced by a rule."""
        names: Set[str] = set()

        if rule.rule_type == "BOOLEAN":
            try:
                root = get_boolean_root(rule)
                names.update(collect_boolean_roi_names(root))
            except RuleEvaluationError:
                pass
        elif rule.rule_type == "INTENSITY":
            config = getattr(rule, "intensity_config", None)
            if config:
                if config.seed_type == "STRUCTURE" and config.seed_roi:
                    names.add(config.seed_roi)
                if config.boundary_roi:
                    names.add(config.boundary_roi)
        elif rule.rule_type == "MARGIN":
            config = getattr(rule, "margin_config", None)
            if config and config.source:
                names.add(config.source)
        elif rule.rule_type == "CROP":
            config = getattr(rule, "crop_config", None)
            if config:
                if config.source:
                    names.add(config.source)
                for boundary in config.boundaries.all():
                    names.add(boundary.boundary_roi)
        elif rule.rule_type == "CLEANUP":
            config = getattr(rule, "cleanup_config", None)
            if config and config.source:
                names.add(config.source)
        elif rule.rule_type == "RING":
            config = getattr(rule, "ring_config", None)
            if config and config.source:
                names.add(config.source)
        elif rule.rule_type == "OVERLAP":
            config = getattr(rule, "overlap_config", None)
            if config:
                if config.source:
                    names.add(config.source)
                for other in config.others.all():
                    names.add(other.other_roi)
        elif rule.rule_type == "EXPAND_SUBTRACT":
            config = getattr(rule, "expand_subtract_config", None)
            if config:
                if config.source:
                    names.add(config.source)
                if config.subtract:
                    names.add(config.subtract)
        elif rule.rule_type == "AVOID_MARGIN":
            config = getattr(rule, "avoid_margin_config", None)
            if config:
                if config.source:
                    names.add(config.source)
                if config.avoid:
                    names.add(config.avoid)

        return names

    def _evaluate_rule(self, rule: PipelineRule) -> sitk.Image:
        if rule.rule_type == "BOOLEAN":
            return self._evaluate_boolean_rule(rule)
        if rule.rule_type == "INTENSITY":
            return self._evaluate_intensity_rule(rule)
        if rule.rule_type == "MARGIN":
            return self._evaluate_margin_rule(rule)
        if rule.rule_type == "CROP":
            return self._evaluate_crop_rule(rule)
        if rule.rule_type == "CLEANUP":
            return self._evaluate_cleanup_rule(rule)
        if rule.rule_type == "RING":
            return self._evaluate_ring_rule(rule)
        if rule.rule_type == "OVERLAP":
            return self._evaluate_overlap_rule(rule)
        if rule.rule_type == "EXPAND_SUBTRACT":
            return self._evaluate_expand_subtract_rule(rule)
        if rule.rule_type == "AVOID_MARGIN":
            return self._evaluate_avoid_margin_rule(rule)
        raise RuleEvaluationError(f"Unknown rule type: {rule.rule_type}")

    def _evaluate_boolean_rule(self, rule: PipelineRule) -> sitk.Image:
        root = get_boolean_root(rule)
        return evaluate_boolean_tree(root, self.available_masks)

    def _evaluate_intensity_rule(self, rule: PipelineRule) -> sitk.Image:
        config = rule.intensity_config
        seed_mask = None
        boundary_mask = None

        if config.seed_type == "STRUCTURE" and config.seed_roi:
            seed_mask = self.available_masks[config.seed_roi]
        elif config.seed_type == "BOUNDARY" and config.boundary_roi:
            seed_mask = self.available_masks[config.boundary_roi]

        if config.boundary_roi:
            boundary_mask = self.available_masks[config.boundary_roi]

        ranges = [{"min": r.min_value, "max": r.max_value} for r in config.ranges.all()]
        return execute_operation(
            "intensity_range",
            {"seed": seed_mask, "boundary": boundary_mask},
            {"ranges": ranges},
            image=self.image,
        )

    def _margin_params(
        self,
        variant: str,
        prefix: str,
        uniform_mm: Optional[float],
        x_mm: Optional[float],
        y_mm: Optional[float],
        z_mm: Optional[float],
        kernel_type: Optional[str],
    ) -> Dict[str, Any]:
        """Build the param dict for a margin-like op (uniform or anisotropic).

        ``prefix`` selects the distance field names (``margin``/``thickness``/
        ``distance``) so the catalog params line up per operation.
        """
        if variant == "ANISOTROPIC":
            return {
                "variant": "ANISOTROPIC",
                f"{prefix}_x_mm": x_mm or 0.0,
                f"{prefix}_y_mm": y_mm or 0.0,
                f"{prefix}_z_mm": z_mm or 0.0,
            }
        return {
            "variant": "UNIFORM",
            f"{prefix}_mm": uniform_mm or 0.0,
            "kernel_type": kernel_type or "ball",
        }

    def _evaluate_margin_rule(self, rule: PipelineRule) -> sitk.Image:
        config = rule.margin_config
        source_mask = self.available_masks[config.source]
        self._ensure_mask_not_empty(source_mask, config.source)
        params = self._directional_margin_params(config, "margin")
        return execute_operation("margin", {"source": source_mask}, params)

    def _directional_margin_params(
        self, config, prefix: str
    ) -> Dict[str, Any]:
        """Build margin params from the six patient-anatomical directional
        fields (``{prefix}_l_mm`` ... ``{prefix}_f_mm``; negative = contract).

        Falls back to the legacy uniform/anisotropic params for pre-existing
        rules that have no directional values set, so they keep working.
        """
        keys = ("l", "r", "a", "p", "h", "f")
        directional = {
            f"{prefix}_{k}_mm": (getattr(config, f"{prefix}_{k}_mm") or 0.0)
            for k in keys
        }
        if any(directional.values()):
            return directional
        return self._margin_params(
            config.variant,
            prefix,
            config.margin_mm,
            config.margin_x_mm,
            config.margin_y_mm,
            config.margin_z_mm,
            config.kernel_type,
        )

    def _evaluate_ring_rule(self, rule: PipelineRule) -> sitk.Image:
        """Ring/shell: expand(source, thickness) - source."""
        config = rule.ring_config
        source_mask = self.available_masks[config.source]
        self._ensure_mask_not_empty(source_mask, config.source)
        params = self._margin_params(
            config.variant,
            "thickness",
            config.thickness_mm,
            config.thickness_x_mm,
            config.thickness_y_mm,
            config.thickness_z_mm,
            config.kernel_type,
        )
        return execute_operation("ring", {"source": source_mask}, params)

    def _evaluate_overlap_rule(self, rule: PipelineRule) -> sitk.Image:
        """Overlap: source ∩ (other1 ∪ other2 ∪ …)."""
        config = rule.overlap_config
        source_mask = self.available_masks[config.source]
        others = list(config.others.values_list("other_roi", flat=True).order_by("order"))
        if not others:
            raise RuleEvaluationError("Overlap rule requires at least one other structure.")
        roles = {"source": source_mask, "others": [self.available_masks[n] for n in others]}
        return execute_operation("overlap", roles, {})

    def _evaluate_expand_subtract_rule(self, rule: PipelineRule) -> sitk.Image:
        """Expand & Subtract: expand(source, distance) - subtract."""
        config = rule.expand_subtract_config
        source_mask = self.available_masks[config.source]
        self._ensure_mask_not_empty(source_mask, config.source)
        params = self._margin_params(
            config.variant,
            "distance",
            config.distance_mm,
            config.distance_x_mm,
            config.distance_y_mm,
            config.distance_z_mm,
            config.kernel_type,
        )
        roles = {"source": source_mask, "subtract": self.available_masks[config.subtract]}
        return execute_operation("expand_subtract", roles, params)

    def _evaluate_avoid_margin_rule(self, rule: PipelineRule) -> sitk.Image:
        """Avoid with Margin: source - expand(avoid, margin)."""
        config = rule.avoid_margin_config
        source_mask = self.available_masks[config.source]
        self._ensure_mask_not_empty(source_mask, config.source)
        avoid_mask = self.available_masks[config.avoid]
        self._ensure_mask_not_empty(avoid_mask, config.avoid)
        params = self._margin_params(
            config.variant,
            "margin",
            config.margin_mm,
            config.margin_x_mm,
            config.margin_y_mm,
            config.margin_z_mm,
            config.kernel_type,
        )
        roles = {"source": source_mask, "avoid": avoid_mask}
        return execute_operation("avoid_margin", roles, params)

    def _evaluate_crop_rule(self, rule: PipelineRule) -> sitk.Image:
        config = rule.crop_config
        source_mask = self.available_masks[config.source]
        boundaries = [self.available_masks[b.boundary_roi] for b in config.boundaries.all()]
        roles = {"source": source_mask, "boundaries": boundaries}
        return execute_operation("crop_to_boundary", roles, {})

    def _evaluate_cleanup_rule(self, rule: PipelineRule) -> sitk.Image:
        config = rule.cleanup_config
        source_mask = self.available_masks[config.source]
        self._ensure_mask_not_empty(source_mask, config.source)
        operation = config.operation

        if operation == "SMOOTH_STRUCTURE":
            return execute_operation(
                "smooth",
                {"source": source_mask},
                {"smoothing_mm": config.smoothing_mm, "iterations": config.iterations},
            )
        if operation == "GAUSSIAN_SMOOTH":
            return execute_operation(
                "gaussian_smooth",
                {"source": source_mask},
                {"sigma_mm": config.sigma_mm, "threshold": config.threshold},
            )
        if operation == "FILL_HOLES":
            return execute_operation(
                "fill_holes",
                {"source": source_mask},
                {"fully_connected": config.fully_connected or False},
            )
        if operation == "REMOVE_SMALL_COMPONENTS":
            return execute_operation(
                "remove_small_components",
                {"source": source_mask},
                {"min_size_mm3": config.min_size_mm3},
            )
        if operation == "KEEP_LARGEST_COMPONENT":
            return execute_operation("keep_largest", {"source": source_mask}, {})

        raise RuleEvaluationError(f"Unknown cleanup operation: {operation}")

    def run_rule(self, rule: PipelineRule) -> str:
        """
        Evaluate a single rule and append its output to the in-memory RTStruct.

        Returns the (possibly dedup-suffixed) output ROI name. Does not save
        the RTStruct — persistence is the caller's job (see JobWorkdir).
        """
        self._validate_rule_inputs([rule])
        mask = self._evaluate_rule(rule)
        self.available_masks[rule.name] = mask
        return self._add_rule_output_to_rtstruct(rule, mask)

    def _ensure_mask_not_empty(self, mask: sitk.Image, name: str) -> None:
        """Raise a clear error if a referenced structure mask contains no voxels."""
        arr = sitk.GetArrayFromImage(mask)
        if not np.any(arr):
            raise RuleEvaluationError(
                f"Structure '{name}' is empty (no segmented voxels). "
                "Margin or cleanup operations cannot be applied to an empty structure."
            )

    def _add_rule_output_to_rtstruct(self, rule: PipelineRule, mask: sitk.Image) -> str:
        color = self._parse_color(rule.output_color)
        name = rule.name

        # CREATE_NEW outputs must be unique in the RTStruct. If the name
        # already exists, append a numeric suffix to avoid duplicates.
        if rule.output_action == "CREATE_NEW" and name in self.rtstruct.get_roi_names():
            suffix = 1
            while f"{name}_{suffix}" in self.rtstruct.get_roi_names():
                suffix += 1
            name = f"{name}_{suffix}"
            logger.warning(
                f"ROI name '{rule.name}' already exists; renamed output to '{name}'"
            )

        add_mask_as_roi(
            self.rtstruct,
            mask,
            name,
            color,
            roi_type=rule.output_roi_type or "ORGAN",
            replace_existing=(rule.output_action == "REPLACE_EXISTING"),
        )
        return name

    def _parse_color(self, color_string: Optional[str]) -> List[int]:
        if not color_string:
            return [255, 255, 0]
        color = color_string.strip()
        if color.startswith("#"):
            try:
                hex_val = color[1:]
                if len(hex_val) == 3:
                    return [int(c * 2, 16) for c in hex_val]
                return [int(hex_val[i:i+2], 16) for i in (0, 2, 4)]
            except (ValueError, IndexError):
                logger.warning(f"Invalid color string '{color_string}', using default yellow")
                return [255, 255, 0]
        parts = [p.strip() for p in color.split("\\")]
        if len(parts) == 3:
            try:
                return [int(p) for p in parts]
            except ValueError:
                pass
        logger.warning(f"Invalid color string '{color_string}', using default yellow")
        return [255, 255, 0]


def run_segmentation_pipeline(
    rtstruct_path: str,
    series_instance_uid: str,
    pipeline,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> Dict[str, Any]:
    """Convenience function to run a pipeline and return the summary."""
    engine = SegmentationEngine(rtstruct_path, series_instance_uid)
    return engine.run_pipeline(pipeline, progress_callback=progress_callback)
