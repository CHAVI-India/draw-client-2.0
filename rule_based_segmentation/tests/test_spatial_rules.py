"""Engine tests for the spatial rule operations (RING, OVERLAP, EXPAND_SUBTRACT, AVOID_MARGIN)."""

import os
import shutil
import tempfile

import numpy as np
import SimpleITK as sitk
from django.test import TestCase

from dicom_handler.utils.structure_generation.operations import (
    apply_uniform_margin,
)

from ..utils.engine import SegmentationEngine
from .helpers import (
    create_dicom_models,
    create_pipeline_with_rules,
    create_synthetic_ct_series,
    create_synthetic_rtstruct_multi,
)


class SpatialRulesBase(TestCase):
    """Shared fixture: 10-slice 64x64 CT (1.0 mm spacing) with two overlapping boxes."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="rbs_spatial_")
        self.series_uid = "1.2.3.4.5.6.7.8.9"
        self.study_uid = "1.2.3.4.5.6.7.8.10"
        self.ct_files = create_synthetic_ct_series(
            self.temp_dir,
            num_slices=10,
            rows=64,
            cols=64,
            spacing=(1.0, 1.0, 1.0),
            series_uid=self.series_uid,
            study_uid=self.study_uid,
        )
        self.series = create_dicom_models(self.ct_files, self.series_uid, self.study_uid)

        # Box = z[3:7], y[28:36], x[28:36]  (4x8x8 = 256 voxels)
        self.box = np.zeros((10, 64, 64), dtype=bool)
        self.box[3:7, 28:36, 28:36] = True
        # Box2 = z[3:7], y[32:40], x[32:40] (4x8x8 = 256 voxels)
        self.box2 = np.zeros((10, 64, 64), dtype=bool)
        self.box2[3:7, 32:40, 32:40] = True

        self.rtstruct_path = os.path.join(self.temp_dir, "test_rtstruct.dcm")
        create_synthetic_rtstruct_multi(
            self.rtstruct_path,
            self.ct_files,
            {"Box": self.box, "Box2": self.box2},
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _engine(self):
        return SegmentationEngine(self.rtstruct_path, self.series_uid)

    def _run_single_rule(self, rules_data):
        pipeline = create_pipeline_with_rules(rules_data=rules_data)
        engine = self._engine()
        engine.run_rule(pipeline.rules.first())
        return engine

    @staticmethod
    def _volume(mask):
        return int(np.sum(sitk.GetArrayFromImage(mask)))


class RingRuleTests(SpatialRulesBase):
    def test_ring_is_a_shell_excluding_source(self):
        engine = self._run_single_rule(
            [
                {
                    "rule_type": "RING",
                    "name": "Ring",
                    "config": {
                        "variant": "UNIFORM",
                        "source": "Box",
                        "thickness_mm": 1.0,
                        "kernel_type": "ball",
                    },
                }
            ]
        )
        ring = engine.available_masks["Ring"]
        box = engine.available_masks["Box"]
        # The ring must exclude the source structure entirely.
        self.assertEqual(self._volume(sitk.And(ring, box)), 0)
        # The ring is non-empty.
        self.assertGreater(self._volume(ring), 0)
        # Ring volume == expanded(Box) - Box.
        expanded = apply_uniform_margin(box, 1.0, "ball")
        expected = self._volume(expanded) - self._volume(box)
        self.assertEqual(self._volume(ring), expected)

    def test_ring_anisotropic_variant(self):
        engine = self._run_single_rule(
            [
                {
                    "rule_type": "RING",
                    "name": "RingA",
                    "config": {
                        "variant": "ANISOTROPIC",
                        "source": "Box",
                        "thickness_x_mm": 1.0,
                        "thickness_y_mm": 1.0,
                        "thickness_z_mm": 0.0,
                    },
                }
            ]
        )
        ring = engine.available_masks["RingA"]
        box = engine.available_masks["Box"]
        self.assertEqual(self._volume(sitk.And(ring, box)), 0)
        # z-thickness 0 means the shell only grows in x/y; it must still be non-empty.
        self.assertGreater(self._volume(ring), 0)
