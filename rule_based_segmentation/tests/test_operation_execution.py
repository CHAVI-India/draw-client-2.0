"""Tests for the shared structure-operation catalog and execution dispatcher.

These exercise :func:`dicom_handler.utils.structure_generation.execute_operation`
directly on synthetic masks — the same low-level layer both the auto-segmentation
pipeline executor and the rule-based segmentation engine route through.

Geometry (1.0 mm spacing, 20^3 volume):
  A = z[2:8],  y[2:8],  x[2:8]    -> 216 voxels
  B = z[6:14], y[6:14], x[6:14]   -> 512 voxels, overlaps A in 8 voxels
  C = z[14:18],y[14:18],x[14:18]  -> 64 voxels, disjoint from A and B
"""

import numpy as np
import SimpleITK as sitk
from django.test import TestCase

from dicom_handler.utils.structure_generation import (
    OPERATIONS,
    OperationExecutionError,
    execute_operation,
    get_operation,
    resolve_operation_id,
    supported_operation_ids,
    to_frontend_catalog,
)


def _image(array):
    img = sitk.GetImageFromArray(array.astype(np.uint8))
    img.SetSpacing((1.0, 1.0, 1.0))
    img.SetOrigin((0.0, 0.0, 0.0))
    return img


def _vox(mask):
    return int(np.count_nonzero(sitk.GetArrayFromImage(mask)))


class OperationCatalogTests(TestCase):
    def test_every_catalog_op_has_a_handler(self):
        handlers = set(supported_operation_ids())
        self.assertEqual(set(OPERATIONS.keys()), handlers)

    def test_legacy_aliases_resolve(self):
        self.assertEqual(resolve_operation_id("expand"), "margin")
        self.assertEqual(resolve_operation_id("contract"), "margin")
        self.assertEqual(resolve_operation_id("anisotropic_margin"), "margin")
        self.assertEqual(resolve_operation_id("union"), "union")
        self.assertEqual(resolve_operation_id("margin"), "margin")

    def test_unknown_op_raises(self):
        with self.assertRaises(KeyError):
            resolve_operation_id("does_not_exist")

    def test_frontend_catalog_serializable(self):
        catalog = to_frontend_catalog()
        self.assertEqual(len(catalog), len(OPERATIONS))
        entry = catalog[0]
        for key in ("id", "name", "description", "category", "structure_roles", "parameters"):
            self.assertIn(key, entry)
        # Each operation exposes its structure roles and parameter schemas.
        margin = get_operation("margin").to_dict()
        self.assertTrue(any(r["name"] == "source" for r in margin["structure_roles"]))
        self.assertTrue(any(p["name"] == "margin_l_mm" for p in margin["parameters"]))
        self.assertTrue(any(p["name"] == "margin_h_mm" for p in margin["parameters"]))
        self.assertTrue(any(p.get("allow_negative") for p in margin["parameters"]))

    def test_catalog_category_filter(self):
        refine = to_frontend_catalog(categories=["refine"])
        self.assertTrue(all(op["category"] == "refine" for op in refine))
        self.assertIn("keep_largest", [op["id"] for op in refine])

    def test_margin_like_ops_offer_only_six_directional_params(self):
        # The old isotropic/anisotropic margin facility (variant select,
        # kernel choice, *_mm / *_x_mm / *_y_mm / *_z_mm) must NOT be offered
        # any more; every margin-like op is specified along the six
        # anatomical directions (same value in all six = uniform).
        for op_id, prefix in (
            ("margin", "margin"),
            ("ring", "thickness"),
            ("expand_subtract", "distance"),
            ("avoid_margin", "margin"),
        ):
            spec = get_operation(op_id).to_dict()
            names = {p["name"] for p in spec["parameters"]}
            with self.subTest(op=op_id):
                for k in ("l", "r", "a", "p", "h", "f"):
                    self.assertIn(f"{prefix}_{k}_mm", names)
                self.assertNotIn("variant", names)
                self.assertNotIn("kernel_type", names)
                self.assertNotIn(f"{prefix}_mm", names)
                self.assertNotIn(f"{prefix}_x_mm", names)
                self.assertNotIn(f"{prefix}_y_mm", names)
                self.assertNotIn(f"{prefix}_z_mm", names)


