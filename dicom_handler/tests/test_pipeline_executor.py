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
import tempfile
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from rt_utils import RTStructBuilder

from dicom_handler.models import AutosegmentationTemplate
from dicom_handler.utils.pipeline_executor import ProductionPipelineExecutor
from dicom_handler.utils.structure_generation import OPERATIONS
from rule_based_segmentation.tests.helpers import create_synthetic_ct_series


def _vox(mask):
    return int(np.count_nonzero(sitk.GetArrayFromImage(mask)))


def _ct_image():
    img = sitk.GetImageFromArray(np.zeros((20, 20, 20), dtype=np.int16))
    img.SetSpacing((1.0, 1.0, 1.0))
    img.SetOrigin((0.0, 0.0, 0.0))
    return img


def _fake_rtstruct(zyx_masks):
    """Build a fake rtstruct whose masks are given in [z, y, x] order.

    rt-utils returns masks in (y, x, z) order, so store the transpose of the
    (z, y, x) masks accordingly (the executor's load_structure transposes back
    with (2, 0, 1)).
    """
    stored = {name: np.transpose(m, (1, 2, 0)) for name, m in zyx_masks.items()}

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


class StructureOperationsCatalogAPITests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="opcat", password="x")
        self.client = Client()
        self.client.login(username="opcat", password="x")

    def test_returns_full_catalog(self):
        r = self.client.get(reverse("dicom_handler:structure_operations_catalog"))
        self.assertEqual(r.status_code, 200)
        ops = r.json()["operations"]
        self.assertEqual(len(ops), len(OPERATIONS))
        ids = {o["id"] for o in ops}
        for expected in ("margin", "ring", "avoid_margin", "expand_subtract", "intensity_range"):
            self.assertIn(expected, ids)
        margin = next(o for o in ops if o["id"] == "margin")
        self.assertTrue(any(r0["name"] == "source" for r0 in margin["structure_roles"]))
        self.assertTrue(any(p["name"] == "margin_l_mm" for p in margin["parameters"]))

    def test_requires_login(self):
        anon = Client()
        r = anon.get(reverse("dicom_handler:structure_operations_catalog"))
        self.assertIn(r.status_code, (302, 401, 403))


class PipelineBuilderViewCatalogTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(username="pbsu", password="x")
        self.client = Client()
        self.client.force_login(self.user)
        self.template = AutosegmentationTemplate.objects.create(
            template_name="Test Template", template_description="d"
        )

    def test_new_page_embeds_catalog(self):
        r = self.client.get(reverse("dicom_handler:pipeline_builder_new", args=[self.template.id]))
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        # The catalog is embedded for the JS builder and lists the shared ops.
        self.assertIn("operationCatalog", html)
        for op_id in ("margin", "ring", "avoid_margin", "expand_subtract", "intensity_range"):
            self.assertIn('"id": "{}"'.format(op_id), html)

    def test_edit_page_embeds_catalog(self):
        from dicom_handler.models import AdditionalStructures
        structure = AdditionalStructures.objects.create(
            autosegmentation_template=self.template, roi_label="X"
        )
        r = self.client.get(reverse("dicom_handler:pipeline_builder_edit", args=[structure.id]))
        self.assertEqual(r.status_code, 200)
        self.assertIn("operationCatalog", r.content.decode())

    def test_structure_type_dropdown_matches_rbs(self):
        """The Structure Type dropdown must offer the same ROI types as rule-based
        extraction (PipelineRule.ROI_TYPE_CHOICES), not a shorter hardcoded list."""
        from rule_based_segmentation.models import PipelineRule

        r = self.client.get(reverse("dicom_handler:pipeline_builder_new", args=[self.template.id]))
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        for value, _label in PipelineRule.ROI_TYPE_CHOICES:
            self.assertIn(f'<option value="{value}"', html, f"missing ROI type {value}")
        # Types that were absent from the old hardcoded 8-value list:
        for value in ("TREATED_VOLUME", "OAR", "MARKER", "BRACHY_CHANNEL", "DOSE_MEASUREMENT"):
            self.assertIn(f'<option value="{value}"', html)


class ExecutorOrientationTests(TestCase):
    """Real rt-utils round-trip: load_structure and add_result_to_rtstruct must
    preserve orientation on a non-square, in-plane-asymmetric series."""

    Z, Y, X = 4, 8, 10

    def _ct_image(self):
        img = sitk.GetImageFromArray(np.zeros((self.Z, self.Y, self.X), dtype=np.int16))
        img.SetSpacing((1.0, 1.0, 1.0))
        img.SetOrigin((0.0, 0.0, 0.0))
        return img

    def _asymmetric_mask(self):
        m = np.zeros((self.Z, self.Y, self.X), dtype=np.uint8)
        m[1, 1, 8] = 1
        m[1, 2, 8] = 1
        m[2, 7, 1] = 1
        return m

    def _new_rtstruct(self, tmp):
        create_synthetic_ct_series(tmp, num_slices=self.Z, rows=self.Y, cols=self.X)
        return RTStructBuilder.create_new(tmp)

    def test_load_structure_preserves_orientation(self):
        tmp = tempfile.mkdtemp(prefix="exec_orient_")
        rt = self._new_rtstruct(tmp)
        m = self._asymmetric_mask()
        rt.add_roi(mask=m.transpose(1, 2, 0).astype(bool), name="A", color=[255, 0, 0])

        ex = ProductionPipelineExecutor(rt, self._ct_image())
        arr = sitk.GetArrayFromImage(ex.load_structure("A")).astype(bool)
        self.assertTrue(
            np.array_equal(arr, m.astype(bool)),
            "load_structure must return the exact (Z,Y,X) mask, not a mirror",
        )

    def test_add_result_to_rtstruct_roundtrip(self):
        tmp = tempfile.mkdtemp(prefix="exec_orient_")
        rt = self._new_rtstruct(tmp)
        src = self._ct_image()
        m = self._asymmetric_mask()

        ex = ProductionPipelineExecutor(rt, src)
        # Prime current_result with a known mask (bypass the pipeline).
        mask_sitk = sitk.GetImageFromArray(m)
        mask_sitk.CopyInformation(src)
        ex.current_result = mask_sitk

        self.assertTrue(ex.add_result_to_rtstruct("Out", [0, 255, 0]))

        ex2 = ProductionPipelineExecutor(rt, src)
        arr = sitk.GetArrayFromImage(ex2.load_structure("Out")).astype(bool)
        self.assertTrue(
            np.array_equal(arr, m.astype(bool)),
            "add_result_to_rtstruct -> load_structure must be an exact round-trip",
        )
