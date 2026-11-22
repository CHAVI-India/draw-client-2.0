"""Orientation regression tests for the RBS rt-utils <-> SimpleITK conversion.

rt-utils (v2.x) indexes masks as ``(Rows, Columns, Slices)`` = ``(Y, X, Z)``,
whereas SimpleITK's ``GetArrayFromImage`` yields ``(Z, Y, X)``. The old code
transposed with ``(2, 1, 0)`` (an ``(X, Y, Z)`` assumption), which:

* crashes with ``ROIException`` on any non-square in-plane series when writing
  an ROI (rt-utils rejects the swapped in-plane shape), and
* silently mirrors the structure in-plane on square series with asymmetric
  content.

These tests use a non-square in-plane grid and an in-plane-asymmetric mask and
assert *exact voxel positions* (not just voxel counts) across the load /
add round-trip. They fail if the axis order regresses.
"""

import tempfile

import numpy as np
import SimpleITK as sitk
from django.test import TestCase
from rt_utils import RTStructBuilder

from rule_based_segmentation.tests.helpers import create_synthetic_ct_series
from rule_based_segmentation.utils.rtstruct_io import add_mask_as_roi, load_roi_masks


class RBSOrientationRoundTripTests(TestCase):
    # Non-square in-plane: rows(Y)=8, cols(X)=10, slices(Z)=4.
    Z, Y, X = 4, 8, 10

    def _ct_image(self) -> sitk.Image:
        img = sitk.GetImageFromArray(np.zeros((self.Z, self.Y, self.X), dtype=np.int16))
        img.SetSpacing((1.0, 1.0, 1.0))
        img.SetOrigin((0.0, 0.0, 0.0))
        return img

    def _asymmetric_mask(self) -> np.ndarray:
        """A (Z,Y,X) mask that is NOT symmetric under an in-plane (Y,X) swap.

        The distinguishing voxels would land at different (or out-of-range)
        positions if the in-plane axes were transposed.
        """
        m = np.zeros((self.Z, self.Y, self.X), dtype=np.uint8)
        m[1, 1, 8] = 1  # (z=1, y=1, x=8)  -> mirrored: (z=1, y=8, x=1) [y out of range]
        m[1, 2, 8] = 1  # (z=1, y=2, x=8)  -> mirrored: (z=1, y=8, x=2) [y out of range]
        m[2, 7, 1] = 1  # (z=2, y=7, x=1)  -> mirrored: (z=2, y=1, x=7)
        return m

    def _new_rtstruct(self, tmp: str) -> RTStructBuilder:
        create_synthetic_ct_series(tmp, num_slices=self.Z, rows=self.Y, cols=self.X)
        return RTStructBuilder.create_new(tmp)

    def test_load_roi_masks_preserves_orientation(self):
        tmp = tempfile.mkdtemp(prefix="rbs_orient_")
        m = self._asymmetric_mask()
        rt = self._new_rtstruct(tmp)
        # Correct convention: SITK (Z,Y,X) -> rt-utils (Y,X,Z).
        rt.add_roi(mask=m.transpose(1, 2, 0).astype(bool), name="ROI", color=[255, 0, 0])

        masks = load_roi_masks(rt, self._ct_image())
        arr = sitk.GetArrayFromImage(masks["ROI"]).astype(bool)

        self.assertEqual(arr.shape, (self.Z, self.Y, self.X))
        self.assertTrue(
            np.array_equal(arr, m.astype(bool)),
            "loaded mask must equal the original (Z,Y,X) exactly, not a mirror",
        )
        # Pin the exact voxels: these hold only if orientation is correct.
        self.assertTrue(arr[1, 1, 8] and arr[1, 2, 8] and arr[2, 7, 1])
        # The in-plane-mirrored positions must be empty.
        self.assertFalse(arr[2, 1, 7])

    def test_add_mask_as_roi_roundtrip(self):
        tmp = tempfile.mkdtemp(prefix="rbs_orient_")
        rt = self._new_rtstruct(tmp)
        src = self._ct_image()
        m = self._asymmetric_mask()

        mask_sitk = sitk.GetImageFromArray(m)
        mask_sitk.CopyInformation(src)

        add_mask_as_roi(rt, mask_sitk, "NewROI", [0, 255, 0])

        masks = load_roi_masks(rt, src)
        arr = sitk.GetArrayFromImage(masks["NewROI"]).astype(bool)
        self.assertTrue(
            np.array_equal(arr, m.astype(bool)),
            "add_mask_as_roi -> load_roi_masks must be an exact round-trip",
        )

    def test_write_rejects_wrong_inplane_shape(self):
        """Guard: an in-plane-transposed (X,Y,Z) mask must be rejected by
        rt-utils on a non-square series (this is what the old code produced)."""
        tmp = tempfile.mkdtemp(prefix="rbs_orient_")
        rt = self._new_rtstruct(tmp)
        m = self._asymmetric_mask()
        with self.assertRaises(Exception):
            # (Z,Y,X) -> (X,Y,Z) is the buggy transpose; in-plane (10,8) != (8,10).
            rt.add_roi(mask=m.transpose(2, 1, 0).astype(bool), name="Bad", color=[1, 2, 3])
