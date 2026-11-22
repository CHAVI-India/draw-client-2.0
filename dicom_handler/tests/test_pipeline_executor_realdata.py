"""Real-data tests for the additional-structures pipeline (ProductionPipelineExecutor).

The executor's unit tests in ``test_pipeline_executor.py`` use a fake rtstruct
and small symmetric volumes, so they cannot exercise the real rt-utils mask I/O
or the operations on realistic anatomy. This module runs the executor against
the committed de-identified DICOM dataset (CT + ARIA RTSTRUCT under
``rule_based_segmentation/tests/dicom_data``), applying *different* operations
to *different* real structures and checking the results are spatially sensible
and correctly shaped.

Note: the committed CT is 512x512 (square in-plane), so this validates the
full load -> operate -> write-back flow on real data but is not the tool that
catches an in-plane (X/Y) transpose; that is covered by the non-square
synthetic tests in ``rule_based_segmentation/tests/test_orientation.py``.
"""

import glob
import os
import shutil
import tempfile
import unittest

import numpy as np
import pydicom
import SimpleITK as sitk
from django.test import SimpleTestCase

from dicom_handler.utils.pipeline_executor import ProductionPipelineExecutor
from rule_based_segmentation.utils.rtstruct_registry import extract_referenced_series_uid

_DATA_DIR = os.path.normpath(
    os.path.join(
        os.path.dirname(__file__), "..", "..",
        "rule_based_segmentation", "tests", "dicom_data",
    )
)


def _find_rtstruct_and_ct(data_dir):
    """Return (rtstruct_path, referenced_ct_uid, [ct_file_paths])."""
    rt_path = None
    ct_uid = None
    for root, _dirs, files in os.walk(data_dir):
        for name in files:
            if name.endswith(".bin"):
                continue
            path = os.path.join(root, name)
            try:
                ds = pydicom.dcmread(path, stop_before_pixels=True, force=True)
            except Exception:
                continue
            if str(getattr(ds, "Modality", "")).upper() == "RTSTRUCT":
                rt_path = path
                ct_uid = extract_referenced_series_uid(ds)
    if not rt_path:
        raise RuntimeError(f"No RTSTRUCT found under {data_dir}")

    ct_files = []
    for root, _dirs, files in os.walk(data_dir):
        for name in files:
            if name.endswith(".bin"):
                continue
            path = os.path.join(root, name)
            try:
                ds = pydicom.dcmread(path, stop_before_pixels=True, force=True)
            except Exception:
                continue
            if (str(getattr(ds, "Modality", "")).upper() == "CT"
                    and str(getattr(ds, "SeriesInstanceUID", "")) == ct_uid):
                ct_files.append(path)
    if not ct_files:
        raise RuntimeError(f"No CT instances for series {ct_uid}")
    return rt_path, ct_uid, sorted(ct_files)


def _load_ct_sitk(ct_dir):
    """Load a single-series CT directory as a SimpleITK image (ordered by
    InstanceNumber)."""

    def _inst(p):
        ds = pydicom.dcmread(p, stop_before_pixels=True, force=True)
        return int(getattr(ds, "InstanceNumber", 0))

    ordered = sorted(glob.glob(os.path.join(ct_dir, "*")), key=_inst)
    reader = sitk.ImageSeriesReader()
    reader.SetFileNames(ordered)
    return reader.Execute()


