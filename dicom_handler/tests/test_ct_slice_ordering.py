"""Regression test for CT slice ordering on load.

``sitk.ImageSeriesReader`` does not reliably normalise unsorted input: feeding
it the DICOM files in an arbitrary (e.g. database) order can yield a mis-computed
*average* inter-slice spacing and a drifted physical<->voxel mapping (surfacing
as a "Non uniform sampling or missing slices detected" warning) -- even for a
perfectly uniform planning CT. That corrupts every mm-based operation (margin
radius, crop boundaries, physical distances).

These tests pin down that ``load_ct_series_as_sitk_image`` orders the files by
slice position first (via ``_series_slice_order``) and that the resulting volume
is uniform.

* ``test_sort_*`` are pure unit tests of the ordering helper (no DB).
* ``test_load_real_ct_uniform_*`` loads the de-identified 190-slice planning CT
  (under ``rule_based_segmentation/tests/dicom_data``) in a *shuffled* instance
  order and asserts the loaded volume is uniform and complete.
"""

import os
import tempfile

import numpy as np
import pydicom
from django.test import SimpleTestCase
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

from dicom_handler.utils.structure_generation import geometry
from dicom_handler.utils.structure_generation.geometry import (
    _series_slice_order,
    load_ct_series_as_sitk_image,
)

CT_SOP_CLASS = "1.2.840.10008.5.1.4.1.1.2"  # CT Image Storage


def _make_ct_slice(path, z, x=0.0, y=0.0):
    """Write a minimal, header-only CT slice at patient z."""
    ds = Dataset()
    ds.PatientID = "SORTTEST"
    ds.SOPClassUID = CT_SOP_CLASS
    ds.SOPInstanceUID = generate_uid()
    ds.Modality = "CT"
    ds.SliceThickness = 2.5
    ds.Rows = 4
    ds.Columns = 4
    ds.PixelSpacing = [1.0, 1.0]
    ds.ImagePositionPatient = [x, y, z]
    ds.ImageOrientationPatient = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 0
    ds.PixelData = b"\x00" * 32
    ds.file_meta = FileMetaDataset()
    ds.file_meta.MediaStorageSOPClassUID = CT_SOP_CLASS
    ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.save_as(path)


class SeriesSliceOrderTests(SimpleTestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rbs_sort_")
        # five slices whose z positions are deliberately NOT in file order
        zs = [5.0, 10.0, 0.0, 15.0, 20.0]
        self.paths = []
        for i, z in enumerate(zs):
            p = os.path.join(self.tmp, f"s{i}.dcm")
            _make_ct_slice(p, z)
            self.paths.append(p)

    def _z(self, p):
        return float(pydicom.dcmread(p, stop_before_pixels=True, force=True).ImagePositionPatient[2])

    def test_sort_orders_by_slice_position(self):
        # feed in reverse -> expect ascending z
        ordered = _series_slice_order(list(reversed(self.paths)))
        z_values = [self._z(p) for p in ordered]
        self.assertEqual(z_values, [0.0, 5.0, 10.0, 15.0, 20.0])

    def test_sort_preserves_all_files(self):
        ordered = _series_slice_order(list(reversed(self.paths)))
        self.assertEqual(set(ordered), set(self.paths))
        self.assertEqual(len(ordered), len(self.paths))

    def test_sort_noop_when_already_sorted(self):
        asc = sorted(self.paths, key=self._z)
        self.assertEqual(_series_slice_order(asc), asc)

    def test_sort_empty(self):
        self.assertEqual(_series_slice_order([]), [])


class RealCtSliceOrderingTests(SimpleTestCase):
    """Load the de-identified planning CT in a shuffled order; the volume must
    come out uniform and complete."""

    @classmethod
    def _ct_files(cls):
        base = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "rule_based_segmentation", "tests", "dicom_data",
        )
        found = []
        for root, _dirs, files in os.walk(base):
            for name in files:
                path = os.path.join(root, name)
                try:
                    ds = pydicom.dcmread(path, stop_before_pixels=True, force=True)
                except Exception:
                    continue
                if str(getattr(ds, "Modality", "")).upper() == "CT":
                    found.append(path)
        return base, found

    def test_load_shuffled_real_ct_is_uniform_and_complete(self):
        base, ct_files = self._ct_files()
        if not ct_files:
            self.skipTest(f"no de-identified CT files under {base}")
        self.assertGreaterEqual(len(ct_files), 50, "expected a full CT series")

        # Deliberately non-ordered instance list (reverse of sorted-by-name).
        shuffled = sorted(ct_files, key=os.path.basename)[::-1]
        from types import SimpleNamespace

        instances = [SimpleNamespace(instance_path=p) for p in shuffled]
        import SimpleITK as sitk  # noqa: F401  (ensures available)
        img = load_ct_series_as_sitk_image({"instances": instances, "series": None})

        # Complete: every slice present.
        self.assertEqual(img.GetSize()[2], len(ct_files))

        # Uniform: no large inter-slice gap (the pre-fix bug produced a ~450 mm
        # "non uniform" jump). The planning CT is 2.5 mm, so a max gap well
        # under 5 mm proves the spacing is not the mis-computed average.
        z_positions = np.array([
            img.TransformIndexToPhysicalPoint((0, 0, i))[2]
            for i in range(img.GetSize()[2])
        ])
        # The series may be ascending or descending; take absolute gaps.
        gaps = np.abs(np.diff(z_positions))
        self.assertLess(
            float(gaps.max()), 5.0,
            f"non-uniform z-sampling (max gap {gaps.max():.1f} mm) -- slices were "
            f"not ordered by position before loading",
        )
        self.assertAlmostEqual(img.GetSpacing()[2], float(np.median(gaps)), delta=1.0)

    def test_sort_restores_true_slice_thickness(self):
        """Feeding ``ImageSeriesReader`` unsorted input mis-computes the spacing
        (a compressed average); ``_series_slice_order`` restores the true
        slice thickness."""
        _base, ct_files = self._ct_files()
        if not ct_files:
            self.skipTest("no de-identified CT files")
        import SimpleITK as sitk

        def z_spacing(files):
            reader = sitk.ImageSeriesReader()
            reader.SetFileNames(files)
            return reader.Execute().GetSpacing()[2]

        # True slice thickness = median of the raw (sorted-by-position) gaps.
        zs = sorted(
            float(pydicom.dcmread(p, stop_before_pixels=True, force=True)
                  .ImagePositionPatient[2])
            for p in ct_files
        )
        true_thickness = float(np.median(np.diff(zs)))
        self.assertGreater(true_thickness, 0.5)

        shuffled = list(reversed(ct_files))
        sorted_spacing = z_spacing(_series_slice_order(shuffled))
        unsorted_spacing = z_spacing(shuffled)

        # Sorted load recovers the true thickness; unsorted does not.
        self.assertAlmostEqual(sorted_spacing, true_thickness, delta=0.5)
        # The pre-fix behaviour averages the spacing to something clearly off.
        self.assertGreater(sorted_spacing, unsorted_spacing)
