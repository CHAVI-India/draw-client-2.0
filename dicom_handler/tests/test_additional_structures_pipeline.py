"""AdditionalStructures.pipeline FK + empty-ROI ("no step") semantics."""

from django.test import TestCase

from dicom_handler.models import AdditionalStructures, AutosegmentationTemplate
from rule_based_segmentation.models import PipelineRule, SegmentationPipeline


class AdditionalStructuresPipelineTests(TestCase):
    def setUp(self):
        self.template = AutosegmentationTemplate.objects.create(template_name="t")

    def _mk(self, **kw):
        return AdditionalStructures.objects.create(
            autosegmentation_template=self.template,
            roi_label="ROI",
            **kw,
        )

    def test_no_pipeline_is_not_generated(self):
        s = self._mk()
        self.assertFalse(s.is_generated)

    def test_empty_pipeline_is_not_generated(self):
        pipeline = SegmentationPipeline.objects.create(
            name="empty", is_public=False, is_active=False
        )
        s = self._mk(pipeline=pipeline)
        self.assertFalse(s.is_generated)

    def test_pipeline_with_rules_is_generated(self):
        pipeline = SegmentationPipeline.objects.create(
            name="gen", is_public=False, is_active=False
        )
        PipelineRule.objects.create(
            pipeline=pipeline, order=1, rule_type="MARGIN", name="ROI",
            output_action="CREATE_NEW",
        )
        s = self._mk(pipeline=pipeline)
        self.assertTrue(s.is_generated)

    def test_fk_null_on_delete(self):
        pipeline = SegmentationPipeline.objects.create(
            name="gen", is_public=False, is_active=False
        )
        PipelineRule.objects.create(
            pipeline=pipeline, order=1, rule_type="MARGIN", name="ROI",
            output_action="CREATE_NEW",
        )
        s = self._mk(pipeline=pipeline)
        pid = s.pipeline_id
        pipeline.delete()
        s.refresh_from_db()
        self.assertIsNone(s.pipeline_id)
        self.assertFalse(s.is_generated)
