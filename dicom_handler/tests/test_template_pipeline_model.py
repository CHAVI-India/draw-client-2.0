"""A1: template one-to-one additional-structures pipeline + EMPTY rule type."""

from django.test import TestCase

from dicom_handler.models import AutosegmentationTemplate
from rule_based_segmentation.models import PipelineRule, SegmentationPipeline


class TemplatePipelineModelTest(TestCase):
    def test_template_has_additional_structures_pipeline_field(self):
        field = AutosegmentationTemplate._meta.get_field(
            "additional_structures_pipeline"
        )
        self.assertTrue(field.one_to_one)
        self.assertTrue(field.null)
        self.assertEqual(field.remote_field.model.__name__, "SegmentationPipeline")

    def test_template_pipeline_link_and_reverse_filter(self):
        template = AutosegmentationTemplate.objects.create(template_name="T")
        template_pipeline = SegmentationPipeline.objects.create(
            name="T — additional structures"
        )
        standalone = SegmentationPipeline.objects.create(name="Standalone")
        template.additional_structures_pipeline = template_pipeline
        template.save()

        # A template-bound pipeline is excluded from the "not template-bound" set
        # that the general RBS pipelines list uses.
        unlinked = SegmentationPipeline.objects.filter(
            additional_structures_template__isnull=True
        )
        self.assertIn(standalone, unlinked)
        self.assertNotIn(template_pipeline, unlinked)
        # Reverse accessor resolves back to the owning template.
        self.assertEqual(template_pipeline.additional_structures_template, template)

    def test_empty_rule_type_is_valid(self):
        p = SegmentationPipeline.objects.create(name="P")
        rule = PipelineRule(
            pipeline=p,
            order=1,
            name="Empty",
            rule_type="EMPTY",
            output_action="CREATE_NEW",
        )
        rule.full_clean()
        rule.save()
        rule.refresh_from_db()
        self.assertEqual(rule.rule_type, "EMPTY")
