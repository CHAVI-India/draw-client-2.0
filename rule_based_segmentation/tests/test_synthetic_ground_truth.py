"""Ground-truth verification of the pipeline's *actual* ROI output, on disk.

Builds a synthetic RTStruct of known, axis-aligned boxes on the existing
de-identified planning CT (see :mod:`synthetic_fixture`), then runs real
pipelines through the engine and reads the **generated DICOM RTStruct file**
back, asserting each produced ROI's voxel set EXACTLY equals an independently
computed ground truth.

This is the strongest possible check: not "a ROI was created" but "the ROI that
was written to the output DICOM contains exactly the voxels it should" -- for
nested/grouped booleans (the original concern), margins, crops and intensity
segmentation.
"""

import os
import shutil
import tempfile
from types import SimpleNamespace
from unittest import mock

import numpy as np
from django.contrib.auth import get_user_model
from django.test import TestCase

from dicom_handler.utils.structure_generation import load_ct_series_as_sitk_image
from rule_based_segmentation.models import SegmentationJob
from rule_based_segmentation.utils import rtstruct_registry
from rule_based_segmentation.utils.engine import SegmentationEngine
from rule_based_segmentation.utils.pipeline_persistence import save_pipeline_from_dict
from rule_based_segmentation.utils.dicom_image_importer import (
    import_uploaded_image_series,
)

from .helpers import make_in_memory_file
from .synthetic_fixture import (
    KNOWN_BOXES,
    all_box_arrays,
    boolean_gt,
    box_array,
    build_synthetic_rtstruct,
    expected_crop,
    expected_intensity,
    expected_margin,
    read_roi_mask_zyx,
)
from .test_pipeline_e2e_physics import _find_dataset


def _roi(name):
    return {"name": name}


def _op(operation, *operands):
    return {"operation": operation, "operands": list(operands)}


