"""The template's additional-structures pipeline.

A template has ONE ``SegmentationPipeline`` (linked via
``AutosegmentationTemplate.additional_structures_pipeline``) that defines all of
its additional ROIs. Every ``output_action=CREATE_NEW`` rule is one additional
structure; ``INTERMEDIATE`` rules are working ROIs; ``EMPTY`` rules create an
empty (zero-voxel) ROI. This module provides the return-or-create helper and
the fixed pipeline-name convention used by the editor, task2 execution, and the
consolidation migration.
"""

from rule_based_segmentation.models import SegmentationPipeline

PIPELINE_NAME_SUFFIX = " — additional structures"
# SegmentationPipeline.name is max_length=256; keep the convention name within it.
PIPELINE_NAME_MAX = 256


def template_pipeline_name(template) -> str:
    """The fixed convention name for a template's pipeline (<= 256 chars)."""
    base = template.template_name[: PIPELINE_NAME_MAX - len(PIPELINE_NAME_SUFFIX)]
    return f"{base}{PIPELINE_NAME_SUFFIX}"


def template_pipeline_for(template) -> SegmentationPipeline:
    """Return the template's additional-structures pipeline, creating and
    linking it on demand with the fixed name / private / active convention.

    Idempotent: once linked, subsequent calls return the same pipeline.
    """
    pipeline = getattr(template, "additional_structures_pipeline", None)
    if pipeline is not None:
        return pipeline
    pipeline = SegmentationPipeline.objects.create(
        name=template_pipeline_name(template),
        is_public=False,
        is_active=True,
    )
    template.additional_structures_pipeline = pipeline
    template.save(update_fields=["additional_structures_pipeline"])
    return pipeline
