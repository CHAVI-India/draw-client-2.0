"""Additional-structure views manage a SegmentationPipeline (Phase 4)."""

import json
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from dicom_handler.models import AdditionalStructures, AutosegmentationTemplate
from rule_based_segmentation.models import SegmentationPipeline

User = get_user_model()


def _margin_data(source, name="PTV_final"):
    return json.dumps({
        "name": "gen", "is_public": False, "structures": [source],
        "rules": [{
            "rule_type": "MARGIN", "name": name, "output_action": "CREATE_NEW",
            "output_color": "#FF0000", "output_roi_type": "PTV",
            "config": {"source": source, "margin_mm": 5.0},
        }],
    })


class AdditionalStructureViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(username="admin", password="pw")
        self.client.force_login(self.user)
        self.template = AutosegmentationTemplate.objects.create(template_name="t")
        # A sibling structure provides an available input "CTV".
        AdditionalStructures.objects.create(
            autosegmentation_template=self.template, roi_label="CTV",
        )
        self.add_url = reverse("dicom_handler:add_additional_structure")
        self.edit_url = reverse("dicom_handler:edit_additional_structure")

    def _post(self, url, data):
        return self.client.post(url, data)

    def test_add_creates_pipeline_and_pins_final_rule(self):
        resp = self._post(self.add_url, {
            "template_id": str(self.template.pk),
            "roi_label": "PTV_final",
            "rt_roi_interpreted_type": "PTV",
            "roi_display_color": "255\\0\\0",
            "pipeline_data": _margin_data("CTV"),
        })
        self.assertEqual(resp.status_code, 302)

        s = AdditionalStructures.objects.get(
            autosegmentation_template=self.template, roi_label="PTV_final")
        self.assertIsNotNone(s.pipeline_id)
        rules = list(s.pipeline.rules.all().order_by("order"))
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].name, "PTV_final")  # pinned to the binding
        self.assertEqual(rules[0].output_action, "CREATE_NEW")
        self.assertEqual(rules[0].output_color, "255\\0\\0")  # binding's DICOM color
        self.assertEqual(rules[0].output_roi_type, "PTV")
        # pipeline is private + inactive
        self.assertFalse(s.pipeline.is_public)
        self.assertFalse(s.pipeline.is_active)

    def test_add_rejects_reference_to_unknown_structure(self):
        before = AdditionalStructures.objects.count()
        self._post(self.add_url, {
            "template_id": str(self.template.pk),
            "roi_label": "BadRef",
            "roi_display_color": "255\\0\\0",
            "pipeline_data": _margin_data("Ghost"),
        })
        self.assertFalse(
            AdditionalStructures.objects.filter(roi_label="BadRef").exists(),
            "a structure referencing an unknown structure must not be created")
        self.assertEqual(AdditionalStructures.objects.count(), before)
        # no orphan pipeline left behind
        self.assertFalse(
            SegmentationPipeline.objects.filter(name="BadRef generation").exists())

    def test_add_empty_payload_is_empty_roi(self):
        self._post(self.add_url, {
            "template_id": str(self.template.pk),
            "roi_label": "Spa",
            "roi_display_color": "0\\255\\0",
        })
        s = AdditionalStructures.objects.get(
            autosegmentation_template=self.template, roi_label="Spa")
        self.assertIsNotNone(s.pipeline_id)
        self.assertEqual(s.pipeline.rules.count(), 0)  # "no step"
        self.assertFalse(s.is_generated)

    def test_edit_reuses_existing_pipeline(self):
        s = self._post(self.add_url, {
            "template_id": str(self.template.pk),
            "roi_label": "PTV_final",
            "rt_roi_interpreted_type": "PTV",
            "roi_display_color": "255\\0\\0",
            "pipeline_data": _margin_data("CTV"),
        })
        s = AdditionalStructures.objects.get(
            autosegmentation_template=self.template, roi_label="PTV_final")
        original_pipeline = s.pipeline

        self._post(self.edit_url, {
            "structure_id": str(s.pk),
            "template_id": str(self.template.pk),
            "roi_label": "PTV_final",
            "rt_roi_interpreted_type": "PTV",
            "roi_display_color": "0\\0\\255",
            "pipeline_data": _margin_data("CTV"),
        })
        s.refresh_from_db()
        self.assertEqual(s.pipeline, original_pipeline,
                         "editing must refresh the same pipeline, not create a new one")
        self.assertEqual(list(s.pipeline.rules.all())[0].output_color, "0\\0\\255")

    def test_edit_rejects_bad_reference_and_keeps_prior_state(self):
        self._post(self.add_url, {
            "template_id": str(self.template.pk),
            "roi_label": "PTV_final",
            "rt_roi_interpreted_type": "PTV",
            "roi_display_color": "255\\0\\0",
            "pipeline_data": _margin_data("CTV"),
        })
        s = AdditionalStructures.objects.get(
            autosegmentation_template=self.template, roi_label="PTV_final")
        before_pipeline_rules = s.pipeline.rules.count()

        self._post(self.edit_url, {
            "structure_id": str(s.pk),
            "template_id": str(self.template.pk),
            "roi_label": "PTV_final",
            "roi_display_color": "255\\0\\0",
            "pipeline_data": _margin_data("Ghost"),
        })
        s.refresh_from_db()
        self.assertEqual(s.pipeline.rules.count(), before_pipeline_rules)
        self.assertEqual(list(s.pipeline.rules.all())[0].name, "PTV_final")