class SdfMarginTests(TestCase):
    """Uniform margins now use the Slicer/Eclipse-style signed-distance
    threshold (true 3D mm) instead of per-axis ceil dilations."""

    def _image(self, array, spacing=(1.0, 1.0, 1.0)):
        img = sitk.GetImageFromArray(array.astype(np.uint8))
        img.SetSpacing(spacing)
        img.SetOrigin((0.0, 0.0, 0.0))
        return img

    def _box(self, z0, z1, y0, y1, x0, x1, shape=(20, 20, 20)):
        arr = np.zeros(shape, dtype=np.uint8)
        arr[z0:z1, y0:y1, x0:x1] = 1
        return arr

    def test_grow_uniform_exact_mm_threshold_anisotropic(self):
        # 1.0 in-plane / 2.5 SI grid; box 2 slices (5 mm) thick.
        img = self._image(self._box(8, 10, 8, 12, 8, 12), spacing=(1.0, 1.0, 2.5))
        out = execute_operation(
            "margin",
            {"source": img},
            {f"margin_{k}_mm": 2.5 for k in "lraphf"},
        )
        arr = sitk.GetArrayFromImage(out)
        coords = np.argwhere(arr).reshape(-1, 3)
        self.assertEqual((coords[:, 0].min(), coords[:, 0].max()), (7, 10))  # SI: +1 slice each side
        self.assertEqual((coords[:, 2].min(), coords[:, 2].max()), (6, 13))  # in-plane: +2 voxels each side

    def test_shrink_uniform_exact_mm(self):
        img = self._image(self._box(2, 8, 2, 8, 2, 8))
        out = execute_operation(
            "margin",
            {"source": img},
            {f"margin_{k}_mm": -1.0 for k in "lraphf"},
        )
        arr = sitk.GetArrayFromImage(out)
        coords = np.argwhere(arr).reshape(-1, 3)
        # Keep voxels whose center is more than 1 mm from the outside: the
        # 4x4x4 core at [3:7] on every axis (edge diagonals excluded, true ball).
        self.assertEqual((coords[:, 0].min(), coords[:, 0].max()), (3, 6))
        self.assertEqual(int(np.count_nonzero(arr)), 4 ** 3)

    def test_sub_voxel_margin_raises_not_feasible(self):
        # 2.4 mm < 2.5 mm slice thickness: Slicer's 'not feasible at current
        # resolution' guard — fail loudly instead of a silent 0-slice margin.
        img = self._image(self._box(8, 10, 8, 12, 8, 12), spacing=(1.0, 1.0, 2.5))
        with self.assertRaises(OperationExecutionError) as ctx:
            execute_operation(
                "margin",
                {"source": img},
                {"variant": "UNIFORM", "margin_mm": 2.4, "kernel_type": "ball"},
            )
        self.assertIn("not feasible", str(ctx.exception))

    def test_mixed_directional_still_per_axis_no_feasibility_error(self):
        # L=2.0 mm on a 2.5 mm-slice grid: mixed values keep the per-axis
        # dilation semantics (each set direction gets >= 1 voxel), no error.
        # L is patient +x (identity orientation), so the +x edge grows.
        img = self._image(self._box(8, 10, 8, 12, 8, 12), spacing=(1.0, 1.0, 2.5))
        params = {f"margin_{k}_mm": 0.0 for k in "lraphf"}
        params["margin_l_mm"] = 2.0
        out = execute_operation("margin", {"source": img}, params)
        arr = sitk.GetArrayFromImage(out)
        xs = np.argwhere(arr).reshape(-1, 3)[:, 2]
        self.assertGreater(xs.max(), 11)  # +x edge grew by 2 mm
        self.assertEqual(xs.min(), 8)     # -x edge untouched

    def test_expand_subtract_uses_true_mm(self):
        src = self._image(self._box(8, 10, 8, 12, 8, 12), spacing=(1.0, 1.0, 2.5))
        sub = self._image(self._box(0, 2, 0, 2, 0, 2), spacing=(1.0, 1.0, 2.5))
        out = execute_operation(
            "expand_subtract",
            {"source": src, "subtract": sub},
            {f"distance_{k}_mm": 2.5 for k in "lraphf"},
        )
        zs = np.argwhere(sitk.GetArrayFromImage(out)).reshape(-1, 3)[:, 0]
        self.assertEqual((zs.min(), zs.max()), (7, 10))  # exactly 1 slice each side

    def test_ring_shell_true_thickness(self):
        src = self._image(self._box(8, 10, 8, 12, 8, 12), spacing=(1.0, 1.0, 2.5))
        out = execute_operation(
            "ring",
            {"source": src},
            {f"thickness_{k}_mm": 2.5 for k in "lraphf"},
        )
        arr = sitk.GetArrayFromImage(out)
        zs = np.argwhere(arr).reshape(-1, 3)[:, 0]
        self.assertEqual((zs.min(), zs.max()), (7, 10))
        self.assertEqual(int(arr[8:10, 8:12, 8:12].sum()), 0)  # core hollowed out

    def test_avoid_margin_true_mm(self):
        src = self._image(self._box(4, 14, 4, 14, 4, 14))
        avoid = self._image(self._box(8, 9, 4, 14, 4, 14))  # strip inside source
        out = execute_operation(
            "avoid_margin",
            {"source": src, "avoid": avoid},
            {f"margin_{k}_mm": 2.0 for k in "lraphf"},
        )
        arr = sitk.GetArrayFromImage(out)
        # 2 mm ring around the avoid strip on a 1 mm grid: z=6..10 cleared.
        self.assertEqual(int(arr[6:11, :, :].sum()), 0)
        self.assertGreater(int(arr[5, :, :].sum()), 0)

    def test_legacy_contract_alias_shrinks(self):
        img = self._image(self._box(2, 8, 2, 8, 2, 8))
        out = execute_operation(
            "contract",
            {"source": img},
            {"variant": "UNIFORM", "margin_mm": 1.0, "kernel_type": "ball"},
        )
        arr = sitk.GetArrayFromImage(out)
        zs = np.argwhere(arr).reshape(-1, 3)[:, 0]
        self.assertEqual((zs.min(), zs.max()), (3, 6))


