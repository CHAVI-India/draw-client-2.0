"""Regression tests for ProductionPipelineExecutor (the auto-segmentation path).

Covers the previously-broken variadic boolean ops (union/intersection), the
running-result chain (refinement/crop), and the feature-rich operations that
the centralized catalog now exposes to the pipeline builder.

A lightweight fake RTStruct stands in for rt-utils so the tests need no DICOM
files: ``get_roi_mask_by_name`` returns an [x, y, z] array (rt-utils
convention), which the executor transposes to [z, y, x] on load.
"""

import numpy as np
import SimpleITK as sitk
from django.test import TestCase

from dicom_handler.utils.pipeline_executor import ProductionPipelineExecutor


def _vox(mask):
    return int(np.count_nonzero(sitk.GetArrayFromImage(mask)))


def _ct_image():
    img = sitk.GetImageFromArray(np.zeros((20, 20, 20), dtype=np.int16))
    img.SetSpacing((1.0, 1.0, 1.0))
    img.SetOrigin((0.0, 0.0, 0.0))
    return img


def _fake_rtstruct(zyx_masks):
    """Build a fake rtstruct whose masks are given in [z, y, x] order."""
    stored = {name: np.transpose(m, (2, 1, 0)) for name, m in zyx_masks.items()}

    class _Fake:
        def get_roi_mask_by_name(self, name):
            return stored[name]

        def add_roi(self, mask, name, color):
            self.added[name] = mask

    fake = _Fake()
    fake.added = {}
    return fake


class ProductionPipelineExecutorTests(TestCase):
    def setUp(self):
        a = np.zeros((20, 20, 20), dtype=np.uint8)
        a[2:8, 2:8, 2:8] = 1
        b = np.zeros((20, 20, 20), dtype=np.uint8)
        b[6:14, 6:14, 6:14] = 1
        c = np.zeros((20, 20, 20), dtype=np.uint8)
        c[14:18, 14:18, 14:18] = 1
        self.masks = {"A": a, "B": b, "C": c}
        self.ct = _ct_image()

    def _run(self, operations, masks=None):
        executor = ProductionPipelineExecutor(
            _fake_rtstruct(masks if masks is not None else self.masks), self.ct
        )
        return executor.execute_pipeline({"operations": operations}), executor

    # ---- Fixed variadic booleans ----------------------------------------
    def test_union_two(self):
        result, _ = self._run([{"type": "union", "structures": ["A", "B"]}])
        self.assertEqual(_vox(result), 720)

    def test_union_three(self):
        result, _ = self._run([{"type": "union", "structures": ["A", "B", "C"]}])
        self.assertEqual(_vox(result), 784)

    def test_intersection_two(self):
        result, _ = self._run([{"type": "intersection", "structures": ["A", "B"]}])
        self.assertEqual(_vox(result), 8)

    def test_subtract(self):
        result, _ = self._run([{"type": "subtract", "structures": ["A", "B"]}])
        self.assertEqual(_vox(result), 208)

    # ---- Margin (legacy expand/contract) --------------------------------
    def test_expand(self):
        result, _ = self._run(
            [{"type": "expand", "structures": ["A"], "parameters": {"margin_mm": 2.0}}]
        )
        self.assertGreater(_vox(result), 216)

    def test_contract(self):
        result, _ = self._run(
            [{"type": "contract", "structures": ["A"], "parameters": {"margin_mm": 2.0}}]
        )
        self.assertLess(_vox(result), 216)

    def test_anisotropic_margin(self):
        result, _ = self._run(
            [
                {
                    "type": "margin",
                    "structures": ["A"],
                    "parameters": {
                        "variant": "ANISOTROPIC",
                        "margin_x_mm": 2.0,
                        "margin_y_mm": 2.0,
                        "margin_z_mm": 2.0,
                    },
                }
            ]
        )
        self.assertGreater(_vox(result), 216)

    # ---- Running-result chain ------------------------------------------
    def test_expand_then_smooth_uses_running_result(self):
        result, _ = self._run(
            [
                {"type": "expand", "structures": ["A"], "parameters": {"margin_mm": 2.0}},
                {"type": "smooth", "parameters": {"smoothing_mm": 1.0, "iterations": 1}},
            ]
        )
        self.assertIsNotNone(result)
        self.assertGreater(_vox(result), 0)

    def test_crop_uses_running_result(self):
        result, _ = self._run(
            [
                {"type": "expand", "structures": ["A"], "parameters": {"margin_mm": 2.0}},
                {"type": "crop_to_boundary", "structures": ["B"]},
            ]
        )
        # (A expanded) ∩ B
        self.assertIsNotNone(result)
        self.assertGreater(_vox(result), 0)

    # ---- Feature-rich operations (now shared) ---------------------------
    def test_ring(self):
        result, _ = self._run(
            [
                {
                    "type": "ring",
                    "structures": ["A"],
                    "parameters": {"variant": "UNIFORM", "thickness_mm": 2.0, "kernel_type": "ball"},
                }
            ]
        )
        self.assertGreater(_vox(result), 0)

    def test_avoid_margin(self):
        result, _ = self._run(
            [
                {
                    "type": "avoid_margin",
                    "structures": ["A", "B"],
                    "parameters": {"variant": "UNIFORM", "margin_mm": 2.0, "kernel_type": "ball"},
                }
            ]
        )
        self.assertGreater(_vox(result), 0)

    # ---- Errors ---------------------------------------------------------
    def test_missing_structure_returns_none(self):
        result, _ = self._run([{"type": "expand", "structures": ["MISSING"]}])
        self.assertIsNone(result)
