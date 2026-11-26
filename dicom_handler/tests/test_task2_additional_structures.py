"""Integration test: task2 generates additional structures via the RBS engine.

Exercises the real ``_add_additional_structures_to_rtstruct`` on a synthetic
series + RTSTRUCT: an empty ROI is added directly, and a margin->crop chain is
generated with only the FINAL ROI exported (intermediates stay in memory).
"""

import os
import shutil
import tempfile

import numpy as np
import pydicom
from django.test import TestCase

from dicom_handler.models import AdditionalStructures, AutosegmentationTemplate
from dicom_handler.import_services.task2_reidentify_rtstruct import (
    _add_additional_structures_to_rtstruct,
)
from rule_based_segmentation.tests.helpers import (
    create_dicom_models,
    create_synthetic_ct_series,
    create_synthetic_rtstruct_multi,
)


class Task2RbsGenerationTests(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="task2_rbs_")
        self.series_uid = "1.2.3.4.5.6.7.8.9"
        self.study_uid = "1.2.3.4.5.6.7.8.10"

        self.ct_files = create_synthetic_ct_series(
            self.temp_dir, num_slices=10, rows=64, cols=64,
            series_uid=self.series_uid, study_uid=self.study_uid,
        )
        self.series = create_dicom_models(
            self.ct_files, self.series_uid, self.study_uid
        )
        self.series.series_root_path = self.temp_dir
        self.series.save(update_fields=["series_root_path"])

        # Two existing structures: a small target (CTV) inside a larger body.
        shp = (10, 64, 64)
        ctv = np.zeros(shp, dtype=bool)
        ctv[3:7, 28:36, 28:36] = True
        body = np.zeros(shp, dtype=bool)
        body[0:10, 10:54, 10:54] = True
        self.rtstruct_path = os.path.join(self.temp_dir, "reid_rtstruct.dcm")
        create_synthetic_rtstruct_multi(
            self.rtstruct_path, self.ct_files, {"CTV": ctv, "Body": body}
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _roi_names(self, ds):
        return {str(r.ROIName) for r in ds.StructureSetROISequence}

    def test_empty_and_generated_added_intermediates_not_exported(self):
        template = AutosegmentationTemplate.objects.create(template_name="t")
        # empty ROI (no generation logic)
        AdditionalStructures.objects.create(
            autosegmentation_template=template,
            roi_label="Spa",
            rt_roi_interpreted_type="OAR",
            roi_display_color="0\\255\\0",
        )
        # margin(CTV) -> crop to Body, exported as PTV_final
        AdditionalStructures.objects.create(
            autosegmentation_template=template,
            roi_label="PTV_final",
            rt_roi_interpreted_type="PTV",
            roi_display_color="255\\0\\0",
            roi_generation_logic={"operations": [
                {"type": "margin", "structures": ["CTV"],
                 "parameters": {"margin_mm": 5.0, "variant": "UNIFORM"}},
                {"type": "crop_to_boundary", "structures": ["Body"], "parameters": {}},
            ]},
        )
        self.series.matched_templates.add(template)

        ds = pydicom.dcmread(self.rtstruct_path, force=True)
        series_data = {
            "series": self.series,
            "study": self.series.study,
            "patient": self.series.study.patient,
            "instances": list(self.series.dicominstance_set.all()),
        }
        name_map = {"CTV": 1, "Body": 2}

        _add_additional_structures_to_rtstruct(ds, series_data, name_map)

        names = self._roi_names(ds)
        self.assertIn("CTV", names)
        self.assertIn("Body", names)
        self.assertIn("Spa", names)          # empty ROI added directly
        self.assertIn("PTV_final", names)     # generated final ROI
        # the intermediate of the chain must NOT be exported
        self.assertNotIn("__ptv_final_step_0", names)

        # PTV_final carries the structure's color and interpreted type.
        num = {str(r.ROIName): int(r.ROINumber) for r in ds.StructureSetROISequence}["PTV_final"]
        contour = [c for c in ds.ROIContourSequence
                   if int(c.ReferencedROINumber) == num][0]
        self.assertEqual(list(contour.ROIDisplayColor), [255, 0, 0])
        obs = [o for o in ds.RTROIObservationsSequence
               if int(o.ReferencedROINumber) == num][0]
        self.assertEqual(obs.RTROIInterpretedType, "PTV")

        # generated name registered in the map
        self.assertIn("PTV_final", name_map)

    def test_generation_does_not_leak_temp_pipeline(self):
        from rule_based_segmentation.models import SegmentationPipeline

        template = AutosegmentationTemplate.objects.create(template_name="t")
        AdditionalStructures.objects.create(
            autosegmentation_template=template,
            roi_label="PTV_final",
            rt_roi_interpreted_type="PTV",
            roi_display_color="255\\0\\0",
            roi_generation_logic={"operations": [
                {"type": "margin", "structures": ["CTV"],
                 "parameters": {"margin_mm": 5.0, "variant": "UNIFORM"}},
            ]},
        )
        self.series.matched_templates.add(template)
        before = SegmentationPipeline.objects.count()

        ds = pydicom.dcmread(self.rtstruct_path, force=True)
        series_data = {
            "series": self.series,
            "study": self.series.study,
            "patient": self.series.study.patient,
            "instances": list(self.series.dicominstance_set.all()),
        }
        _add_additional_structures_to_rtstruct(ds, series_data, {"CTV": 1, "Body": 2})

        # the temporary synthesized pipeline is cleaned up
        self.assertEqual(SegmentationPipeline.objects.count(), before)
