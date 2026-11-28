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

from dicom_handler.models import AutosegmentationTemplate
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
        from django.contrib.auth import get_user_model
        from rule_based_segmentation.utils.pipeline_persistence import (
            save_pipeline_from_dict,
        )

        user = get_user_model().objects.create(username="u_task2_t1")
        template = AutosegmentationTemplate.objects.create(template_name="t")
        pipeline = save_pipeline_from_dict({
            "name": "t — additional structures",
            "structures": ["CTV", "Body"],
            "rules": [
                {"rule_type": "EMPTY", "name": "Spa", "output_action": "CREATE_NEW",
                 "config": {}, "tempId": "e1"},
                {"rule_type": "MARGIN", "name": "__PTV_final_step_0",
                 "output_action": "INTERMEDIATE",
                 "config": {"source": "CTV", "margin_l_mm": 5.0}, "tempId": "m1"},
                {"rule_type": "CROP", "name": "__PTV_final_step_1",
                 "output_action": "INTERMEDIATE",
                 "config": {"source": "__PTV_final_step_0", "boundaries": ["Body"]},
                 "tempId": "c1"},
                {"rule_type": "CLEANUP", "name": "PTV_final",
                 "output_action": "CREATE_NEW", "output_roi_type": "PTV",
                 "output_color": "255\\0\\0",
                 "config": {"source": "__PTV_final_step_1",
                            "operation": "KEEP_LARGEST_COMPONENT"}, "tempId": "k1"},
            ],
        }, user)
        template.additional_structures_pipeline = pipeline
        template.save()
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
        self.assertIn("Spa", names)          # empty ROI (EMPTY rule)
        self.assertIn("PTV_final", names)     # generated final ROI
        # the intermediates of the chain must NOT be exported
        self.assertNotIn("__PTV_final_step_0", names)
        self.assertNotIn("__PTV_final_step_1", names)

        # PTV_final carries the rule's color and interpreted type.
        num = {str(r.ROIName): int(r.ROINumber) for r in ds.StructureSetROISequence}["PTV_final"]
        contour = [c for c in ds.ROIContourSequence
                   if int(c.ReferencedROINumber) == num][0]
        self.assertEqual(list(contour.ROIDisplayColor), [255, 0, 0])
        obs = [o for o in ds.RTROIObservationsSequence
               if int(o.ReferencedROINumber) == num][0]
        self.assertEqual(obs.RTROIInterpretedType, "PTV")

        # generated name registered in the map
        self.assertIn("PTV_final", name_map)

    def test_no_transient_pipeline_created(self):
        from django.contrib.auth import get_user_model
        from rule_based_segmentation.models import SegmentationPipeline
        from rule_based_segmentation.utils.pipeline_persistence import (
            save_pipeline_from_dict,
        )

        user = get_user_model().objects.create(username="u_task2_t2")
        template = AutosegmentationTemplate.objects.create(template_name="t")
        pipeline = save_pipeline_from_dict({
            "name": "t — additional structures",
            "structures": ["CTV"],
            "rules": [
                {"rule_type": "MARGIN", "name": "PTV", "output_action": "CREATE_NEW",
                 "config": {"source": "CTV", "margin_l_mm": 5.0}, "tempId": "p1"},
            ],
        }, user)
        template.additional_structures_pipeline = pipeline
        template.save()
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

        # task2 runs the existing template pipeline; it creates no new pipeline
        self.assertEqual(SegmentationPipeline.objects.count(), before)

    def test_template_pipeline_is_used(self):
        """A4: task2 runs the template's additional-structures pipeline."""
        from django.contrib.auth import get_user_model
        from rule_based_segmentation.utils.pipeline_persistence import (
            save_pipeline_from_dict,
        )

        template = AutosegmentationTemplate.objects.create(template_name="t")
        user = get_user_model().objects.create(username="u_task2")
        pipeline = save_pipeline_from_dict({
            "name": "tpl — additional structures",
            "structures": ["CTV"],
            "rules": [
                {"rule_type": "MARGIN", "name": "PTV", "output_action": "CREATE_NEW",
                 "config": {"source": "CTV", "margin_l_mm": 5.0}, "tempId": "p1"},
            ],
        }, user)
        template.additional_structures_pipeline = pipeline
        template.save()
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
        self.assertIn("PTV", names)  # created via the template pipeline
        self.assertIn("PTV", name_map)