@unittest.skipUnless(os.path.isdir(_DATA_DIR), "real DICOM test data not present")
class AdditionalStructuresRealDataTests(SimpleTestCase):
    """Run the additional-structures executor on the committed real dataset."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.rt_path, cls.ct_uid, cls.ct_files = _find_rtstruct_and_ct(_DATA_DIR)
        cls.work = tempfile.mkdtemp(prefix="addstruct_real_")
        cls.ct_dir = os.path.join(cls.work, "ct")
        os.makedirs(cls.ct_dir, exist_ok=True)
        for p in cls.ct_files:
            shutil.copy2(p, cls.ct_dir)
        cls.ct_image = _load_ct_sitk(cls.ct_dir)
        # Expected (Z, Y, X) shape of any mask on this dataset.
        cls.zyx_shape = tuple(cls.ct_image.GetSize()[::-1])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)
        super().tearDownClass()

    def _executor(self):
        from rt_utils import RTStructBuilder

        rtstruct = RTStructBuilder.create_from(
            dicom_series_path=self.ct_dir, rt_struct_path=self.rt_path
        )
        return ProductionPipelineExecutor(rtstruct, self.ct_image)

    def _vox(self, mask):
        arr = mask if isinstance(mask, np.ndarray) else sitk.GetArrayFromImage(mask)
        return int(np.count_nonzero(arr))

    def _arr(self, mask):
        arr = mask if isinstance(mask, np.ndarray) else sitk.GetArrayFromImage(mask)
        return arr.astype(bool)

    def _subset(self, a, b):
        """True if mask `a` is a spatial subset of mask `b`."""
        return bool(np.array_equal(np.logical_and(a, b), a))

    def _assert_shaped(self, mask):
        self.assertEqual(self._arr(mask).shape, self.zyx_shape)

    # ---- Different operations on different real structures ----------------

    def test_union_of_two_lungs(self):
        ex = self._executor()
        result = ex.execute_pipeline(
            {"operations": [
                {"type": "union", "structures": ["LUNG_LT", "LUNG_RT"]},
            ]}
        )
        self.assertIsNotNone(result)
        self._assert_shaped(result)
        union = self._arr(result)
        lt = self._arr(ex.load_structure("LUNG_LT"))
        rt = self._arr(ex.load_structure("LUNG_RT"))
        self.assertTrue(self._subset(lt, union), "union must contain LUNG_LT")
        self.assertTrue(self._subset(rt, union), "union must contain LUNG_RT")
        self.assertGreaterEqual(self._vox(result), max(self._vox(lt), self._vox(rt)))

    def test_intersection_btv_within_body(self):
        ex = self._executor()
        result = ex.execute_pipeline(
            {"operations": [
                {"type": "intersection", "structures": ["BTV", "BODY"]},
            ]}
        )
        self.assertIsNotNone(result)
        self._assert_shaped(result)
        inter = self._arr(result)
        body = self._arr(ex.load_structure("BODY"))
        self.assertTrue(self._subset(inter, body), "intersection must lie in BODY")
        self.assertGreater(self._vox(result), 0, "BTV is inside BODY, intersection non-empty")

    def test_subtract_heart_from_body(self):
        ex = self._executor()
        result = ex.execute_pipeline(
            {"operations": [
                {"type": "subtract", "structures": ["BODY", "HEART"]},
            ]}
        )
        self.assertIsNotNone(result)
        self._assert_shaped(result)
        sub = self._arr(result)
        body = self._arr(ex.load_structure("BODY"))
        self.assertTrue(self._subset(sub, body), "body-minus-heart lies in BODY")
        self.assertLess(self._vox(result), self._vox(body), "subtract removed the heart")
        self.assertGreater(self._vox(result), 0)

    def test_margin_grows_lad(self):
        ex = self._executor()
        result = ex.execute_pipeline(
            {"operations": [
                {"type": "margin", "structures": ["LAD"],
                 "parameters": {"variant": "UNIFORM", "margin_mm": 5.0, "kernel_type": "ball"}},
            ]}
        )
        self.assertIsNotNone(result)
        self._assert_shaped(result)
        grown = self._arr(result)
        lad = self._arr(ex.load_structure("LAD"))
        self.assertTrue(self._subset(lad, grown), "5mm margin must contain LAD")
        self.assertGreater(self._vox(result), self._vox(lad), "margin must grow LAD")

    def test_grow_then_crop_to_body(self):
        ex = self._executor()
        result = ex.execute_pipeline(
            {"operations": [
                {"type": "margin", "structures": ["BTV"],
                 "parameters": {"variant": "UNIFORM", "margin_mm": 5.0, "kernel_type": "ball"}},
                {"type": "crop_to_boundary", "structures": ["BODY"]},
            ]}
        )
        self.assertIsNotNone(result)
        self._assert_shaped(result)
        cropped = self._arr(result)
        body = self._arr(ex.load_structure("BODY"))
        self.assertTrue(self._subset(cropped, body), "cropped target lies in BODY")
        self.assertGreater(self._vox(result), 0)

    # ---- Write-back (add_result_to_rtstruct) on real data -----------------

    def test_add_result_to_rtstruct_roundtrip(self):
        """load_structure -> operate -> add_result_to_rtstruct -> save ->
        reload -> load_structure. add_result_to_rtstruct only mutates the
        in-memory RTStructBuilder, so we must save and re-read to verify the
        contour write-back (and both transposes) round-trip."""
        from rt_utils import RTStructBuilder

        ex = self._executor()
        # Prime the running result with the real LAD mask.
        ex.current_result = ex.load_structure("LAD")
        self.assertTrue(ex.add_result_to_rtstruct("LAD_TEST_OUT", [0, 255, 0]))

        out_path = os.path.join(self.work, "out_addstruct.dcm")
        ex.rtstruct.save(out_path)

        # Re-load from the saved file through a fresh executor.
        rt2 = RTStructBuilder.create_from(
            dicom_series_path=self.ct_dir, rt_struct_path=out_path
        )
        self.assertIn("LAD_TEST_OUT", rt2.get_roi_names())
        ex2 = ProductionPipelineExecutor(rt2, self.ct_image)
        back = ex2.load_structure("LAD_TEST_OUT")
        self._assert_shaped(back)
        self.assertGreater(self._vox(back), 0)
