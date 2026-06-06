"""
Conversion utilities between RTStruct contours and SimpleITK binary masks.

This module handles:
- Converting RTStruct ROI contours to SimpleITK binary masks
- Converting SimpleITK masks back to RTStruct contours
- Handling coordinate transformations and axis ordering
"""

import SimpleITK as sitk
import numpy as np
from rt_utils import RTStructBuilder
import logging
from typing import Tuple, List, Optional, Dict, Any
import os

logger = logging.getLogger(__name__)


def rtstruct_roi_to_sitk_mask(
    rtstruct_path: str,
    ct_image: sitk.Image,
    roi_name: str,
    dicom_series_path: str
) -> sitk.Image:
    """
    Convert a specific ROI from RTStruct to SimpleITK binary mask.
    
    This function uses rt-utils to extract contours and convert them to a
    3D binary mask, then wraps it in a SimpleITK image with proper geometry.
    
    Args:
        rtstruct_path: Path to RTStruct DICOM file
        ct_image: Reference SimpleITK CT image (for geometry)
        roi_name: Name of the ROI to extract
        dicom_series_path: Path to directory containing CT DICOM files
        
    Returns:
        sitk.Image: Binary mask (0 and 1) with same geometry as ct_image
        
    Raises:
        ValueError: If ROI name not found in RTStruct
        RuntimeError: If conversion fails
    """
    try:
        logger.info(f"Converting ROI '{roi_name}' from RTStruct to SimpleITK mask")
        
        # Load RTStruct using rt-utils
        rtstruct = RTStructBuilder.create_from(
            dicom_series_path=dicom_series_path,
            rt_struct_path=rtstruct_path
        )
        
        # Get list of available ROI names
        roi_names = rtstruct.get_roi_names()
        logger.debug(f"Available ROIs: {roi_names}")
        
        if roi_name not in roi_names:
            raise ValueError(f"ROI '{roi_name}' not found in RTStruct. Available ROIs: {roi_names}")
        
        # Extract mask as numpy array
        # rt-utils returns array in (Z, Y, X) order
        mask_np = rtstruct.get_roi_mask_by_name(roi_name)
        
        logger.debug(f"Extracted mask shape: {mask_np.shape}, dtype: {mask_np.dtype}")
        
        # Convert to SimpleITK image
        mask_sitk = numpy_to_sitk_mask(mask_np, ct_image)
        
        logger.info(f"Successfully converted ROI '{roi_name}' to SimpleITK mask")
        return mask_sitk
        
    except Exception as e:
        logger.error(f"Failed to convert ROI '{roi_name}' to mask: {str(e)}")
        raise RuntimeError(f"RTStruct to mask conversion failed: {str(e)}")


def sitk_mask_to_numpy(mask_sitk: sitk.Image) -> np.ndarray:
    """
    Convert SimpleITK mask to numpy array.
    
    Handles axis ordering: SimpleITK uses (X, Y, Z) order internally,
    but GetArrayFromImage returns (Z, Y, X) order for numpy compatibility.
    
    Args:
        mask_sitk: SimpleITK binary mask
        
    Returns:
        np.ndarray: Binary mask in (Z, Y, X) order, dtype uint8
    """
    # GetArrayFromImage automatically converts from SimpleITK (X,Y,Z) to numpy (Z,Y,X)
    mask_np = sitk.GetArrayFromImage(mask_sitk)
    
    # Ensure binary (0 and 1)
    mask_np = (mask_np > 0).astype(np.uint8)
    
    return mask_np


def numpy_to_sitk_mask(
    mask_np: np.ndarray,
    reference_image: sitk.Image
) -> sitk.Image:
    """
    Convert numpy mask to SimpleITK image with proper geometry.
    
    Args:
        mask_np: Numpy array in (Z, Y, X) order
        reference_image: Reference SimpleITK image to copy geometry from
        
    Returns:
        sitk.Image: Binary mask with same geometry as reference_image
    """
    # Ensure binary
    mask_np = (mask_np > 0).astype(np.uint8)
    
    # Convert to SimpleITK image
    # GetImageFromArray automatically converts from numpy (Z,Y,X) to SimpleITK (X,Y,Z)
    mask_sitk = sitk.GetImageFromArray(mask_np)
    
    # Copy geometric information from reference image
    mask_sitk.SetSpacing(reference_image.GetSpacing())
    mask_sitk.SetOrigin(reference_image.GetOrigin())
    mask_sitk.SetDirection(reference_image.GetDirection())
    
    return mask_sitk


