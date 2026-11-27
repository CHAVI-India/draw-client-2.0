"""Reusable synthetic RTStruct fixture with *known* voxel shapes.

A handful of axis-aligned box ROIs is written into a copy of the existing
de-identified RTStruct (on the existing de-identified planning CT -- no new CT
is created). Because every box's voxel membership is defined exactly, every
structure a pipeline produces can be asserted against an independently computed
ground truth.

Why this is reliable on this CT:

* Axis-aligned boxes round-trip exactly through rt_utils' contour
  encode/decode -- verified empirically on this series (0 mismatched voxels)
  even though the raw files sit in arbitrary on-disk order.
* ``rt_utils`` sorts the series by slice position internally, and the app's own
  sitk load does the same (``_series_slice_order``), so the mask geometry and the
  contour geometry agree on a uniform 2.5 mm z-spacing.
* Boolean / crop / intensity are pure image-space (voxel-index) set operations,
  so their ground truth is exact numpy on the box arrays.
* Margin is a voxel-grid dilation/erosion by ``ceil(|mm| / spacing)`` voxels per
  axis (a plain ``sitk.BinaryDilate``/``BinaryErode``), so it is predictable too.

The fixture is built on demand by :func:`build_synthetic_rtstruct` and can also
be persisted to a stable path for reuse (see the ``synthetic`` test-data dir).
"""

from __future__ import annotations

import os

import numpy as np
import SimpleITK as sitk
from rt_utils import RTStructBuilder

from dicom_handler.utils.structure_generation.geometry import _series_slice_order
from rule_based_segmentation.utils.rtstruct_io import (
    _remove_roi_from_rtstruct,
    add_mask_as_roi,
)

# Location of the de-identified RT dataset (CT + RTSTRUCT) under this app's
# tests, and the stable path the generated fixture is persisted to for reuse.
DATASET_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests", "dicom_data"
)
SYNTHETIC_FIXTURE_DIR = os.path.join(DATASET_ROOT, "synthetic")
SYNTHETIC_FIXTURE_PATH = os.path.join(SYNTHETIC_FIXTURE_DIR, "synthetic_boxes_rtstruct.dcm")


def find_deidentified_dataset(dataset_root: str = DATASET_ROOT):
    """Locate the de-identified RT dataset on disk.

    Returns ``(ct_dir, ct_files, base_rtstruct_path)`` where ``ct_dir`` holds the
    CT DICOM files (for rt_utils geometry) and ``base_rtstruct_path`` is the
    RTSTRUCT whose referenced frame of reference matches the CT.
    """
    ct_files: list[str] = []
    rtstruct_path: str | None = None
    for root, _dirs, files in os.walk(dataset_root):
        for name in files:
            if name.endswith(".bin"):
                continue
            path = os.path.join(root, name)
            try:
                import pydicom

                ds = pydicom.dcmread(path, stop_before_pixels=True, force=True)
            except Exception:
                continue
            modality = str(getattr(ds, "Modality", "")).upper()
            if modality == "CT":
                ct_files.append(path)
            elif modality == "RTSTRUCT" and rtstruct_path is None:
                rtstruct_path = path
    if not ct_files or rtstruct_path is None:
        raise FileNotFoundError(f"no CT series / RTSTRUCT found under {dataset_root}")
    return os.path.dirname(ct_files[0]), sorted(ct_files), rtstruct_path


def load_ct_image_from_dir(ct_dir: str) -> sitk.Image:
    """Load a CT series from a directory as a sitk image (DB-free), ordering the
    slices by position first. Only image-modalities (CT/MR/PT) are used, so the
    directory may also hold an RTSTRUCT/RTPLAN/RTDOSE."""
    import pydicom

    files = []
    for f in os.listdir(ct_dir):
        if not f.lower().endswith((".dcm", ".dicom")):
            continue
        path = os.path.join(ct_dir, f)
        try:
            ds = pydicom.dcmread(path, stop_before_pixels=True, force=True)
        except Exception:
            continue
        if str(getattr(ds, "Modality", "")).upper() in ("CT", "MR", "PT"):
            files.append(path)
    if not files:
        raise FileNotFoundError(f"no CT/MR/PT images under {ct_dir}")
    files = _series_slice_order(files)
    reader = sitk.ImageSeriesReader()
    reader.SetFileNames(files)
    return reader.Execute()