class OperationExecutionTests(TestCase):
    def setUp(self):
        shape = (20, 20, 20)
        a = np.zeros(shape, dtype=np.uint8)
        a[2:8, 2:8, 2:8] = 1
        b = np.zeros(shape, dtype=np.uint8)
        b[6:14, 6:14, 6:14] = 1
        c = np.zeros(shape, dtype=np.uint8)
        c[14:18, 14:18, 14:18] = 1
        self.A, self.B, self.C = _image(a), _image(b), _image(c)
        self.a, self.b, self.c = a, b, c

    # ---- Boolean ---------------------------------------------------------
    def test_union_two(self):
        result = execute_operation("union", {"primary": self.A, "others": [self.B]}, {})
        self.assertEqual(_vox(result), 720)  # |A| + |B| - |A ∩ B|

    def test_union_three(self):
        result = execute_operation("union", {"primary": self.A, "others": [self.B, self.C]}, {})
        self.assertEqual(_vox(result), 784)  # 720 + disjoint C

    def test_intersection(self):
        result = execute_operation("intersection", {"primary": self.A, "others": [self.B]}, {})
        self.assertEqual(_vox(result), 8)

    def test_subtract_pure(self):
        result = execute_operation("subtract", {"primary": self.A, "others": [self.B]}, {})
        self.assertEqual(_vox(result), 208)  # 216 - 8

    def test_subtract_with_margin(self):
        result = execute_operation(
            "subtract", {"primary": self.A, "others": [self.B]}, {"margin_mm": 2.0}
        )
        # Subtracting then expanding the result should grow it.
        self.assertGreater(_vox(result), _vox(execute_operation(
            "subtract", {"primary": self.A, "others": [self.B]}, {}
        )))

    def test_xor(self):
        result = execute_operation("xor", {"primary": self.A, "others": [self.B]}, {})
        self.assertEqual(_vox(result), 712)  # |A △ B| = |A ∪ B| - |A ∩ B|

    # ---- Margin ----------------------------------------------------------
    def test_margin_uniform_grow(self):
        result = execute_operation(
            "margin", {"source": self.A}, {"variant": "UNIFORM", "margin_mm": 2.0, "kernel_type": "ball"}
        )
        self.assertGreater(_vox(result), _vox(self.A))

    def test_margin_uniform_shrink(self):
        result = execute_operation(
            "margin", {"source": self.A}, {"variant": "UNIFORM", "margin_mm": -2.0, "kernel_type": "ball"}
        )
        self.assertLess(_vox(result), _vox(self.A))

    def test_margin_zero_is_identity(self):
        result = execute_operation(
            "margin", {"source": self.A}, {"variant": "UNIFORM", "margin_mm": 0.0, "kernel_type": "ball"}
        )
        self.assertEqual(_vox(result), _vox(self.A))

    def test_margin_anisotropic(self):
        result = execute_operation(
            "margin",
            {"source": self.A},
            {"variant": "ANISOTROPIC", "margin_x_mm": 2.0, "margin_y_mm": 2.0, "margin_z_mm": 2.0},
        )
        self.assertGreater(_vox(result), _vox(self.A))

    def test_legacy_expand_contract(self):
        grown = execute_operation("expand", {"source": self.A}, {"margin_mm": 2.0, "kernel_type": "ball"})
        shrunken = execute_operation("contract", {"source": self.A}, {"margin_mm": 2.0, "kernel_type": "ball"})
        # Legacy expand/contract must map to a signed uniform margin.
        self.assertGreater(_vox(grown), _vox(self.A))
        self.assertLess(_vox(shrunken), _vox(self.A))

    # ---- Boundary / composite -------------------------------------------
    def test_crop_to_boundary(self):
        result = execute_operation("crop_to_boundary", {"source": self.A, "boundaries": [self.B]}, {})
        self.assertEqual(_vox(result), 8)  # == A ∩ B

    def test_ring_shell(self):
        result = execute_operation(
            "ring", {"source": self.A}, {"variant": "UNIFORM", "thickness_mm": 2.0, "kernel_type": "ball"}
        )
        # A shell: non-empty and does not include the original interior.
        self.assertGreater(_vox(result), 0)
        arr = sitk.GetArrayFromImage(result)
        original = sitk.GetArrayFromImage(self.A)
        self.assertEqual(int(np.count_nonzero(arr & original)), 0)

    def test_overlap(self):
        result = execute_operation("overlap", {"source": self.A, "others": [self.B]}, {})
        self.assertEqual(_vox(result), 8)  # == A ∩ B

    def test_expand_subtract(self):
        result = execute_operation(
            "expand_subtract",
            {"source": self.A, "subtract": self.B},
            {"variant": "UNIFORM", "distance_mm": 5.0, "kernel_type": "ball"},
        )
        self.assertGreater(_vox(result), 0)

    def test_avoid_margin(self):
        result = execute_operation(
            "avoid_margin",
            {"source": self.A, "avoid": self.B},
            {"variant": "UNIFORM", "margin_mm": 2.0, "kernel_type": "ball"},
        )
        self.assertGreater(_vox(result), 0)
        # Avoiding a margin around B must shrink A relative to A - B.
        plain = execute_operation("subtract", {"primary": self.A, "others": [self.B]}, {})
        self.assertLessEqual(_vox(result), _vox(plain))

    # ---- Refinement ------------------------------------------------------
    def test_refine_operations_return_valid_masks(self):
        cases = [
            ("smooth", {"smoothing_mm": 1.0, "iterations": 1}),
            ("gaussian_smooth", {"sigma_mm": 1.0, "threshold": 0.5}),
            ("fill_holes", {}),
            ("remove_small_components", {"min_size_mm3": 50.0}),
            ("keep_largest", {}),
            ("keep_n_largest", {"n": 2}),
            ("close_gaps", {"gap_size_mm": 2.0}),
            ("remove_protrusions", {"protrusion_size_mm": 1.0}),
        ]
        for op_id, params in cases:
            with self.subTest(op=op_id):
                result = execute_operation(op_id, {"source": self.A}, params)
                self.assertEqual(result.GetSize(), self.A.GetSize())
                self.assertGreaterEqual(_vox(result), 0)

    # ---- Errors ----------------------------------------------------------
    def test_missing_required_role_raises(self):
        with self.assertRaises(OperationExecutionError):
            execute_operation("margin", {}, {"variant": "UNIFORM", "margin_mm": 2.0})

    def test_unknown_op_raises(self):
        with self.assertRaises(KeyError):
            execute_operation("nope", {"source": self.A}, {})

    # ---- Intensity -------------------------------------------------------
    def test_intensity_requires_image(self):
        with self.assertRaises(OperationExecutionError):
            execute_operation("intensity_range", {}, {"ranges": [{"min": 0, "max": 100}]})

    def test_intensity_range_basic(self):
        # Grayscale image: half the volume at 10 HU, half at 1000 HU.
        arr = np.zeros((20, 20, 20), dtype=np.int16)
        arr[:, :10, :] = 10
        arr[:, 10:, :] = 1000
        image = sitk.GetImageFromArray(arr)
        image.SetSpacing((1.0, 1.0, 1.0))
        result = execute_operation(
            "intensity_range", {}, {"ranges": [{"min": 1000, "max": 2000}]}, image=image
        )
        self.assertEqual(_vox(result), 10 * 20 * 20)  # the 1000-HU half


