"""task2 runs an FK pipeline (RBS) to generate an additional structure.

Covers: FK pipeline is the source of truth; the final rule's pinned name/color/type
reach the exported ROI; intermediates are not exported; and task2 produces exactly
one RTStruct (the inline runner must not spawn a second structure-set file).
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
from rule_based_segmentation.models import (
    CropBoundary,
    CropRuleConfig,
    MarginRuleConfig,
    PipelineRule,
    SegmentationPipeline,
)
from rule_based_segmentation.tests.helpers import (
    create_dicom_models,
    create_synthetic_ct_series,
    create_synthetic_rtstruct_multi,
)


class Task2PipelineFkTests(TestCase):
    def setUp(self):
        base = tempfile.mkdtemp(prefix="task2fk_")
        self.series_dir = os.path.join(base, "series")
        os.makedirs(self.series_dir)
        self.parent_dir = base  # where task2 writes its temp rtstruct

        self.series_uid = "1.2.9.1.1.1.1"
        self.study_uid = "1.2.9.1.1.1.2"
        self.ct_files = create_synthetic_ct_series(
            self.series_dir, num_slices=10, rows=64, cols=64,
            series_uid=self.series_uid, study_uid=self.study_uid,
        )
        self.series = create_dicom_models(
            self.ct_files, self.series_uid, self.study_uid
        )
        self.series.series_root_path = self.series_dir
        self.series.save(update_fields=["series_root_path"])

        shp = (10, 64, 64)
        ctv = np.zeros(shp, dtype=bool)
        ctv[3:7, 28:36, 28:36] = True
        body = np.zeros(shp, dtype=bool)
        body[:, 10:54, 10:54] = True
        self.rtstruct_path = os.path.join(self.series_dir, "reid_rtstruct.dcm")
        create_synthetic_rtstruct_multi(
            self.rtstruct_path, self.ct_files, {"CTV": ctv, "Body": body}
        )
        self.template = AutosegmentationTemplate.objects.create(template_name="t")

    def tearDown(self):
        shutil.rmtree(self.parent_dir, ignore_errors=True)

    def _build_margin_crop_pipeline(self):
        pipeline = SegmentationPipeline.objects.create(
            name="PTV_final generation", is_public=False, is_active=False,
        )
        m = PipelineRule.objects.create(
            pipeline=pipeline, order=1, rule_type="MARGIN",
            name="__ptv_final_step_0", output_action="INTERMEDIATE",
        )
        MarginRuleConfig.objects.create(
            pipeline_rule=m, source="CTV", margin_mm=5.0, variant="UNIFORM",
        )
        c = PipelineRule.objects.create(
            pipeline=pipeline, order=2, rule_type="CROP", name="PTV_final",
            output_action="CREATE_NEW", output_color="255\\0\\0",
            output_roi_type="PTV",
        )
        cc = CropRuleConfig.objects.create(pipeline_rule=c, source="__ptv_final_step_0")
        CropBoundary.objects.create(crop_rule=cc, boundary_roi="Body", order=1)
        return pipeline

    def _run(self, ds):
        series_data = {
            "series": self.series,
            "study": self.series.study,
            "patient": self.series.study.patient,
            "instances": list(self.series.dicominstance_set.all()),
        }
        name_map = {"CTV": 1, "Body": 2}
        _add_additional_structures_to_rtstruct(ds, series_data, name_map)
        return name_map

    def test_fk_pipeline_generates_roi_with_pinned_color_type(self):
        pipeline = self._build_margin_crop_pipeline()
        AdditionalStructures.objects.create(
            autosegmentation_template=self.template,
            roi_label="PTV_final",
            rt_roi_interpreted_type="PTV",
            roi_display_color="255\\0\\0",
            pipeline=pipeline,
        )
        self.series.matched_templates.add(self.template)

        ds = pydicom.dcmread(self.rtstruct_path, force=True)
        name_map = self._run(ds)

        names = {str(r.ROIName) for r in ds.StructureSetROISequence}
        self.assertIn("PTV_final", names)
        self.assertNotIn("__ptv_final_step_0", names)  # no intermediate leak
        self.assertIn("PTV_final", name_map)

        num = {str(r.ROIName): int(r.ROINumber) for r in ds.StructureSetROISequence}["PTV_final"]
        contour = [c for c in ds.ROIContourSequence if int(c.ReferencedROINumber) == num][0]
        self.assertEqual(list(contour.ROIDisplayColor), [255, 0, 0])
        obs = [o for o in ds.RTROIObservationsSequence if int(o.ReferencedROINumber) == num][0]
        self.assertEqual(obs.RTROIInterpretedType, "PTV")

    def test_produces_exactly_one_rtstruct(self):
        self._build_margin_crop_pipeline()
        pipeline = SegmentationPipeline.objects.filter(name="PTV_final generation").first()
        AdditionalStructures.objects.create(
            autosegmentation_template=self.template,
            roi_label="PTV_final", rt_roi_interpreted_type="PTV",
            roi_display_color="255\\0\\0", pipeline=pipeline,
        )
        self.series.matched_templates.add(self.template)

        dcm_before = {f for f in os.listdir(self.series_dir) if f.endswith(".dcm")}
        ds = pydicom.dcmread(self.rtstruct_path, force=True)
        self._run(ds)

        # the temp rtstruct (written to the parent dir) is cleaned up
        self.assertFalse(
            os.path.exists(os.path.join(self.parent_dir, "temp_rtstruct.dcm")),
            "task2 must not leave a second RTStruct file behind",
        )
        # no new structure-set file appears in the series dir
        dcm_after = {f for f in os.listdir(self.series_dir) if f.endswith(".dcm")}
        self.assertEqual(dcm_before, dcm_after, "no new RTStruct file in the series dir")

    def test_empty_pipeline_is_an_empty_roi(self):
        # A pipeline with zero rules => "no step" => plain empty ROI.
        empty_pipeline = SegmentationPipeline.objects.create(
            name="empty gen", is_public=False, is_active=False,
        )
        AdditionalStructures.objects.create(
            autosegmentation_template=self.template,
            roi_label="Spa", rt_roi_interpreted_type="OAR",
            roi_display_color="0\\255\\0", pipeline=empty_pipeline,
        )
        self.series.matched_templates.add(self.template)

        ds = pydicom.dcmread(self.rtstruct_path, force=True)
        self._run(ds)
        names = {str(r.ROIName) for r in ds.StructureSetROISequence}
        self.assertIn("Spa", names)
