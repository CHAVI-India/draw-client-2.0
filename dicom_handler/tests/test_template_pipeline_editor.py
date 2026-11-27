"""A3: template pipeline editor (one pipeline per template)."""

import json

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from dicom_handler.models import AutosegmentationTemplate
from rule_based_segmentation.models import SegmentationPipeline
from dicom_handler.utils.template_pipeline import (
    template_pipeline_for,
    template_pipeline_name,
)


class TemplatePipelineEditorTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(username="editor", password="pw", email="e@x.com")
        self.template = AutosegmentationTemplate.objects.create(
            template_name="Head & Neck",
            template_description="test",
        )

    def test_editor_view_renders(self):
        url = reverse("dicom_handler:template_pipeline_view", args=[self.template.id])
        self.client.force_login(self.user)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Additional Structures")
        self.assertContains(resp, "Structure Generation Rules")

    def test_template_pipeline_for_returns_or_creates(self):
        p1 = template_pipeline_for(self.template)
        self.assertEqual(p1.name, template_pipeline_name(self.template))
        self.assertFalse(p1.is_public)
        self.assertTrue(p1.is_active)
        # second call returns the same instance (not a new one)
        self.template.refresh_from_db()
        self.assertEqual(template_pipeline_for(self.template), p1)
        self.assertEqual(SegmentationPipeline.objects.count(), 1)

    def test_save_creates_and_links_pipeline(self):
        pipeline_data = {
            "name": template_pipeline_name(self.template),
            "is_public": False,
            "structures": ["CTV"],
            "rules": [
                {"rule_type": "MARGIN", "name": "PTV", "output_action": "CREATE_NEW",
                 "config": {"source": "CTV", "margin_l_mm": 5}, "tempId": "t1"},
                {"rule_type": "EMPTY", "name": "EmptyROI", "output_action": "CREATE_NEW",
                 "config": {}, "tempId": "t2"},
            ],
        }
        url = reverse("dicom_handler:template_pipeline_save", args=[self.template.id])
        self.client.force_login(self.user)
        resp = self.client.post(
            url, {"pipeline_data": json.dumps(pipeline_data)}
        )
        # save redirects to template detail on success
        self.assertEqual(resp.status_code, 302)
        self.template.refresh_from_db()
        pipeline = self.template.additional_structures_pipeline
        self.assertIsNotNone(pipeline, "template must be linked to its pipeline")
        self.assertEqual(pipeline.name, template_pipeline_name(self.template))
        self.assertFalse(pipeline.is_public)
        self.assertTrue(pipeline.is_active)
        self.assertEqual(pipeline.rules.count(), 2)
        self.assertEqual(
            set(pipeline.rules.values_list("rule_type", flat=True)),
            {"MARGIN", "EMPTY"},
        )

    def test_save_replaces_stale_rules(self):
        url = reverse("dicom_handler:template_pipeline_save", args=[self.template.id])
        first = {
            "name": template_pipeline_name(self.template),
            "structures": ["CTV"],
            "rules": [
                {"rule_type": "EMPTY", "name": "A", "output_action": "CREATE_NEW",
                 "config": {}, "tempId": "a"},
            ],
        }
        self.client.force_login(self.user)
        self.client.post(url, {"pipeline_data": json.dumps(first)})
        self.template.refresh_from_db()
        p = self.template.additional_structures_pipeline
        self.assertEqual(p.rules.count(), 1)

        second = {
            "name": template_pipeline_name(self.template),
            "structures": ["CTV"],
            "rules": [
                {"rule_type": "EMPTY", "name": "B", "output_action": "CREATE_NEW",
                 "config": {}, "tempId": "b"},
            ],
        }
        self.client.post(url, {"pipeline_data": json.dumps(second)})
        p.refresh_from_db()
        # still one pipeline, rules replaced (no orphan/duplicate rule)
        self.assertEqual(SegmentationPipeline.objects.count(), 1)
        self.assertEqual([r.name for r in p.rules.all()], ["B"])

    def test_template_pipeline_hidden_from_rbs_list(self):
        from rule_based_segmentation.utils.pipeline_persistence import (
            save_pipeline_from_dict,
        )

        template_pipeline = template_pipeline_for(self.template)
        self.template.additional_structures_pipeline = template_pipeline
        self.template.save()
        standalone = save_pipeline_from_dict(
            {"name": "Standalone", "structures": [], "rules": []}, self.user
        )

        visible = SegmentationPipeline.objects.filter(
            additional_structures_template__isnull=True
        )
        self.assertIn(standalone, visible)
        self.assertNotIn(template_pipeline, visible)
