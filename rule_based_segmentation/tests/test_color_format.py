"""Color-format canonicalization (see docs/COLOR_FORMAT_AUDIT.md).

The DB column stores the canonical DICOM ``R\\G\\B``; hex is only the UI format.
These tests lock in:
  * the hex<->RGB helpers,
  * that a UI-saved hex color is stored as ``R\\G\\B``,
  * the read-back round-trip (no more "colors turn yellow on re-edit"), and
  * the one-off migration that converts pre-existing hex rows.
"""

from django.test import TestCase

from ..models import PipelineRule, SegmentationPipeline
from ..utils.pipeline_persistence import (
    _hex_to_rgb_dicom,
    _rgb_dicom_to_hex,
    pipeline_data_from_pipeline,
    save_pipeline_from_dict,
)


class HexRgbHelperTests(TestCase):
    def test_rgb_to_hex(self):
        self.assertEqual(_rgb_dicom_to_hex("255\\0\\0"), "#FF0000")
        self.assertEqual(_rgb_dicom_to_hex("0\\255\\0"), "#00FF00")
        self.assertEqual(_rgb_dicom_to_hex("0\\0\\255"), "#0000FF")
        self.assertEqual(_rgb_dicom_to_hex(None), "#FFFF00")
        self.assertEqual(_rgb_dicom_to_hex(""), "#FFFF00")

    def test_rgb_to_hex_now_tolerates_hex(self):
        # The data-loss bug: a hex value must round-trip, not collapse to yellow.
        self.assertEqual(_rgb_dicom_to_hex("#FF0000"), "#FF0000")
        self.assertEqual(_rgb_dicom_to_hex("#ff0000"), "#FF0000")
        self.assertEqual(_rgb_dicom_to_hex("#C0C0C0"), "#C0C0C0")
        self.assertEqual(_rgb_dicom_to_hex("#F00"), "#FF0000")  # 3-digit expands

    def test_hex_to_rgb(self):
        self.assertEqual(_hex_to_rgb_dicom("#FF0000"), "255\\0\\0")
        self.assertEqual(_hex_to_rgb_dicom("#00FF00"), "0\\255\\0")
        self.assertEqual(_hex_to_rgb_dicom("#F00"), "255\\0\\0")
        self.assertEqual(_hex_to_rgb_dicom("255\\0\\0"), "255\\0\\0")  # RGB unchanged
        self.assertEqual(_hex_to_rgb_dicom(""), "")
        self.assertEqual(_hex_to_rgb_dicom(None), None)


def _rule_data(color):
    return {
        "rule_type": "MARGIN",
        "name": "out",
        "output_action": "CREATE_NEW",
        "output_color": color,
        "output_roi_type": "PTV",
        "config": {"variant": "UNIFORM", "source": "CTV",
                   "margin_mm": 1.0, "kernel_type": "ball"},
    }


class SaveNormalizesToRgbTests(TestCase):
    def test_hex_saved_from_builder_is_stored_as_rgb(self):
        p = save_pipeline_from_dict(
            {"name": "p", "rules": [_rule_data("#FF0000")]}, user=None
        )
        self.assertEqual(p.rules.first().output_color, "255\\0\\0")

    def test_rgb_saved_from_builder_is_stored_as_rgb(self):
        p = save_pipeline_from_dict(
            {"name": "p", "rules": [_rule_data("0\\255\\0")]}, user=None
        )
        self.assertEqual(p.rules.first().output_color, "0\\255\\0")

    def test_round_trip_preserves_color(self):
        # Save a hex color, read it back for the UI, and confirm it is unchanged
        # (not yellow). This is the exact regression behind "colors turn yellow".
        p = save_pipeline_from_dict(
            {"name": "p", "rules": [_rule_data("#C0C0C0")]}, user=None
        )
        data = pipeline_data_from_pipeline(p)
        self.assertEqual(data["rules"][0]["output_color"], "#C0C0C0")


def _migration_module():
    import importlib

    return importlib.import_module(
        "rule_based_segmentation.migrations.0016_normalize_output_color_to_rgb"
    )


class ColorMigrationTests(TestCase):
    def test_migration_converts_hex_rows_to_rgb(self):
        from django.apps import apps as live_apps

        # Simulate pre-migration hex rows by writing directly (bypass _save_rule).
        p = SegmentationPipeline.objects.create(name="p")
        PipelineRule.objects.create(
            pipeline=p, order=1, name="a", rule_type="MARGIN",
            output_action="CREATE_NEW", output_color="#FF0000",
        )
        PipelineRule.objects.create(
            pipeline=p, order=2, name="b", rule_type="MARGIN",
            output_action="CREATE_NEW", output_color="0\\255\\0",  # already RGB
        )
        PipelineRule.objects.create(
            pipeline=p, order=3, name="c", rule_type="MARGIN",
            output_action="CREATE_NEW", output_color=None,  # leave NULL
        )

        mod = _migration_module()
        mod.normalize(live_apps, None)

        self.assertEqual(PipelineRule.objects.get(name="a").output_color, "255\\0\\0")
        self.assertEqual(PipelineRule.objects.get(name="b").output_color, "0\\255\\0")
        self.assertIsNone(PipelineRule.objects.get(name="c").output_color)

        # Idempotent: a second run changes nothing.
        mod.normalize(live_apps, None)
        self.assertEqual(PipelineRule.objects.get(name="a").output_color, "255\\0\\0")
