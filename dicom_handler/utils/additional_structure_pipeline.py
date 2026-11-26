"""Shared persistence for template-driven additional-structure pipelines.

Both the inline additional-structure form and the full-page pipeline builder
author an ``AdditionalStructures`` row whose generation is a
``SegmentationPipeline``. This module centralizes:
- the set of ROIs a pipeline may reference for a template (validation), and
- turning the posted ``pipeline_data`` into a pinned, validated pipeline.
"""

import logging

from dicom_handler.models import AdditionalStructures, AutosegmentationStructure
from rule_based_segmentation.models import SegmentationPipeline
from rule_based_segmentation.utils.pipeline_persistence import (
    parse_pipeline_data,
    pin_final_rule,
    referenced_structure_names,
    save_pipeline_from_dict,
)

logger = logging.getLogger(__name__)


def available_structure_names(template, exclude_structure=None):
    """ROIs an additional-structure pipeline may reference for a template.

    Base ROIs (the template's reidentified structure set) + sibling
    additional-structure labels.
    """
    names = set()
    base = (
        AutosegmentationStructure.objects.filter(
            autosegmentation_model__autosegmentation_template_name=template
        )
        .select_related("structureproperties")
    )
    for struct in base:
        props = getattr(struct, "structureproperties", None)
        if props and props.roi_label:
            names.add(props.roi_label)
        if struct.name:
            names.add(struct.name)
    siblings = AdditionalStructures.objects.filter(autosegmentation_template=template)
    if exclude_structure is not None and exclude_structure.pk:
        siblings = siblings.exclude(pk=exclude_structure.pk)
    names.update(siblings.values_list("roi_label", flat=True))
    return names


def save_pipeline_for_structure(request, template, structure, existing_pipeline=None):
    """Persist the posted pipeline for an additional structure.

    Parses ``pipeline_data``, creates/refreshes a SegmentationPipeline, pins the
    final rule to the structure's identity, and validates that every referenced
    structure belongs to the template. Returns the pipeline (zero rules == empty
    ROI). Raises ``ValidationError`` on a bad reference set (and removes any
    orphan). The caller should run this inside a transaction.
    """
    from django.core.exceptions import ValidationError

    data = parse_pipeline_data(request.POST)

    if data is None:
        # No builder payload: an empty ROI ("no step"). Keep an explicit (empty)
        # pipeline so the FK is always present.
        if existing_pipeline is None:
            existing_pipeline = SegmentationPipeline.objects.create(
                name=f"{structure.roi_label} generation",
                is_public=False, is_active=False,
            )
        return existing_pipeline

    rules = data.get("rules", [])
    if existing_pipeline is None:
        pipeline = save_pipeline_from_dict(data, request.user)
    else:
        pipeline = save_pipeline_from_dict(data, request.user, pipeline=existing_pipeline)

    # Stable, descriptive name; keep it private + inactive (it is not a
    # standalone job pipeline).
    pipeline.name = f"{structure.roi_label} generation"
    pipeline.is_public = False
    pipeline.is_active = False
    pipeline.save(update_fields=["name", "is_public", "is_active"])

    # Pin the exported ROI to the binding (name / color / interpreted type).
    pin_final_rule(
        pipeline,
        structure.roi_label,
        structure.roi_display_color,
        structure.rt_roi_interpreted_type,
    )

    # Validate references: every input structure must be part of the template,
    # except names produced by the pipeline itself (intermediates + final).
    referenced = referenced_structure_names(rules)
    produced = {r.get("name", "").strip() for r in rules}
    available = available_structure_names(template, exclude_structure=structure)
    missing = (referenced - available) - produced
    if missing:
        pipeline.delete()  # drop the orphan if we are not going to keep it
        raise ValidationError({
            "pipeline": (
                "These structures are not part of the template: "
                f"{', '.join(sorted(missing))}"
            )
        })
    return pipeline
