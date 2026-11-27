"""One-off (Phase 5, A5): consolidate each template's per-row additional-structure
pipelines into a SINGLE template pipeline.

``template.additional_structures_pipeline`` becomes the one
SegmentationPipeline that holds every additional structure for the template:

- A row that has a ``pipeline`` FK contributes all of its rules (in order).
- A row with no pipeline (an empty-ROI placeholder) contributes a single
  ``EMPTY`` rule (CREATE_NEW, named after ``roi_label`` with the row's
  color/type).

Duplicate output names across the merged rules are auto-suffixed and their
references are rewritten across all merged configs.

State-agnostic + idempotent: templates that already have a pipeline are skipped;
templates with no additional structures are left alone (their pipeline is created
lazily by the editor / ``template_pipeline_for``). The per-row ``pipeline`` FKs and
the ``AdditionalStructures`` rows are left intact (A6 drops the model). Safe to run
repeatedly; runs in a single transaction.
"""

import logging

from django.db import migrations, transaction

logger = logging.getLogger(__name__)


def _rename_in_rule(rule, old, new):
    """Replace structure name ``old`` with ``new`` inside a builder rule dict."""
    cfg = rule.get("config")
    if not isinstance(cfg, dict):
        return
    if rule.get("rule_type") == "BOOLEAN":
        def walk(node):
            if not isinstance(node, dict):
                return
            if node.get("name") == old:
                node["name"] = new
            for child in node.get("operands", []):
                walk(child)
        walk(cfg)
        return
    for key in ("source", "seed_roi", "boundary_roi", "avoid", "subtract"):
        if isinstance(cfg.get(key), str) and cfg[key] == old:
            cfg[key] = new
    for key in ("boundaries", "others"):
        if isinstance(cfg.get(key), list):
            cfg[key] = [new if x == old else x for x in cfg[key]]


def _dedupe_names(rules):
    """Suffix duplicate output names and rewrite references across all rules.

    Returns the number of renames. ``rules`` are mutated in place.
    """
    seen = set()
    renames = 0
    for rule in rules:
        name = rule.get("name") or ""
        if not name or name not in seen:
            if name:
                seen.add(name)
            continue
        base = name
        i = 1
        while f"{base}_{i}" in seen:
            i += 1
        newname = f"{base}_{i}"
        for other in rules:
            if other is not rule:
                _rename_in_rule(other, name, newname)
        rule["name"] = newname
        seen.add(newname)
        renames += 1
    return renames


def _migrate(apps, schema_editor):
    from dicom_handler.models import AdditionalStructures, AutosegmentationTemplate
    from dicom_handler.utils.template_pipeline import template_pipeline_name
    from rule_based_segmentation.models import SegmentationPipeline
    from rule_based_segmentation.utils.pipeline_persistence import (
        pipeline_data_from_pipeline,
        save_pipeline_from_dict,
    )

    consolidated = 0
    renames_total = 0
    with transaction.atomic():
        for template in AutosegmentationTemplate.objects.all():
            if template.additional_structures_pipeline is not None:
                continue  # already consolidated (idempotent)

            rows = list(
                AdditionalStructures.objects.filter(
                    autosegmentation_template=template
                ).order_by("roi_label", "id")
            )
            if not rows:
                continue  # no additional structures; pipeline created lazily

            merged_rules = []
            merged_structures = []
            for row in rows:
                if row.pipeline_id:
                    data = pipeline_data_from_pipeline(row.pipeline)
                    merged_rules.extend(data.get("rules", []))
                    for s in data.get("structures", []):
                        if s not in merged_structures:
                            merged_structures.append(s)
                else:
                    # empty-ROI placeholder -> EMPTY rule
                    merged_rules.append(
                        {
                            "rule_type": "EMPTY",
                            "name": row.roi_label,
                            "output_action": "CREATE_NEW",
                            "output_color": row.roi_display_color or "255\\255\\0",
                            "output_roi_type": row.rt_roi_interpreted_type or "ORGAN",
                            "config": {},
                        }
                    )

            renames_total += _dedupe_names(merged_rules)

            new_pipeline = SegmentationPipeline.objects.create(
                name=template_pipeline_name(template),
                is_public=False,
                is_active=True,
            )
            save_pipeline_from_dict(
                {
                    "name": template_pipeline_name(template),
                    "description": (
                        f"Consolidated additional structures for "
                        f"'{template.template_name}'."
                    ),
                    "is_public": False,
                    "structures": merged_structures,
                    "rules": merged_rules,
                },
                None,
                pipeline=new_pipeline,
            )
            new_pipeline.is_active = True
            new_pipeline.save(update_fields=["is_active"])
            template.additional_structures_pipeline = new_pipeline
            template.save(update_fields=["additional_structures_pipeline"])
            consolidated += 1

    logger.info(
        "Consolidated %d template pipeline(s); renamed %d name collision(s).",
        consolidated,
        renames_total,
    )


def _reverse(apps, schema_editor):
    # No-op: leave the consolidated pipelines and the (soon-to-be-dropped)
    # AdditionalStructures rows in place; the OneToOne field is optional.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("dicom_handler", "0063_autosegmentationtemplate_additional_structures_pipeline"),
    ]

    operations = [
        migrations.RunPython(_migrate, _reverse),
    ]