def add_sitk_mask_to_rtstruct(
    rtstruct: RTStructBuilder,
    mask_sitk: sitk.Image,
    roi_name: str,
    roi_color: List[int],
    roi_type: str = "ORGAN"
) -> RTStructBuilder:
    """
    Add a SimpleITK mask as a new ROI to an RTStruct.
    
    This function converts the SimpleITK mask to numpy format and uses
    rt-utils to generate contours and add them to the RTStruct.
    
    Args:
        rtstruct: RTStructBuilder instance
        mask_sitk: SimpleITK binary mask to add
        roi_name: Name for the new ROI
        roi_color: RGB color as [R, G, B] where each value is 0-255
        roi_type: DICOM ROI type (e.g., "ORGAN", "PTV", "CTV", "GTV")
        
    Returns:
        RTStructBuilder: Updated RTStruct with new ROI added
    """
    logger.info(f"Adding SimpleITK mask as ROI '{roi_name}' to RTStruct")
    
    # Convert to numpy array
    mask_np = sitk_mask_to_numpy(mask_sitk)
    
    # Add to RTStruct using rt-utils
    # rt-utils automatically:
    # - Finds contours on each slice using OpenCV
    # - Converts pixel coordinates to patient coordinates
    # - Creates proper DICOM contour sequences
    rtstruct.add_roi(
        mask=mask_np,
        name=roi_name,
        color=roi_color,
        description=f"Generated structure: {roi_name}",
        use_pin_hole=False  # Use standard contour extraction
    )
    
    logger.info(f"Successfully added ROI '{roi_name}' to RTStruct")
    return rtstruct


def load_multiple_rois_as_masks(
    rtstruct_path: str,
    ct_image: sitk.Image,
    roi_names: List[str],
    dicom_series_path: str
) -> Dict[str, sitk.Image]:
    """
    Load multiple ROIs from RTStruct as SimpleITK masks.
    
    Args:
        rtstruct_path: Path to RTStruct DICOM file
        ct_image: Reference SimpleITK CT image
        roi_names: List of ROI names to extract
        dicom_series_path: Path to directory containing CT DICOM files
        
    Returns:
        Dictionary mapping ROI names to SimpleITK masks
    """
    masks = {}
    
    # Load RTStruct once
    rtstruct = RTStructBuilder.create_from(
        dicom_series_path=dicom_series_path,
        rt_struct_path=rtstruct_path
    )
    
    available_rois = rtstruct.get_roi_names()
    
    for roi_name in roi_names:
        if roi_name not in available_rois:
            logger.warning(f"ROI '{roi_name}' not found in RTStruct. Skipping.")
            continue
        
        try:
            mask_np = rtstruct.get_roi_mask_by_name(roi_name)
            mask_sitk = numpy_to_sitk_mask(mask_np, ct_image)
            masks[roi_name] = mask_sitk
            logger.info(f"Loaded ROI '{roi_name}' as mask")
        except Exception as e:
            logger.error(f"Failed to load ROI '{roi_name}': {str(e)}")
            continue
    
    return masks


def create_empty_mask_like(reference_image: sitk.Image) -> sitk.Image:
    """
    Create an empty (all zeros) mask with the same geometry as reference image.
    
    Args:
        reference_image: Reference SimpleITK image
        
    Returns:
        sitk.Image: Empty binary mask
    """
    size = reference_image.GetSize()
    empty_mask = sitk.Image(size, sitk.sitkUInt8)
    empty_mask.SetSpacing(reference_image.GetSpacing())
    empty_mask.SetOrigin(reference_image.GetOrigin())
    empty_mask.SetDirection(reference_image.GetDirection())
    
    return empty_mask


def resample_mask_to_reference(
    mask: sitk.Image,
    reference: sitk.Image,
    interpolator: int = sitk.sitkNearestNeighbor
) -> sitk.Image:
    """
    Resample a mask to match the geometry of a reference image.
    
    Useful when masks have different spacing or orientation than the target CT.
    
    Args:
        mask: SimpleITK mask to resample
        reference: Reference image with target geometry
        interpolator: Interpolation method (default: nearest neighbor for binary masks)
        
    Returns:
        sitk.Image: Resampled mask matching reference geometry
    """
    resampler = sitk.ResampleImageFilter()
    resampler.SetReferenceImage(reference)
    resampler.SetInterpolator(interpolator)
    resampler.SetDefaultPixelValue(0)
    resampler.SetOutputPixelType(sitk.sitkUInt8)
    
    resampled_mask = resampler.Execute(mask)
    
    # Ensure binary
    resampled_mask = resampled_mask > 0
    
    return resampled_mask


def get_roi_names_from_rtstruct(rtstruct_path: str, dicom_series_path: str) -> List[str]:
    """
    Get list of all ROI names in an RTStruct file.
    
    Args:
        rtstruct_path: Path to RTStruct DICOM file
        dicom_series_path: Path to directory containing CT DICOM files
        
    Returns:
        List of ROI names
    """
    try:
        rtstruct = RTStructBuilder.create_from(
            dicom_series_path=dicom_series_path,
            rt_struct_path=rtstruct_path
        )
        return rtstruct.get_roi_names()
    except Exception as e:
        logger.error(f"Failed to read ROI names from RTStruct: {str(e)}")
        return []
