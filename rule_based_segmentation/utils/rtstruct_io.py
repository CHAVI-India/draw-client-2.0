"""RTStruct loading, saving, and ROI manipulation utilities."""

import logging
import os
import shutil
import tempfile
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pydicom
import SimpleITK as sitk
from rt_utils import RTStructBuilder

from dicom_handler.models import DICOMInstance, DICOMSeries
from dicom_handler.utils.structure_generation import load_ct_series_as_sitk_image

logger = logging.getLogger(__name__)


def load_rtstruct_and_image(
    rtstruct_path: str,
    series_instance_uid: str,
) -> Tuple[RTStructBuilder, sitk.Image, DICOMSeries]:
    """
    Load an RTStruct and its referenced image series.

    Args:
        rtstruct_path: Path to the RTStruct DICOM file.
        series_instance_uid: Series Instance UID of the referenced CT/MR/PT series.

    Returns:
        Tuple of (RTStructBuilder, SimpleITK image, DICOMSeries).

    Raises:
        ValueError: If the series is not found or has no instances.
        RuntimeError: If loading fails.
    """
    try:
        series = DICOMSeries.objects.get(series_instance_uid=series_instance_uid)
    except DICOMSeries.DoesNotExist:
        raise ValueError(f"DICOMSeries with UID {series_instance_uid} not found")

    instances = list(DICOMInstance.objects.filter(series_instance_uid=series))
    if not instances:
        raise ValueError(f"No DICOM instances found for series {series_instance_uid}")

    temp_dir = None
    try:
        temp_dir = tempfile.mkdtemp(prefix="rbs_rtstruct_work_")
        _copy_instances_to_directory(instances, temp_dir)

        rtstruct = RTStructBuilder.create_from(
            dicom_series_path=temp_dir,
            rt_struct_path=rtstruct_path,
        )

        image = load_ct_series_as_sitk_image({"instances": instances, "series": series})

        logger.info(
            f"Loaded RTStruct {rtstruct_path} with {len(instances)} image instances"
        )
        return rtstruct, image, series
    except Exception as e:
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
        logger.error(f"Failed to load RTStruct {rtstruct_path}: {e}")
        raise RuntimeError(f"Failed to load RTStruct: {e}") from e


def _copy_instances_to_directory(
    instances: List[DICOMInstance],
    target_directory: str,
) -> None:
    """Copy DICOM instance files into a single directory for rt-utils."""
    for idx, instance in enumerate(instances):
        source_path = instance.instance_path
        if not source_path or not os.path.exists(source_path):
            raise ValueError(f"Instance file missing: {source_path}")

        ext = os.path.splitext(source_path)[1] or ".dcm"
        target_path = os.path.join(target_directory, f"image_{idx:04d}{ext}")
        shutil.copy2(source_path, target_path)