class OperationExecutionRoleCoercionTests(TestCase):
    def setUp(self):
        shape = (20, 20, 20)
        a = np.zeros(shape, dtype=np.uint8)
        a[2:8, 2:8, 2:8] = 1
        self.A = _image(a)

    def test_single_role_tolerates_single_element_list(self):
        result = execute_operation("margin", {"source": [self.A]}, {"variant": "UNIFORM", "margin_mm": 1.0})
        self.assertEqual(result.GetSize(), self.A.GetSize())


class DirectionalMarginTests(TestCase):
    """Six-directional (patient-anatomical) margin: L/R, A/P, H(superior)/F(inferior).

    The mask A is a 6x6x6 cube at indices [2:8] on every axis (20^3 volume, 1 mm
    spacing, identity orientation). Under identity orientation the anatomical
    directions map as: L=+x, R=-x, A=-y, P=+y, H=+z, F=-z.
    """

    def setUp(self):
        a = np.zeros((20, 20, 20), dtype=np.uint8)
        a[2:8, 2:8, 2:8] = 1
        self.A = _image(a)

    def _arr(self, mask):
        return sitk.GetArrayFromImage(mask) > 0

    def _x_range(self, mask):
        xs = np.where(self._arr(mask).any(axis=(0, 1)))[0]
        return int(xs.min()), int(xs.max())

    def _z_range(self, mask):
        zs = np.where(self._arr(mask).any(axis=(1, 2)))[0]
        return int(zs.min()), int(zs.max())

    def test_left_grows_only_positive_x(self):
        r = execute_operation("margin", {"source": self.A}, {"margin_l_mm": 1.0})
        self.assertEqual(self._x_range(r), (2, 8))  # +x edge grows, -x edge fixed
        self.assertEqual(_vox(r), 6 * 6 * 7)

    def test_right_grows_only_negative_x(self):
        r = execute_operation("margin", {"source": self.A}, {"margin_r_mm": 1.0})
        self.assertEqual(self._x_range(r), (1, 7))
        self.assertEqual(_vox(r), 6 * 6 * 7)

    def test_superior_grows_positive_z(self):
        r = execute_operation("margin", {"source": self.A}, {"margin_h_mm": 1.0})
        self.assertEqual(self._z_range(r), (2, 8))
        self.assertEqual(_vox(r), 7 * 6 * 6)

    def test_inferior_grows_negative_z(self):
        r = execute_operation("margin", {"source": self.A}, {"margin_f_mm": 1.0})
        self.assertEqual(self._z_range(r), (1, 7))
        self.assertEqual(_vox(r), 7 * 6 * 6)

    def test_negative_contracts(self):
        r = execute_operation("margin", {"source": self.A}, {"margin_h_mm": -1.0})
        self.assertEqual(self._z_range(r), (2, 6))
        self.assertEqual(_vox(r), 5 * 6 * 6)

    def test_left_and_right(self):
        r = execute_operation(
            "margin", {"source": self.A}, {"margin_l_mm": 1.0, "margin_r_mm": 1.0}
        )
        self.assertEqual(self._x_range(r), (1, 8))
        self.assertEqual(_vox(r), 6 * 6 * 8)

    def test_all_six_equal_uniform(self):
        params = {f"margin_{k}_mm": 1.0 for k in ("l", "r", "a", "p", "h", "f")}
        r = execute_operation("margin", {"source": self.A}, params)
        self.assertEqual(self._x_range(r), (1, 8))
        self.assertEqual(self._z_range(r), (1, 8))
        # True 1 mm Euclidean ball (SDF threshold): edge/corner diagonals are
        # sqrt(2) mm away and stay excluded -> 6 face slabs of 6x6, not the
        # old 8x8x8 L-infinity box.
        self.assertEqual(_vox(r), 6 * 6 * 6 + 6 * (6 * 6))

    def test_legacy_uniform_backcompat(self):
        r = execute_operation(
            "margin", {"source": self.A}, {"variant": "UNIFORM", "margin_mm": 1.0}
        )
        self.assertEqual(self._x_range(r), (1, 8))
        self.assertEqual(self._z_range(r), (1, 8))
        self.assertEqual(_vox(r), 6 * 6 * 6 + 6 * (6 * 6))

    def test_legacy_contract_alias(self):
        r = execute_operation("contract", {"source": self.A}, {"margin_h_mm": 1.0})
        self.assertEqual(self._z_range(r), (2, 6))


