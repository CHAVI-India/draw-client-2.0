"""Template detail: additional-structures section shows ONE pipeline entry
point.

The additional ROIs of a template are defined by the template's single
additional-structures pipeline (Phase 5 / A6), so the detail page must offer
a single "Edit pipeline" button — not a per-ROI edit link. The old per-row
links pointed at ``pipeline_builder_edit`` / ``edit_additional_structure``,
URLs that no longer exist.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse

from dicom_handler.models import AutosegmentationTemplate
from rule_based_segmentation.utils.pipeline_persistence import (
    save_pipeline_from_dict,
)


def _pipeline(user, rules):
    return save_pipeline_from_dict(
        {
            "name": "additional structures",
            "structures": ["X"],
            "rules": rules,
        },
        user,
    )


class TemplateDetailAdditionalButtonTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="detail_chk", email="d@e.f", password="pw"
        )
        self.client = Client()
        self.client.force_login(self.user)

    def _detail_html(self, template):
        response = self.client.get(
            reverse("dicom_handler:template_detail", args=[template.id])
        )
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def _pipeline_url(self, template):
        return reverse("dicom_handler:template_pipeline_view", args=[template.id])

    def test_single_edit_pipeline_button_when_rules_exist(self):
        template = AutosegmentationTemplate.objects.create(template_name="T1")
        pipeline = _pipeline(
            self.user,
            [
                {"rule_type": "EMPTY", "name": "Spa", "output_action": "CREATE_NEW",
                 "config": {}, "tempId": "1"},
                {"rule_type": "MARGIN", "name": "PTV", "output_action": "CREATE_NEW",
                 "config": {"source": "X", "margin_mm": 3.0, "kernel_type": "ball"},
                 "tempId": "2"},
            ],
        )
        template.additional_structures_pipeline = pipeline
        template.save()

        html = self._detail_html(template)

        # Exactly one entry point to the pipeline editor...
        self.assertEqual(html.count(f'href="{self._pipeline_url(template)}"'), 1)
        self.assertIn("Edit pipeline", html)
        # ...and both additional ROIs are listed (read-only).
        self.assertIn("Spa", html)
        self.assertIn("PTV", html)
        # No per-ROI edit links to the removed pre-A6 URLs.
        self.assertNotIn("pipeline_builder_edit", html)
        self.assertNotIn("edit_additional_structure", html)

    def test_add_button_when_no_pipeline_rules(self):
        template = AutosegmentationTemplate.objects.create(template_name="T2")
        html = self._detail_html(template)

        self.assertEqual(html.count(f'href="{self._pipeline_url(template)}"'), 1)
        self.assertIn("Add additional structures", html)
        self.assertNotIn("Edit pipeline", html)
