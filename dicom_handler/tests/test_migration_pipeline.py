"""Test the one-off migration that converts roi_generation_logic to RBS pipelines."""

import importlib
from django.apps import apps as live_apps
from django.test import TestCase

from dicom_handler.models import AdditionalStructures, AutosegmentationTemplate
from rule_based_segmentation.models import PipelineRule, SegmentationPipeline

_MIG = importlib.import_module(
    "dicom_handler.migrations.0062_migrate_additionalstructures_pipeline"
)

CHAIN = {"operations": [
    {"type": "margin", "structures": ["CTV"],
     "parameters": {"margin_mm": 5.0, "variant": "UNIFORM"}},
    {"type": "crop_to_boundary", "structures": ["Body"], "parameters": {}},
    {"type": "smooth", "structures": [],
     "parameters": {"smoothing_mm": 1.0, "iterations": 1}},
]}


class MigrationPipelineTests(TestCase):
    def _extra(self, **kw):
        template = AutosegmentationTemplate.objects.create(template_name="t")
        return AdditionalStructures.objects.create(
            autosegmentation_template=template, **kw
        )

    def test_converts_chain_pins_final_and_sets_fk(self):
        extra = self._extra(
            roi_label="PTV_final", rt_roi_interpreted_type="PTV",
            roi_display_color="255\\0\\0", roi_generation_logic=CHAIN,
        )
        _MIG._migrate(live_apps, None)

        extra.refresh_from_db()
        self.assertIsNotNone(extra.pipeline_id, "migration should set the FK")
        rules = list(extra.pipeline.rules.all().order_by("order"))
        self.assertEqual(len(rules), 3)
        self.assertEqual([r.output_action for r in rules],
                         ["INTERMEDIATE", "INTERMEDIATE", "CREATE_NEW"])
        self.assertEqual(rules[0].rule_type, "MARGIN")
        self.assertEqual(rules[2].name, "PTV_final")
        self.assertEqual(rules[2].output_color, "255\\0\\0")
        self.assertEqual(rules[2].output_roi_type, "PTV")

    def test_empty_roi_gets_no_pipeline(self):
        extra = self._extra(roi_label="Spa")
        _MIG._migrate(live_apps, None)
        extra.refresh_from_db()
        self.assertIsNone(extra.pipeline_id)

    def test_idempotent(self):
        extra = self._extra(roi_label="PTV_final", roi_generation_logic=CHAIN)
        _MIG._migrate(live_apps, None)
        extra.refresh_from_db()
        first_pipeline = extra.pipeline
        count_before = SegmentationPipeline.objects.count()

        _MIG._migrate(live_apps, None)  # run again

        extra.refresh_from_db()
        self.assertEqual(extra.pipeline, first_pipeline,
                         "second run must not create a new pipeline")
        self.assertEqual(SegmentationPipeline.objects.count(), count_before)
        self.assertEqual(first_pipeline.rules.count(), 3)
