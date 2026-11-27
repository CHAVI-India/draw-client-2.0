"""End-to-end acceptance: a matched template's additional-structures pipeline is
executed by the RBS engine through the real task2 entry point, exporting only the
FINAL (CREATE_NEW) ROIs.

Covers an empty ROI, a margin->crop->cleanup chain (with in-memory intermediates),
a ring, an expand_subtract, and a contract — asserting colors/types are honored
and no intermediate (``__...step_...``) structure leaks into the RTStruct.
"""

import os
import shutil
import tempfile

import numpy as np
import pydicom
from django.contrib.auth import get_user_model
from django.test import TestCase

from dicom_handler.models import AutosegmentationTemplate
from dicom_handler.import_services.task2_reidentify_rtstruct import (
    _add_additional_structures_to_rtstruct,
)
from rule_based_segmentation.utils.pipeline_persistence import (
    save_pipeline_from_dict,
)
from rule_based_segmentation.tests.helpers import (
    create_dicom_models,
    create_synthetic_ct_series,
    create_synthetic_rtstruct_multi,
)


class EndToEndTemplateGenerationTests(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="rbs_e2e_")
        self.series_uid = "1.2.8.1.1.1.1"
        self.study_uid = "1.2.8.1.1.1.2"
        self.ct_files = create_synthetic_ct_series(
            self.temp_dir, num_slices=12, rows=64, cols=64,
            series_uid=self.series_uid, study_uid=self.study_uid,
        )
        self.series = create_dicom_models(
            self.ct_files, self.series_uid, self.study_uid
        )
        self.series.series_root_path = self.temp_dir
        self.series.save(update_fields=["series_root_path"])

        shp = (12, 64, 64)
        ctv = np.zeros(shp, dtype=bool)
        ctv[2:10, 20:44, 20:44] = True
        body = np.zeros(shp, dtype=bool)
        body[:, 8:56, 8:56] = True
        oar = np.zeros(shp, dtype=bool)
        oar[4:8, 10:18, 10:18] = True  # overlaps part of CTV
        self.rtstruct_path = os.path.join(self.temp_dir, "rtstruct.dcm")
        create_synthetic_rtstruct_multi(
            self.rtstruct_path, self.ct_files,
            {"CTV": ctv, "Body": body, "OAR": oar},
        )

        self.template = AutosegmentationTemplate.objects.create(template_name="t")
        self.user = get_user_model().objects.create(username="e2e_user")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _set_pipeline(self, rules):
        pipeline = save_pipeline_from_dict(
            {"name": "t — additional structures", "structures": ["CTV", "Body", "OAR"],
             "rules": rules},
            self.user,
        )
        self.template.additional_structures_pipeline = pipeline
        self.template.save()
        self.series.matched_templates.add(self.template)

    def _run(self):
        ds = pydicom.dcmread(self.rtstruct_path, force=True)
        series_data = {
            "series": self.series,
            "study": self.series.study,
            "patient": self.series.study.patient,
            "instances": list(self.series.dicominstance_set.all()),
        }
        name_map = {n: i + 1 for i, n in enumerate(["CTV", "Body", "OAR"])}
        _add_additional_structures_to_rtstruct(ds, series_data, name_map)
        return ds, name_map

    def _names(self, ds):
        return {str(r.ROIName) for r in ds.StructureSetROISequence}

    def test_only_final_rois_exported_with_correct_types(self):
        self._set_pipeline([
            # empty ROI (EMPTY rule)
            {"rule_type": "EMPTY", "name": "Spa", "output_action": "CREATE_NEW",
             "output_roi_type": "OAR", "output_color": "0\\255\\0",
             "config": {}, "tempId": "r1"},
            # margin -> crop -> cleanup (smooth): 2 intermediates + 1 final
            {"rule_type": "MARGIN", "name": "__PTV_final_step_0",
             "output_action": "INTERMEDIATE",
             "config": {"source": "CTV", "margin_mm": 4.0, "variant": "UNIFORM"},
             "tempId": "r2"},
            {"rule_type": "CROP", "name": "__PTV_final_step_1",
             "output_action": "INTERMEDIATE",
             "config": {"source": "__PTV_final_step_0", "boundaries": ["Body"]},
             "tempId": "r3"},
            {"rule_type": "CLEANUP", "name": "PTV_final",
             "output_action": "CREATE_NEW", "output_roi_type": "PTV",
             "output_color": "255\\0\\0",
             "config": {"source": "__PTV_final_step_1",
                        "operation": "SMOOTH_STRUCTURE",
                        "smoothing_mm": 1.0, "iterations": 1},
             "tempId": "r4"},
            # ring (single op -> final directly)
            {"rule_type": "RING", "name": "Ring1", "output_action": "CREATE_NEW",
             "output_roi_type": "OTHER", "output_color": "0\\0\\255",
             "config": {"source": "CTV", "thickness_mm": 2.0}, "tempId": "r5"},
            # expand_subtract (single op)
            {"rule_type": "EXPAND_SUBTRACT", "name": "ES1",
             "output_action": "CREATE_NEW", "output_roi_type": "OTHER",
             "output_color": "255\\0\\255",
             "config": {"source": "CTV", "subtract": "OAR", "distance_mm": 5.0},
             "tempId": "r6"},
            # contract (negative margin)
            {"rule_type": "MARGIN", "name": "CtvShrink",
             "output_action": "CREATE_NEW", "output_roi_type": "GTV",
             "output_color": "255\\255\\0",
             "config": {"source": "CTV", "margin_mm": -1.0, "variant": "UNIFORM"},
             "tempId": "r7"},
        ])

        ds, name_map = self._run()
        names = self._names(ds)

        # all final ROIs present
        for final in ["Spa", "PTV_final", "Ring1", "ES1", "CtvShrink"]:
            self.assertIn(final, names)
            self.assertIn(final, name_map)
        # originals untouched
        for orig in ["CTV", "Body", "OAR"]:
            self.assertIn(orig, names)

        # NO intermediate structures may leak
        for n in names:
            self.assertNotIn("step_", n, f"intermediate leaked: {n}")

        # types honored
        type_by_num = {
            int(o.ReferencedROINumber): str(o.RTROIInterpretedType)
            for o in ds.RTROIObservationsSequence
        }
        num_by_name = {str(r.ROIName): int(r.ROINumber) for r in ds.StructureSetROISequence}
        self.assertEqual(type_by_num[num_by_name["PTV_final"]], "PTV")
        self.assertEqual(type_by_num[num_by_name["CtvShrink"]], "GTV")

        # colors honored
        color_by_num = {
            int(c.ReferencedROINumber): list(c.ROIDisplayColor)
            for c in ds.ROIContourSequence
        }
        self.assertEqual(color_by_num[num_by_name["PTV_final"]], [255, 0, 0])
        self.assertEqual(color_by_num[num_by_name["Ring1"]], [0, 0, 255])

    def test_generation_result_is_nonempty_for_ring_and_expand_subtract(self):
        self._set_pipeline([
            {"rule_type": "RING", "name": "Ring1", "output_action": "CREATE_NEW",
             "output_roi_type": "OTHER",
             "config": {"source": "CTV", "thickness_mm": 2.0}, "tempId": "r1"},
            {"rule_type": "EXPAND_SUBTRACT", "name": "ES1",
             "output_action": "CREATE_NEW", "output_roi_type": "OTHER",
             "config": {"source": "CTV", "subtract": "OAR", "distance_mm": 5.0},
             "tempId": "r2"},
        ])

        ds, _ = self._run()
        num_by_name = {str(r.ROIName): int(r.ROINumber) for r in ds.StructureSetROISequence}
        for name in ["Ring1", "ES1"]:
            self.assertIn(name, num_by_name, f"{name} missing from structure set")

        # Rebuild a file-backed builder and confirm the generated ROIs have real
        # volume (not an empty contour).
        from rt_utils import RTStructBuilder
        saved = os.path.join(self.temp_dir, "check_rtstruct.dcm")
        ds.save_as(saved, write_like_original=False)
        builder = RTStructBuilder.create_from(
            dicom_series_path=self.temp_dir, rt_struct_path=saved,
        )
        for name in ["Ring1", "ES1"]:
            mask = builder.get_roi_mask_by_name(name)
            self.assertIsNotNone(mask, f"{name} has no mask")
            self.assertGreater(int(np.sum(mask.astype(bool))), 0, f"{name} should be non-empty")
