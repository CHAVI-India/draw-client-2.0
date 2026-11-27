"""Normalize ``PipelineRule.output_color`` to the canonical DICOM ``R\\G\\B``.

The color column drifted: the web builder (a native ``<input type=color>``) saved
hex (``#RRGGBB``), while migrations/XML/legacy/defaults stored the DICOM-native
``R\\G\\B``. The engine tolerates both, but the UI read-back (``_rgb_dicom_to_hex``)
only understood ``R\\G\\B``, so hex rows read back as yellow. Going forward,
``_save_rule`` stores the canonical ``R\\G\\B`` (see
``docs/COLOR_FORMAT_AUDIT.md``); this one-off migration converts the hex rows
that were already saved.

Portable: idempotent (only hex rows are touched; after conversion there are
none), transactional, and self-contained (no import of the live app module).
"""

from django.db import migrations


def _hex_to_rgb(color_string):
    """Hex (#RGB / #RRGGBB) -> R\\G\\B; non-hex returned unchanged."""
    s = (color_string or "").strip()
    if not s.startswith("#"):
        return color_string
    hv = s[1:]
    try:
        if len(hv) == 3:
            hv = "".join(c * 2 for c in hv)
        return f"{int(hv[0:2], 16)}\\{int(hv[2:4], 16)}\\{int(hv[4:6], 16)}"
    except (ValueError, IndexError):
        return color_string


def normalize(apps, schema_editor):
    PipelineRule = apps.get_model("rule_based_segmentation", "PipelineRule")
    for rule in PipelineRule.objects.filter(output_color__startswith="#"):
        rule.output_color = _hex_to_rgb(rule.output_color)
        rule.save(update_fields=["output_color"])


def reverse(apps, schema_editor):
    """Convert R\\G\\B back to hex (rollback only)."""
    PipelineRule = apps.get_model("rule_based_segmentation", "PipelineRule")
    for rule in PipelineRule.objects.filter(output_color__contains="\\"):
        try:
            r, g, b = (int(p) for p in rule.output_color.split("\\") if p != "")
            if len([r, g, b]) == 3 and all(0 <= x <= 255 for x in (r, g, b)):
                rule.output_color = f"#{r:02X}{g:02X}{b:02X}"
                rule.save(update_fields=["output_color"])
        except (ValueError, TypeError):
            continue


class Migration(migrations.Migration):

    dependencies = [
        ("rule_based_segmentation", "0015_alter_pipelinerule_rule_type"),
    ]

    operations = [
        migrations.RunPython(normalize, reverse, atomic=True),
    ]
