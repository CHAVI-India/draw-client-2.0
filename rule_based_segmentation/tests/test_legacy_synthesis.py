"""Tests for synthesize_rules (legacy roi_generation_logic -> RBS rules)."""

from django.test import TestCase

from dicom_handler.models import AdditionalStructures, AutosegmentationTemplate

from ..utils.legacy_synthesis import LegacySynthesisError, synthesize_rules


class LegacySynthesisTests(TestCase):
    def setUp(self):
        self.template = AutosegmentationTemplate.objects.create(template_name="t")

    def _extra(self, logic, label="PTV_final", color="255\\0\\0", roi_type="PTV"):
        return AdditionalStructures.objects.create(
            autosegmentation_template=self.template,
            roi_label=label,
            roi_display_color=color,
            rt_roi_interpreted_type=roi_type,
            roi_generation_logic=logic,
        )

    def test_margin_then_crop_yields_one_exported_rule(self):
        extra = self._extra({"operations": [
            {"type": "margin", "structures": ["CTV"],
             "parameters": {"margin_mm": 5.0, "variant": "UNIFORM"}},
            {"type": "crop_to_boundary", "structures": ["Body"], "parameters": {}},
        ]})
        rules, pipeline = synthesize_rules(extra)
        try:
            self.assertEqual(len(rules), 2)
            self.assertEqual(rules[0].rule_type, "MARGIN")
            self.assertEqual(rules[0].output_action, "INTERMEDIATE")
            self.assertEqual(rules[0].margin_config.source, "CTV")
            self.assertEqual(rules[0].margin_config.margin_mm, 5.0)

            self.assertEqual(rules[1].rule_type, "CROP")
            self.assertEqual(rules[1].output_action, "CREATE_NEW")
            self.assertEqual(rules[1].name, "PTV_final")
            # crop source is the intermediate, not the original CTV
            self.assertEqual(rules[1].crop_config.source, rules[0].name)
            self.assertEqual(
                list(rules[1].crop_config.boundaries.values_list("boundary_roi", flat=True)),
                ["Body"],
            )
            # final rule carries the structure's color + type
            self.assertEqual(rules[1].output_color, "255\\0\\0")
            self.assertEqual(rules[1].output_roi_type, "PTV")
        finally:
            pipeline.delete()

    def test_margin_then_cleanup_consumes_running_result(self):
        extra = self._extra({"operations": [
            {"type": "margin", "structures": ["CTV"],
             "parameters": {"margin_mm": 3.0, "variant": "UNIFORM"}},
            {"type": "keep_largest", "structures": [], "parameters": {}},
        ]})
        rules, pipeline = synthesize_rules(extra)
        try:
            self.assertEqual(rules[1].rule_type, "CLEANUP")
            self.assertEqual(rules[1].cleanup_config.operation, "KEEP_LARGEST_COMPONENT")
            self.assertEqual(rules[1].cleanup_config.source, rules[0].name)
            self.assertEqual(rules[1].name, "PTV_final")
        finally:
            pipeline.delete()

    def test_contract_negates_margin(self):
        extra = self._extra({"operations": [
            {"type": "contract", "structures": ["CTV"],
             "parameters": {"margin_mm": 3.0, "variant": "UNIFORM"}},
        ]})
        rules, pipeline = synthesize_rules(extra)
        try:
            self.assertEqual(rules[0].rule_type, "MARGIN")
            self.assertEqual(rules[0].margin_config.margin_mm, -3.0)
        finally:
            pipeline.delete()

    def test_empty_logic_returns_no_rules(self):
        extra = self._extra(None)
        rules, pipeline = synthesize_rules(extra)
        self.assertEqual(rules, [])
        pipeline.delete()

    def test_unknown_op_raises(self):
        extra = self._extra({"operations": [
            {"type": "not_a_real_op", "structures": ["CTV"], "parameters": {}},
        ]})
        pipeline = None
        try:
            synthesize_rules(extra, pipeline)
            self.fail("expected LegacySynthesisError")
        except LegacySynthesisError:
            pass

    def test_single_op_is_exported_directly(self):
        extra = self._extra({"operations": [
            {"type": "margin", "structures": ["CTV"],
             "parameters": {"margin_mm": 5.0, "variant": "UNIFORM"}},
        ]})
        rules, pipeline = synthesize_rules(extra)
        try:
            self.assertEqual(len(rules), 1)
            self.assertEqual(rules[0].output_action, "CREATE_NEW")
            self.assertEqual(rules[0].name, "PTV_final")
        finally:
            pipeline.delete()