class DirectionalCompositeTests(TestCase):
    """Six-directional params for the composite margin-like ops (ring,
    expand_subtract, avoid_margin) through the shared dispatcher.

    Geometry as in DirectionalMarginTests: A = 6x6x6 cube at [2:8],
    B = 8x8x8 cube at [6:14], C = disjoint cube at [14:18].
    """

    def setUp(self):
        a = np.zeros((20, 20, 20), dtype=np.uint8)
        a[2:8, 2:8, 2:8] = 1
        b = np.zeros((20, 20, 20), dtype=np.uint8)
        b[6:14, 6:14, 6:14] = 1
        self.A = _image(a)
        self.B = _image(b)

    def _arr(self, mask):
        return sitk.GetArrayFromImage(mask) > 0

    def _x_range(self, mask):
        xs = np.where(self._arr(mask).any(axis=(0, 1)))[0]
        return int(xs.min()), int(xs.max())

    def test_ring_single_direction_is_a_slab(self):
        # 1 mm shell toward +x only: exactly the 6x6 slab at x=8.
        r = execute_operation("ring", {"source": self.A}, {"thickness_l_mm": 1.0})
        self.assertEqual(self._x_range(r), (8, 8))
        self.assertEqual(_vox(r), 6 * 6)

    def test_ring_uniform_via_six_equal_directions(self):
        params = {f"thickness_{k}_mm": 1.0 for k in ("l", "r", "a", "p", "h", "f")}
        r = execute_operation("ring", {"source": self.A}, params)
        # 1 mm shell = true Euclidean ball growth (6 face slabs) minus the cube.
        self.assertEqual(_vox(r), 6 * (6 * 6))

    def test_ring_zero_thickness_is_empty(self):
        params = {f"thickness_{k}_mm": 0.0 for k in ("l", "r", "a", "p", "h", "f")}
        r = execute_operation("ring", {"source": self.A}, params)
        self.assertEqual(_vox(r), 0)

    def test_expand_subtract_single_direction(self):
        # A grown 1 mm toward +x (L) now spans x=2..8, so it overlaps B over
        # x=6..8 (3) * y=6..7 (2) * z=6..7 (2) = 12 voxels: 252 - 12 = 240.
        r = execute_operation(
            "expand_subtract", {"source": self.A, "subtract": self.B}, {"distance_l_mm": 1.0}
        )
        self.assertEqual(_vox(r), 216 + 6 * 6 - 12)

    def test_avoid_margin_single_direction(self):
        # All-zero directions: plain subtraction A - B = 208.
        params = {f"margin_{k}_mm": 0.0 for k in ("l", "r", "a", "p", "h", "f")}
        r = execute_operation("avoid_margin", {"source": self.A, "avoid": self.B}, params)
        self.assertEqual(_vox(r), 216 - 8)
        # Growing the avoid structure 1 mm toward -z (F, toward A) eats more.
        grown = execute_operation(
            "avoid_margin", {"source": self.A, "avoid": self.B}, {"margin_f_mm": 1.0}
        )
        self.assertLess(_vox(grown), _vox(r))
        self.assertEqual(_vox(grown), 216 - 12)

    def test_legacy_ring_uniform_still_executes(self):
        # Pre-existing pipelines keep working through the legacy params.
        r = execute_operation(
            "ring", {"source": self.A}, {"variant": "UNIFORM", "thickness_mm": 1.0, "kernel_type": "ball"}
        )
        self.assertGreater(_vox(r), 0)
        arr = self._arr(r)
        original = self._arr(self.A)
        self.assertEqual(int(np.count_nonzero(arr & original)), 0)