class SyntheticGroundTruthTests(TestCase):
    """Run real pipelines over the synthetic known-shape RTStruct and verify the
    written DICOM ROIs voxel-for-voxel."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = get_user_model().objects.create_user(
            username="synphys", password="x", email="syn@x.y"
        )

        src_rtstruct, cls.series_uid, ct_files = _find_dataset()
        cls.src_rtstruct = src_rtstruct

        cls.work_dir = tempfile.mkdtemp(prefix="rbs_syn_")
        cls.series_dir = os.path.join(cls.work_dir, "ct_series")
        os.makedirs(cls.series_dir, exist_ok=True)
        patcher = mock.patch(
            "rule_based_segmentation.utils.dicom_image_importer"
            "._get_series_target_directory",
            return_value=cls.series_dir,
        )
        patcher.start()
        cls.addClassCleanup(patcher.stop)

        uploads = [
            make_in_memory_file(os.path.basename(p), open(p, "rb").read())
            for p in ct_files
        ]
        cls.series = import_uploaded_image_series(
            uploads, expected_series_instance_uid=cls.series_uid
        )

        from dicom_handler.models import DICOMInstance

        instances = list(DICOMInstance.objects.filter(series_instance_uid=cls.series))
        cls.ct_image = load_ct_series_as_sitk_image(
            {"instances": instances, "series": cls.series}
        )
        cls.spacing = cls.ct_image.GetSpacing()  # (x, y, z)
        cls.ct_dir = cls.series_dir  # holds the CT files for rt_utils

        cls.shape_zyx = cls.ct_image.GetSize()[::-1]
        cls.boxes = all_box_arrays(cls.shape_zyx)
        cls.ct_hu = np.asarray(__import__("SimpleITK").GetArrayFromImage(cls.ct_image))

        cls.syn_rt_path = os.path.join(cls.work_dir, "synthetic_boxes.dcm")
        build_synthetic_rtstruct(
            cls.ct_dir, src_rtstruct, cls.syn_rt_path, cls.ct_image
        )

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work_dir, ignore_errors=True)
        super().tearDownClass()

    def _run_rules(self, rules):
        """Build a pipeline, run it through the engine, return the output path."""
        spec = {
            "name": "syn_" + os.urandom(4).hex(),
            "is_public": False,
            "rules": rules,
        }
        pipeline = save_pipeline_from_dict(spec, self.user)
        out_path = os.path.join(self.work_dir, f"out_{os.urandom(4).hex()}.dcm")
        engine = SegmentationEngine(self.syn_rt_path, self.series_uid)
        engine.run_pipeline(pipeline, output_path=out_path)
        return out_path

    def _assert_exact(self, out_path, name, expected):
        got = read_roi_mask_zyx(out_path, self.ct_dir, name)
        exp = np.asarray(expected).astype(bool)
        mismatch = int(np.logical_xor(got, exp).sum())
        self.assertEqual(
            mismatch,
            0,
            f"{name}: {mismatch} voxels differ from ground truth "
            f"(got {int(got.sum())}, expected {int(exp.sum())})",
        )

    # ------------------------------------------------------------------
    # 0. The fixture itself is correct (boxes round-trip exactly).
    # ------------------------------------------------------------------
    def test_fixture_boxes_round_trip_exactly(self):
        for name in KNOWN_BOXES:
            with self.subTest(box=name):
                got = read_roi_mask_zyx(self.syn_rt_path, self.ct_dir, name)
                self.assertTrue(
                    np.array_equal(got, self.boxes[name]),
                    f"{name}: written box does not match its definition",
                )
        # and only the known boxes are present
        from rt_utils import RTStructBuilder

        rb = RTStructBuilder.create_from(
            dicom_series_path=self.ct_dir, rt_struct_path=self.syn_rt_path
        )
        self.assertEqual(set(rb.get_roi_names()), set(KNOWN_BOXES))

    # ------------------------------------------------------------------
    # 1. Nested / grouped boolean expressions, verified on the written file.
    # ------------------------------------------------------------------
    def test_boolean_nested_and_grouped_match_ground_truth(self):
        A, B, C, D = (self.boxes[k] for k in ("BoxA", "BoxB", "BoxC", "BoxD"))
        rules = [
            {"rule_type": "BOOLEAN", "name": "U_AB", "output_roi_type": "OAR",
             "config": _op("UNION", _roi("BoxA"), _roi("BoxB"))},
            {"rule_type": "BOOLEAN", "name": "I_AB", "output_roi_type": "OAR",
             "config": _op("INTERSECTION", _roi("BoxA"), _roi("BoxB"))},
            {"rule_type": "BOOLEAN", "name": "S_AD", "output_roi_type": "OAR",
             "config": _op("SUBTRACT", _roi("BoxA"), _roi("BoxD"))},
            {"rule_type": "BOOLEAN", "name": "X_AB", "output_roi_type": "OAR",
             "config": _op("XOR", _roi("BoxA"), _roi("BoxB"))},
            {"rule_type": "BOOLEAN", "name": "U_ABC", "output_roi_type": "OAR",
             "config": _op("UNION", _roi("BoxA"), _roi("BoxB"), _roi("BoxC"))},
            # Nested group: A minus (B union C)
            {"rule_type": "BOOLEAN", "name": "S_A_BC", "output_roi_type": "OAR",
             "config": _op("SUBTRACT", _roi("BoxA"), _op("UNION", _roi("BoxB"), _roi("BoxC")))},
            # Nested group: (A union D) intersect B  == A intersect B
            {"rule_type": "BOOLEAN", "name": "I_AD_B", "output_roi_type": "OAR",
             "config": _op("INTERSECTION", _op("UNION", _roi("BoxA"), _roi("BoxD")), _roi("BoxB"))},
            # Nested group: B minus (A union C)
            {"rule_type": "BOOLEAN", "name": "S_B_AC", "output_roi_type": "OAR",
             "config": _op("SUBTRACT", _roi("BoxB"), _op("UNION", _roi("BoxA"), _roi("BoxC")))},
            # XOR with a group: A xor (B intersect C)  == A  (B and C disjoint)
            {"rule_type": "BOOLEAN", "name": "X_A_BC", "output_roi_type": "OAR",
             "config": _op("XOR", _roi("BoxA"), _op("INTERSECTION", _roi("BoxB"), _roi("BoxC")))},
            # Two-level nesting: (A union B) minus ((C union D) intersect B)
            {"rule_type": "BOOLEAN", "name": "DEEP", "output_roi_type": "OAR",
             "config": _op("SUBTRACT",
                           _op("UNION", _roi("BoxA"), _roi("BoxB")),
                           _op("INTERSECTION",
                               _op("UNION", _roi("BoxC"), _roi("BoxD")), _roi("BoxB")))},
        ]
        out_path = self._run_rules(rules)
        expected = {
            "U_AB": boolean_gt("UNION", A, B),
            "I_AB": boolean_gt("INTERSECTION", A, B),
            "S_AD": boolean_gt("SUBTRACT", A, D),
            "X_AB": boolean_gt("XOR", A, B),
            "U_ABC": boolean_gt("UNION", A, B, C),
            "S_A_BC": boolean_gt("SUBTRACT", A, boolean_gt("UNION", B, C)),
            "I_AD_B": boolean_gt("INTERSECTION", boolean_gt("UNION", A, D), B),
            "S_B_AC": boolean_gt("SUBTRACT", B, boolean_gt("UNION", A, C)),
            "X_A_BC": boolean_gt("XOR", A, boolean_gt("INTERSECTION", B, C)),
            "DEEP": boolean_gt("SUBTRACT",
                               boolean_gt("UNION", A, B),
                               boolean_gt("INTERSECTION",
                                          boolean_gt("UNION", C, D), B)),
        }
        for name, exp in expected.items():
            with self.subTest(rule=name):
                self._assert_exact(out_path, name, exp)

    # ------------------------------------------------------------------
    # 2. Margins (uniform expansion + erosion) -- exact, on disk.
    # ------------------------------------------------------------------
    def test_margin_matches_ground_truth(self):
        A = self.boxes["BoxA"]
        rules = [
            {"rule_type": "MARGIN", "name": "MAG_A_5", "output_roi_type": "PTV",
             "config": {"variant": "UNIFORM", "source": "BoxA",
                        "margin_mm": 5.0, "kernel_type": "ball"}},
            {"rule_type": "MARGIN", "name": "MAG_A_m3", "output_roi_type": "PTV",
             "config": {"variant": "UNIFORM", "source": "BoxA",
                        "margin_mm": -3.0, "kernel_type": "ball"}},
        ]
        out_path = self._run_rules(rules)
        self._assert_exact(out_path, "MAG_A_5",
                           expected_margin(A, 5.0, self.spacing))
        self._assert_exact(out_path, "MAG_A_m3",
                           expected_margin(A, -3.0, self.spacing))

    # ------------------------------------------------------------------
    # 3. Crop-to-boundary -- exact, on disk (single + multiple boundaries).
    # ------------------------------------------------------------------
    def test_crop_matches_ground_truth(self):
        A, B, C = self.boxes["BoxA"], self.boxes["BoxB"], self.boxes["BoxC"]
        rules = [
            {"rule_type": "CROP", "name": "CROP_B_A", "output_roi_type": "OAR",
             "config": {"source": "BoxB", "boundaries": ["BoxA"]}},
            {"rule_type": "CROP", "name": "CROP_A_BC", "output_roi_type": "OAR",
             "config": {"source": "BoxA", "boundaries": ["BoxB", "BoxC"]}},
        ]
        out_path = self._run_rules(rules)
        self._assert_exact(out_path, "CROP_B_A", expected_crop(B, A))
        self._assert_exact(out_path, "CROP_A_BC", expected_crop(A, B, C))

    # ------------------------------------------------------------------
    # 4. Intensity-range segmentation -- exact, on disk.
    # ------------------------------------------------------------------
    def test_intensity_matches_ground_truth(self):
        A, C = self.boxes["BoxA"], self.boxes["BoxC"]
        rules = [
            {"rule_type": "INTENSITY", "name": "INT_IMG", "output_roi_type": "OAR",
             "config": {"seed_type": "IMAGE",
                        "ranges": [{"min": -200, "max": 400}]}},
            {"rule_type": "INTENSITY", "name": "INT_SEED", "output_roi_type": "GTV",
             "config": {"seed_type": "STRUCTURE", "seed_roi": "BoxA",
                        "ranges": [{"min": 0, "max": 300}]}},
            {"rule_type": "INTENSITY", "name": "INT_BOUND", "output_roi_type": "OAR",
             "config": {"seed_type": "IMAGE", "boundary_roi": "BoxC",
                        "ranges": [{"min": 100, "max": 200}]}},
        ]
        out_path = self._run_rules(rules)
        self._assert_exact(out_path, "INT_IMG",
                           expected_intensity(self.ct_hu, [(-200, 400)]))
        self._assert_exact(out_path, "INT_SEED",
                           expected_intensity(self.ct_hu, [(0, 300)], seed=A))
        self._assert_exact(out_path, "INT_BOUND",
                           expected_intensity(self.ct_hu, [(100, 200)], boundary=C))