# Name -> (z0, z1, y0, y1, x0, x1) in IMAGE space (slice-index, row, column).
#
# Relationships (all verified in the tests):
#   BoxB overlaps BoxA  (shared region z 30:60, y 150:200, x 150:200)
#   BoxD is fully inside BoxA
#   BoxC is disjoint from both BoxA and BoxB (separated in y)
KNOWN_BOXES: dict[str, tuple[int, int, int, int, int, int]] = {
    "BoxA": (0, 60, 100, 200, 100, 200),
    "BoxB": (30, 120, 150, 280, 150, 280),
    "BoxC": (0, 40, 350, 420, 350, 420),
    "BoxD": (5, 30, 120, 160, 120, 160),
}

# Distinct, unambiguous colors so a mis-mapped box cannot hide behind another.
BOX_COLORS = {
    "BoxA": [255, 0, 0],
    "BoxB": [0, 200, 0],
    "BoxC": [0, 0, 255],
    "BoxD": [255, 255, 0],
}


def box_array(name: str, shape_zyx: tuple[int, int, int]) -> np.ndarray:
    """The (Z, Y, X) uint8 mask for a known box (1 inside, 0 outside)."""
    z0, z1, y0, y1, x0, x1 = KNOWN_BOXES[name]
    arr = np.zeros(shape_zyx, dtype=np.uint8)
    arr[z0:z1, y0:y1, x0:x1] = 1
    return arr


def all_box_arrays(shape_zyx: tuple[int, int, int]) -> dict[str, np.ndarray]:
    return {name: box_array(name, shape_zyx) for name in KNOWN_BOXES}


def build_synthetic_rtstruct(
    ct_dir: str,
    base_rtstruct_path: str,
    out_path: str,
    ct_image: sitk.Image,
) -> str:
    """Write the known box ROIs into a copy of ``base_rtstruct_path`` and save.

    All pre-existing ROIs from the base structure set are removed so the result
    contains *only* the known boxes -- a clean, fully-specified input set.

    Args:
        ct_dir: Directory holding the CT DICOM files (for rt_utils geometry).
        base_rtstruct_path: An RTStruct whose referenced frame of reference
            matches the CT (used only for that linkage).
        out_path: Where to write the synthetic RTStruct.
        ct_image: The reference sitk image (the mask geometry is copied from it).

    Returns:
        ``out_path``.
    """
    rb = RTStructBuilder.create_from(
        dicom_series_path=ct_dir, rt_struct_path=base_rtstruct_path
    )
    # Drop the base structure set's ROIs so only the known boxes remain.
    for existing in list(rb.get_roi_names()):
        _remove_roi_from_rtstruct(rb, existing)

    shape_zyx = ct_image.GetSize()[::-1]  # (X, Y, Z) -> (Z, Y, X)
    for name in KNOWN_BOXES:
        mask = sitk.GetImageFromArray(box_array(name, shape_zyx).astype(np.uint8))
        mask.CopyInformation(ct_image)
        add_mask_as_roi(rb, mask, name, list(BOX_COLORS[name]), "ORGAN")

    rb.save(out_path)
    return out_path


def read_roi_mask_zyx(rtstruct_path: str, ct_dir: str, roi_name: str) -> np.ndarray:
    """Read one ROI from an RTStruct as a boolean (Z, Y, X) array."""
    rb = RTStructBuilder.create_from(
        dicom_series_path=ct_dir, rt_struct_path=rtstruct_path
    )
    mask_ypx = rb.get_roi_mask_by_name(roi_name)  # rt_utils -> (Y, X, Z)
    return mask_ypx.transpose(2, 0, 1).astype(bool)  # -> (Z, Y, X)


