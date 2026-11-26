"""Full-page pipeline builder now authors RBS pipelines (UI swap, Phase 4)."""

from django.test import TestCase
from django.contrib.auth.models import User
from django.urls import reverse

from dicom_handler.models import (
    AdditionalStructures,
    AutosegmentationTemplate,
    AutosegmentationModel,
    AutosegmentationStructure,
)
from rule_based_segmentation.models import SegmentationPipeline


def _setup_template():
    template = AutosegmentationTemplate.objects.create(
        template_name="T"
    )
    model = AutosegmentationModel.objects.create(
        name="Model", autosegmentation_template_name=template
    )
    AutosegmentationStructure.objects.create(name="BaseROI", autosegmentation_model=model)
    return template, model


def _make_user():
    return User.objects.create_user(username="pb", password="x", is_staff=True)


class PipelineBuilderUIViewTests(TestCase):
    def setUp(self):
        self.user = _make_user()
        self._login()

    def _login(self):
        from django.contrib.auth.models import Permission
        from django.contrib.contenttypes.models import ContentType
        ct = ContentType.objects.get(app_label="dicom_handler", model="additionalstructures")
        perms = Permission.objects.filter(
            content_type=ct,
            codename__in=["add_additionalstructures", "change_additionalstructures"],
        )
        self.user.user_permissions.add(*perms)
        self.client.login(username="pb", password="x")

    def test_new_renders_rbs_builder(self):
        self._login()
        template, _ = _setup_template()
        response = self.client.get(reverse("dicom_handler:pipeline_builder_new", args=[template.id]))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("rule_based_pipeline_builder.js", html)
        self.assertNotIn("/static/js/pipeline_builder.js", html)
        self.assertIn('name="pipeline_data"', html)
        self.assertNotIn('name="roi_generation_logic"', html)

    def test_save_new_persists_pipeline_fk(self):
        self._login()
        template, _ = _setup_template()
        import json
        payload = {
            "mode": "new",
            "template_id": str(template.id),
            "roi_label": "Derived",
            "rt_roi_interpreted_type": "",
            "roi_display_color": "255\\0\\0",
            "pipeline_data": json.dumps({
                "rules": [{
                    "order": 1, "name": "Derived", "rule_type": "MARGIN",
                    "output_action": "EXPORT_TO_RTSTRUCT",
                    "output_color": "255\\0\\0", "output_roi_type": "",
                    "config": {"source": "BaseROI", "direction": "EXPAND",
                               "isotropic_mm": 5.0, "lateral_mm": None,
                               "posterior_mm": None, "inferior_mm": None,
                               "anterior_mm": None, "superior_mm": None,
                               "rothello_mm": None,
                               "smoothing_mm": 1.0, "iterations": 1},
                }],
                "structures": [],
            }),
        }
        response = self.client.post(reverse("dicom_handler:pipeline_builder_save"), payload)
        structure = AdditionalStructures.objects.get(roi_label="Derived")
        self.assertIsNotNone(structure.pipeline)
        self.assertEqual(structure.pipeline.rules.count(), 1)

    def test_save_new_empty_is_empty_roi(self):
        self._login()
        template, _ = _setup_template()
        import json
        payload = {
            "mode": "new",
            "template_id": str(template.id),
            "roi_label": "EmptyROI",
            "roi_display_color": "0\\255\\0",
            "pipeline_data": json.dumps({"rules": [], "structures": []}),
        }
        self.client.post(reverse("dicom_handler:pipeline_builder_save"), payload)
        structure = AdditionalStructures.objects.get(roi_label="EmptyROI")
        self.assertIsNotNone(structure.pipeline)
        self.assertEqual(structure.pipeline.rules.count(), 0)