class Task2RbsReidentificationOrderTests(TestCase):
    """Regression: additional structures must survive the task2 re-identification pass.

    An RTSTRUCT returned by the external segmentation server still carries
    *de-identified* Contour Image Sequence references. ``_reidentify_dicom_tags``
    used to run the additional-structures pipeline BEFORE the UID-replacement
    walks, so ``RTStructBuilder.create_from()`` rejected the RTStruct ("references
    image(s) that are not contained in input series data") and silently dropped
    every additional structure. The pipeline must run AFTER the re-mapping.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="task2_reid_order_")
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

        # Give every instance a de-identified UID, as the segmentation-server
        # export does, and remember the original -> de-identified mapping.
        self.deid_map = {}
        for i, inst in enumerate(self.series.dicominstance_set.all()):
            deid = f"1.2.3.99.0.{i + 1}"
            inst.deidentified_sop_instance_uid = deid
            inst.save(update_fields=["deidentified_sop_instance_uid"])
            self.deid_map[inst.sop_instance_uid] = deid

        shp = (10, 64, 64)
        ctv = np.zeros(shp, dtype=bool)
        ctv[3:7, 28:36, 28:36] = True
        self.rtstruct_path = os.path.join(self.temp_dir, "reid_rtstruct.dcm")
        create_synthetic_rtstruct_multi(
            self.rtstruct_path, self.ct_files, {"CTV": ctv}
        )

        # Simulate the RTSTRUCT coming back from the segmentation server:
        # Contour Image Sequence references in the Referenced Frame of
        # Reference still carry the de-identified SOP UIDs.
        ds = pydicom.dcmread(self.rtstruct_path, force=True)
        for ref in ds.ReferencedFrameOfReferenceSequence:
            study_seq = ref.get("RTReferencedStudySequence")
            if not study_seq:
                continue
            for s_ref in study_seq:
                series_seq = s_ref.get("RTReferencedSeriesSequence")
                if not series_seq:
                    continue
                for ss_ref in series_seq:
                    for ci in ss_ref.get("ContourImageSequence", []):
                        orig = str(ci.ReferencedSOPInstanceUID)
                        if orig in self.deid_map:
                            ci.ReferencedSOPInstanceUID = self.deid_map[orig]
        ds.save_as(self.rtstruct_path, write_like_original=False)

        # Template whose additional-structures pipeline creates one empty ROI.
        from django.contrib.auth import get_user_model
        from rule_based_segmentation.utils.pipeline_persistence import (
            save_pipeline_from_dict,
        )

        user = get_user_model().objects.create(username="u_task2_reid_order")
        template = AutosegmentationTemplate.objects.create(
            template_name="t_reid_order"
        )
        pipeline = save_pipeline_from_dict({
            "name": "t_reid_order — additional structures",
            "structures": ["CTV"],
            "rules": [
                {"rule_type": "EMPTY", "name": "Extra_PTV",
                 "output_action": "CREATE_NEW", "config": {}, "tempId": "e1"},
            ],
        }, user)
        template.additional_structures_pipeline = pipeline
        template.save()
        self.series.matched_templates.add(template)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_additional_structures_survive_reidentification(self):
        from dicom_handler.import_services.task2_reidentify_rtstruct import (
            _reidentify_dicom_tags,
        )

        series_data = {
            "series": self.series,
            "study": self.series.study,
            "patient": self.series.study.patient,
            "instances": list(self.series.dicominstance_set.all()),
        }
        ds = _reidentify_dicom_tags(self.rtstruct_path, series_data)
        self.assertIsNotNone(ds, "re-identification failed entirely")

        names = {str(r.ROIName) for r in ds.StructureSetROISequence}
        self.assertIn("CTV", names)
        # The CREATE_NEW rule from the template's additional-structures
        # pipeline must have been applied even though the input RTStruct
        # still carried de-identified contour references.
        self.assertIn("Extra_PTV", names)

        # The UID re-mapping must have restored the original SOP UIDs.
        for ref in ds.ReferencedFrameOfReferenceSequence:
            for s_ref in ref.get("RTReferencedStudySequence", []):
                for ss_ref in s_ref.get("RTReferencedSeriesSequence", []):
                    for ci in ss_ref.get("ContourImageSequence", []):
                        self.assertIn(
                            str(ci.ReferencedSOPInstanceUID),
                            self.deid_map,
                            "contour reference was not re-identified to an original SOP UID",
                        )

    def test_sibling_series_in_same_directory_does_not_break_generation(self):
        """Production incident: ``series_root_path`` held more than one series.

        rt-utils walks the given directory in full, so a sibling series with
        overlapping slice positions made
        ``RTStructBuilder.create_from(dicom_series_path=series_root_path)``
        raise "more than one image at the same slice position" and drop every
        additional structure. The builder must be built from this series' own
        instances only.
        """
        from dicom_handler.import_services.task2_reidentify_rtstruct import (
            _reidentify_dicom_tags,
        )

        # A second series in the same datastore folder, same geometry, so a
        # directory-wide scan would see two images per slice position.
        sibling_dir = os.path.join(self.temp_dir, "sibling_series")
        os.makedirs(sibling_dir)
        create_synthetic_ct_series(
            sibling_dir, num_slices=10, rows=64, cols=64,
            series_uid="1.2.3.4.5.6.7.8.21", study_uid=self.study_uid,
        )

        # Sanity check: the on-disk scan this test used to trigger really
        # would have failed on duplicate positions.
        from rt_utils import image_helper

        with self.assertRaises(Exception):
            image_helper.load_sorted_image_series(self.temp_dir)

        series_data = {
            "series": self.series,
            "study": self.series.study,
            "patient": self.series.study.patient,
            "instances": list(self.series.dicominstance_set.all()),
        }
        ds = _reidentify_dicom_tags(self.rtstruct_path, series_data)
        self.assertIsNotNone(ds, "re-identification failed entirely")

        names = {str(r.ROIName) for r in ds.StructureSetROISequence}
        self.assertIn("Extra_PTV", names)
