"""Per-ROI color and interpreted-type fidelity (client feedback: "always yellow").

Uses the real engine on a synthetic RTStruct so the assertions read the actual
DICOM ROIDisplayColor / RTROIInterpretedType that would reach a TPS like Eclipse.
"""

import os
import shutil
import tempfile

import numpy as np
from django.test import TestCase

from ..models import MarginRuleConfig, PipelineRule, SegmentationPipeline
from ..utils.engine import SegmentationEngine
from .helpers import (
    create_dicom_models,
    create_synthetic_ct_series,
    create_synthetic_rtstruct,
)


def _roi_by_number(ds, roi_number):
    for roi in ds.StructureSetROISequence:
        if int(roi.ROINumber) == roi_number:
            return roi
    raise AssertionError(f"ROI number {roi_number} not found")


class RoiColorTypeFidelityTests(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="rbs_fidelity_")
        self.series_uid = "1.2.3.4.5.6.7.8.9"
        self.study_uid = "1.2.3.4.5.6.7.8.10"
        self.ct_files = create_synthetic_ct_series(
            self.temp_dir, num_slices=10, rows=64, cols=64,
            series_uid=self.series_uid, study_uid=self.study_uid,
        )
        create_dicom_models(self.ct_files, self.series_uid, self.study_uid)
        self.mask = np.zeros((10, 64, 64), dtype=bool)
        self.mask[3:7, 28:36, 28:36] = True
        # Source structure "CTV" with a known, non-yellow color.
        self.rtstruct_path = os.path.join(self.temp_dir, "rt.dcm")
        create_synthetic_rtstruct(
            self.rtstruct_path, self.ct_files,
            roi_name="CTV", mask_array=self.mask, color=[0, 255, 0],
        )
        # Give the source a PTV interpreted type (the synthetic helper leaves it unset).
        import pydicom
        ds = pydicom.dcmread(self.rtstruct_path, force=True)
        for obs in ds.RTROIObservationsSequence:
            if obs.ReferencedROINumber == _roi_by_number(ds, 1).ROINumber:
                obs.RTROIInterpretedType = "PTV"
        ds.save_as(self.rtstruct_path, write_like_original=False)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _new_rule(self, output_color, output_roi_type):
        pipeline = SegmentationPipeline.objects.create(name="p")
        rule = PipelineRule.objects.create(
            pipeline=pipeline, order=1, rule_type="MARGIN", name="CTV_m",
            output_action="CREATE_NEW", output_color=output_color,
            output_roi_type=output_roi_type,
        )
        MarginRuleConfig.objects.create(
            pipeline_rule=rule, variant="UNIFORM", source="CTV",
            margin_mm=2.0, kernel_type="ball",
        )
        return rule

    def test_explicit_color_and_type_reach_dicom(self):
        engine = SegmentationEngine(self.rtstruct_path, self.series_uid)
        rule = self._new_rule("0\\0\\255", "OAR")
        engine.run_rule(rule)
        ds = engine.rtstruct.ds
        names = [str(r.ROIName) for r in ds.StructureSetROISequence]
        self.assertIn("CTV_m", names)
        # find its ROI number
        num = _roi_by_number(ds, 2).ROINumber
        contour = [c for c in ds.ROIContourSequence
                   if int(c.ReferencedROINumber) == num][0]
        self.assertEqual(list(contour.ROIDisplayColor), [0, 0, 255])
        obs = [o for o in ds.RTROIObservationsSequence
               if int(o.ReferencedROINumber) == num][0]
        self.assertEqual(obs.RTROIInterpretedType, "OAR")

    def test_unset_color_inherits_from_source(self):
        engine = SegmentationEngine(self.rtstruct_path, self.series_uid)
        rule = self._new_rule(None, None)  # no color, no type -> inherit from CTV
        engine.run_rule(rule)
        ds = engine.rtstruct.ds
        num = _roi_by_number(ds, 2).ROINumber
        contour = [c for c in ds.ROIContourSequence
                   if int(c.ReferencedROINumber) == num][0]
        # Inherited the source's green color, not the yellow default.
        self.assertEqual(list(contour.ROIDisplayColor), [0, 255, 0])
        obs = [o for o in ds.RTROIObservationsSequence
               if int(o.ReferencedROINumber) == num][0]
        # Inherited the source's PTV type.
        self.assertEqual(obs.RTROIInterpretedType, "PTV")
