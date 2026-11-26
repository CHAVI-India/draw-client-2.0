"""One-off: convert AdditionalStructures.roi_generation_logic into RBS pipelines.

For each additional structure that has a non-empty generation chain and no
pipeline yet, synthesize a private SegmentationPipeline and point the FK at it.
``synthesize_rules`` already pins the final rule to ``roi_label`` (CREATE_NEW,
with the structure's color/type) and forces earlier rules to INTERMEDIATE, so no
extra pinning is needed here. Idempotent: rows that already have a pipeline are
skipped. ``roi_generation_logic`` is preserved (frozen fallback until Phase 5).
"""

import logging

from django.db import migrations

logger = logging.getLogger(__name__)


def _migrate(apps, schema_editor):
    # Tail data migration: RBS model migrations (0012-0014) and dicom_handler.0061
    # are already applied, so the live model classes match the database schema at
    # this point. Use live classes consistently (mixing the historical ``apps``
    # registry with the live classes used inside ``synthesize_rules`` would trip
    # Django's cross-registry FK type check).
    from dicom_handler.models import AdditionalStructures
    from rule_based_segmentation.models import SegmentationPipeline
    from rule_based_segmentation.utils.legacy_synthesis import synthesize_rules

    converted = 0
    skipped = 0
    for extra in AdditionalStructures.objects.all():
        if extra.pipeline_id:
            skipped += 1
            continue
        logic = extra.roi_generation_logic
        if not (logic and (logic.get("operations") or [])):
            continue  # empty ROI: no pipeline needed (the "no step" case)
        pipeline = SegmentationPipeline.objects.create(
            name=f"{extra.roi_label} generation",
            description=f"Synthesized from roi_generation_logic for '{extra.roi_label}'.",
            is_public=False,
            is_active=False,
        )
        rules, _ = synthesize_rules(extra, pipeline=pipeline)
        extra.pipeline = pipeline
        extra.save(update_fields=["pipeline"])
        converted += 1

    logger.info(
        "Migrated %d additional structure(s) to RBS pipelines (%d already had a pipeline).",
        converted, skipped,
    )


def _reverse(apps, schema_editor):
    # No-op: leave the synthesized pipelines in place and keep the frozen
    # roi_generation_logic. The FK is optional, so nothing else to undo.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("dicom_handler", "0061_additionalstructures_pipeline"),
        ("rule_based_segmentation", "0014_roi_name_limit_54"),
    ]

    operations = [
        migrations.RunPython(_migrate, _reverse),
    ]