def expected_margin(array_zyx: np.ndarray, margin_mm: float, spacing) -> np.ndarray:
    """Ground-truth for a margin, as an L-infinity (box) dilation/erosion by
    ``ceil(|mm| / spacing)`` voxels per axis.

    This matches the engine's margin path exactly: a (uniform or anisotropic)
    margin is applied through ``apply_directional_margin`` -- six one-sided,
    line-shaped dilations/erosions along the array axes -- whose union is the
    full L-infinity box of the given per-axis radius. (A plain
    ``sitk.BinaryDilate`` ball, by contrast, leaves the corners unfilled and is
    therefore *not* the engine's margin.) ``scipy.ndimage``'s box
    dilation/erosion is the independent ground truth for that L-infinity box.
    """
    from scipy import ndimage

    arr = np.asarray(array_zyx).astype(bool)
    rx, ry, rz = (int(np.ceil(abs(margin_mm) / s)) for s in spacing)  # spacing=(x,y,z)
    # scipy operates on the (Z, Y, X) array, so the structure is (rz, ry, rx).
    struct = np.ones((2 * rz + 1, 2 * ry + 1, 2 * rx + 1), dtype=int)
    if margin_mm > 0:
        return ndimage.binary_dilation(arr, structure=struct)
    return ndimage.binary_erosion(arr, structure=struct)


def expected_crop(array_zyx: np.ndarray, *boundaries) -> np.ndarray:
    """Ground-truth for crop-to-boundary: intersection with every boundary."""
    result = np.asarray(array_zyx).astype(bool)
    for b in boundaries:
        result = result & np.asarray(b).astype(bool)
    return result


def expected_intensity(
    ct_zyx: np.ndarray,
    ranges: list[tuple[float, float]],
    seed: np.ndarray | None = None,
    boundary: np.ndarray | None = None,
) -> np.ndarray:
    """Ground-truth for intensity-range segmentation: voxels inside any range,
    restricted by an optional seed and/or boundary (matches
    ``intensity_range_segmentation`` exactly)."""
    img = np.asarray(ct_zyx)
    mask = np.zeros(img.shape, dtype=bool)
    for lo, hi in ranges:
        mask |= (img >= lo) & (img <= hi)
    if seed is not None:
        mask &= np.asarray(seed).astype(bool)
    if boundary is not None:
        mask &= np.asarray(boundary).astype(bool)
    return mask


def boolean_gt(op: str, *operands: np.ndarray) -> np.ndarray:
    """Ground-truth for a (left-associative) boolean op over boolean arrays.

    Operands may themselves be pre-computed group arrays (i.e. nested groups),
    mirroring how the engine folds a boolean tree."""
    arrays = [np.asarray(a).astype(bool) for a in operands]
    if op == "UNION":
        result = arrays[0]
        for a in arrays[1:]:
            result = result | a
        return result
    if op == "INTERSECTION":
        result = arrays[0]
        for a in arrays[1:]:
            result = result & a
        return result
    if op == "SUBTRACT":
        result = arrays[0]
        for a in arrays[1:]:
            result = result & ~a
        return result
    if op == "XOR":
        result = arrays[0]
        for a in arrays[1:]:
            result = result ^ a
        return result
    raise ValueError(f"unknown op {op}")


def generate_persistent_fixture(out_path: str | None = None) -> str:
    """Build the synthetic known-box RTStruct from the de-identified dataset and
    persist it for reuse (DB-free).

    Run once (e.g. ``manage.py shell``) to (re)generate the committed artifact:
    ``python manage.py shell -c "from rule_based_segmentation.tests.synthetic_fixture import generate_persistent_fixture; generate_persistent_fixture()"``

    Returns the path written.
    """
    out_path = out_path or SYNTHETIC_FIXTURE_PATH
    ct_dir, _ct_files, base_rtstruct = find_deidentified_dataset()
    ct_image = load_ct_image_from_dir(ct_dir)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    build_synthetic_rtstruct(ct_dir, base_rtstruct, out_path, ct_image)
    return out_path


def verify_fixture_boxes(rtstruct_path: str, ct_dir: str) -> dict[str, bool]:
    """Check that each known box in a synthetic RTStruct matches its definition.

    Returns ``{name: ok}``. Used to confirm a persisted fixture is still valid.
    """
    shape = load_ct_image_from_dir(ct_dir).GetSize()[::-1]
    results: dict[str, bool] = {}
    for name in KNOWN_BOXES:
        try:
            got = read_roi_mask_zyx(rtstruct_path, ct_dir, name)
            results[name] = bool(np.array_equal(got, box_array(name, shape)))
        except Exception:
            results[name] = False
    return results
