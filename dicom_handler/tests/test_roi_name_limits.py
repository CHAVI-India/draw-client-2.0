"""Regression tests: ROI name fields must support the 54-char Eclipse
Clinical-Goal naming convention (was capped at 16)."""

from django.core.exceptions import ValidationError
from django.test import TestCase

from dicom_handler.models import (
    AdditionalStructures,
    AutosegmentationStructure,
    AutosegmentationTemplate,
    StructureProperties,
)


class RoiNameLimitTests(TestCase):
    def _structure(self):
        return AutosegmentationStructure.objects.create(name="S")

    def test_structure_properties_roi_label_accepts_54(self):
        sp = StructureProperties(
            autosegmentation_structure=self._structure(), roi_label="L" * 54
        )
        sp.full_clean()  # must not raise
        self.assertEqual(len(sp.roi_label), 54)

    def test_structure_properties_roi_label_rejects_55(self):
        sp = StructureProperties(
            autosegmentation_structure=self._structure(), roi_label="L" * 55
        )
        with self.assertRaises(ValidationError):
            sp.full_clean()

    def test_additional_structures_roi_label_accepts_54(self):
        template = AutosegmentationTemplate.objects.create(template_name="t")
        extra = AdditionalStructures(
            autosegmentation_template=template, roi_label="L" * 54
        )
        extra.full_clean()  # must not raise
        self.assertEqual(len(extra.roi_label), 54)

    def test_additional_structures_roi_label_rejects_55(self):
        template = AutosegmentationTemplate.objects.create(template_name="t")
        extra = AdditionalStructures(
            autosegmentation_template=template, roi_label="L" * 55
        )
        with self.assertRaises(ValidationError):
            extra.full_clean()