def save_rtstruct(rtstruct: RTStructBuilder, output_path: str) -> str:
    """
    Save an RTStruct to disk, creating parent directories if needed.

    Args:
        rtstruct: RTStructBuilder instance to save.
        output_path: Destination file path.

    Returns:
        The output path.
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    rtstruct.save(output_path)
    logger.info(f"Saved RTStruct to {output_path}")
    return output_path


def _backup_rtstruct(original_path: str) -> str:
    """Create a timestamped backup of the original RTStruct file."""
    from datetime import datetime

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{original_path}.backup.{timestamp}.dcm"
    shutil.copy2(original_path, backup_path)
    logger.info(f"Created backup of original RTStruct at {backup_path}")
    return backup_path


def _remove_roi_from_rtstruct(rtstruct: RTStructBuilder, roi_name: str) -> None:
    """Remove an existing ROI from the underlying pydicom dataset."""
    ds = rtstruct.ds

    # Find the ROI number for the given name.
    roi_number = None
    if hasattr(ds, "StructureSetROISequence"):
        for roi in ds.StructureSetROISequence:
            if str(getattr(roi, "ROIName", "")) == roi_name:
                roi_number = int(getattr(roi, "ROINumber", 0))
                break

    if roi_number is None:
        logger.warning(f"ROI '{roi_name}' not found for replacement")
        return

    # Remove from StructureSetROISequence
    if hasattr(ds, "StructureSetROISequence"):
        ds.StructureSetROISequence = [
            roi
            for roi in ds.StructureSetROISequence
            if int(getattr(roi, "ROINumber", 0)) != roi_number
        ]

    # Remove from ROIContourSequence
    if hasattr(ds, "ROIContourSequence"):
        ds.ROIContourSequence = [
            contour
            for contour in ds.ROIContourSequence
            if int(getattr(contour, "ReferencedROINumber", 0)) != roi_number
        ]

    # Remove from RTROIObservationsSequence if present
    if hasattr(ds, "RTROIObservationsSequence"):
        ds.RTROIObservationsSequence = [
            obs
            for obs in ds.RTROIObservationsSequence
            if int(getattr(obs, "ReferencedROINumber", 0)) != roi_number
        ]

    logger.info(f"Removed existing ROI '{roi_name}' (number {roi_number}) before replacement")


def _add_roi_display_type(rtstruct: RTStructBuilder, roi_name: str, roi_type: str) -> None:
    """Set the RT ROI Interpreted Type on the just-added ROI if possible."""
    ds = rtstruct.ds
    if not hasattr(ds, "RTROIObservationsSequence"):
        return
    for obs in ds.RTROIObservationsSequence:
        referenced = getattr(obs, "ReferencedROINumber", None)
        if referenced is None:
            continue
        matching = None
        if hasattr(ds, "StructureSetROISequence"):
            for roi in ds.StructureSetROISequence:
                if int(getattr(roi, "ROINumber", 0)) == int(referenced):
                    matching = roi
                    break
        if matching and getattr(matching, "ROIName", "") == roi_name:
            obs.RTROIInterpretedType = roi_type


def _sitk_to_rtutils_array(mask_sitk: sitk.Image) -> np.ndarray:
    """Convert a SimpleITK mask to rt-utils expected (X, Y, Z) boolean array."""
    arr = sitk.GetArrayFromImage(mask_sitk)  # (Z, Y, X)
    return arr.transpose(2, 1, 0).astype(bool)  # (X, Y, Z)


def _rtutils_to_sitk_array(mask_array: np.ndarray, reference_image: sitk.Image) -> sitk.Image:
    """Convert an rt-utils (X, Y, Z) boolean array to a SimpleITK mask."""
    arr = mask_array.transpose(2, 1, 0).astype(np.uint8)  # (Z, Y, X)
    mask_sitk = sitk.GetImageFromArray(arr)
    mask_sitk.CopyInformation(reference_image)
    return mask_sitk


def load_roi_masks(
    rtstruct: RTStructBuilder,
    ct_image: sitk.Image,
) -> Dict[str, sitk.Image]:
    """
    Load all ROI masks from an RTStruct as SimpleITK masks.

    Args:
        rtstruct: RTStructBuilder instance.
        ct_image: Reference CT/MR/PT image for geometry.

    Returns:
        Dictionary mapping ROI names to SimpleITK masks.
    """
    masks = {}
    for roi_name in rtstruct.get_roi_names():
        try:
            mask_array = rtstruct.get_roi_mask_by_name(roi_name)  # (X, Y, Z)
            masks[roi_name] = _rtutils_to_sitk_array(mask_array, ct_image)
        except Exception as e:
            logger.warning(f"Failed to load ROI '{roi_name}': {e}")
    return masks


def add_mask_as_roi(
    rtstruct: RTStructBuilder,
    mask: sitk.Image,
    name: str,
    color: List[int],
    roi_type: str = "ORGAN",
    replace_existing: bool = False,
) -> RTStructBuilder:
    """
    Add a SimpleITK mask as a new ROI to an RTStruct, optionally replacing an existing ROI.

    Args:
        rtstruct: RTStructBuilder instance.
        mask: SimpleITK binary mask.
        name: Name for the new ROI.
        color: RGB color as [R, G, B].
        roi_type: DICOM ROI type.
        replace_existing: If True, remove any existing ROI with the same name first.

    Returns:
        Updated RTStructBuilder.
    """
    if replace_existing:
        _remove_roi_from_rtstruct(rtstruct, name)

    mask_np = _sitk_to_rtutils_array(mask)
    rtstruct.add_roi(
        mask=mask_np,
        name=name,
        color=color,
        description=f"Generated structure: {name}",
        use_pin_hole=False,
    )
    _add_roi_display_type(rtstruct, name, roi_type)
    logger.info(f"Added ROI '{name}' to RTStruct (replace_existing={replace_existing})")
    return rtstruct
