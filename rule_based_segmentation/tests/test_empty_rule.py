"""A2: EMPTY rule execution produces a zero-voxel ROI."""

import os
import shutil
import tempfile

import numpy as np
import SimpleITK as sitk
from django.test import TestCase

from ..models import PipelineRule, SegmentationPipeline
from ..utils.engine import SegmentationEngine
from ..utils.inline_runner import InlineSegmentationRunner
from ..utils.rtstruct_io import load_rtstruct_and_image
from .helpers import (
    create_dicom_models,
    create_synthetic_ct_series,
    create_synthetic_rtstruct,
)


class EmptyRuleTests(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="rbs_empty_")
        self.series_uid = "1.2.3.4.5.6.7.8.9"
        self.study_uid = "1.2.3.4.5.6.7.8.10"
        self.ct_files = create_synthetic_ct_series(
            self.temp_dir, num_slices=10, rows=64, cols=64,
            series_uid=self.series_uid, study_uid=self.study_uid,
        )
        create_dicom_models(self.ct_files, self.series_uid, self.study_uid)
        self.mask = np.zeros((10, 64, 64), dtype=bool)
        self.mask[3:7, 28:36, 28:36] = True
        self.rtstruct_path = os.path.join(self.temp_dir, "rt.dcm")
        create_synthetic_rtstruct(
            self.rtstruct_path, self.ct_files, roi_name="CTV",
            mask_array=self.mask, color=[255, 0, 0],
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _empty_rule(self):
        p = SegmentationPipeline.objects.create(name="p")
        return PipelineRule.objects.create(
            pipeline=p, order=1, rule_type="EMPTY", name="EmptyROI",
            output_action="CREATE_NEW", output_color="255\\255\\255",
            output_roi_type="ORGAN",
        )

    def test_empty_mask_is_zero_voxel(self):
        rtstruct, image, _ = load_rtstruct_and_image(self.rtstruct_path, self.series_uid)
        engine = SegmentationEngine.from_rtstruct(rtstruct, image)
        mask = engine._evaluate_rule(self._empty_rule())
        arr = sitk.GetArrayFromImage(mask)
        self.assertEqual(int(arr.sum()), 0, "EMPTY mask must have zero voxels")
        self.assertEqual(mask.GetSize(), image.GetSize(), "EMPTY keeps reference geometry")

    def test_empty_rule_exported_to_rtstruct(self):
        rtstruct, image, _ = load_rtstruct_and_image(self.rtstruct_path, self.series_uid)
        engine = SegmentationEngine.from_rtstruct(rtstruct, image)
        out = engine.run_rule(self._empty_rule())
        self.assertEqual(out, "EmptyROI")
        self.assertIn("EmptyROI", engine.rtstruct.get_roi_names())
        self.assertEqual(
            int(sitk.GetArrayFromImage(engine.available_masks["EmptyROI"]).sum()), 0
        )

    def test_empty_rule_via_inline_runner(self):
        rtstruct, image, _ = load_rtstruct_and_image(self.rtstruct_path, self.series_uid)
        runner = InlineSegmentationRunner(rtstruct, image)
        summary = runner.run_rules([self._empty_rule()])
        self.assertIn("EmptyROI", summary["created"])
        self.assertIn("EmptyROI", rtstruct.get_roi_names())

    def test_empty_rule_persisted_without_config(self):
        from django.contrib.auth import get_user_model
        from ..utils.pipeline_persistence import (
            referenced_structure_names,
            save_pipeline_from_dict,
        )

        user = get_user_model().objects.create(username="u_empty_persist")
        data = {
            "name": "tpl — additional structures",
            "structures": ["CTV"],
            "rules": [
                {"rule_type": "EMPTY", "name": "EmptyROI",
                 "output_action": "CREATE_NEW", "config": {}, "tempId": "t1"},
            ],
        }
        p = save_pipeline_from_dict(data, user)
        rule = p.rules.first()
        self.assertEqual(rule.rule_type, "EMPTY")
        # EMPTY references no input structure and needs no config object.
        self.assertEqual(
            referenced_structure_names([data["rules"][0]]), set()
        )
