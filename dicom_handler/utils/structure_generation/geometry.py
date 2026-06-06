"""
Geometry utilities for CT series loading and coordinate handling.

This module handles:
- Loading DICOM CT series as SimpleITK images with proper geometric information
- Extracting and validating geometric metadata (spacing, origin, direction)
- Coordinate system transformations
"""

import SimpleITK as sitk
import os
import logging
from typing import List, Dict, Any, Tuple
import numpy as np

logger = logging.getLogger(__name__)


def load_ct_series_as_sitk_image(series_data: Dict[str, Any]) -> sitk.Image:
    """
    Load CT DICOM series as a SimpleITK image.
    
    This function loads all DICOM instances from the database and creates a 3D
    SimpleITK image with proper geometric information (spacing, origin, direction).
    
    Args:
        series_data: Dictionary containing:
            - 'instances': List of DICOMInstance objects with instance_path
            - 'series': DICOMSeries object (for metadata)
    
    Returns:
        sitk.Image: 3D CT image with proper geometry
        
    Raises:
        ValueError: If no valid DICOM files found or if files cannot be read
        RuntimeError: If SimpleITK fails to load the series
    """
    instances = series_data.get('instances', [])
    
    if not instances:
        raise ValueError("No DICOM instances found in series_data")
    
    # Collect valid file paths
    dicom_files = []
    for instance in instances:
        if instance.instance_path and os.path.exists(instance.instance_path):
            dicom_files.append(instance.instance_path)
        else:
            logger.warning(f"Instance path not found or invalid: {instance.instance_path}")
    
    if not dicom_files:
        raise ValueError("No valid DICOM files found - all instance paths are missing or invalid")
    
    logger.info(f"Loading CT series with {len(dicom_files)} slices")
    
    try:
        # Use SimpleITK's ImageSeriesReader for proper DICOM series loading
        reader = sitk.ImageSeriesReader()
        reader.SetFileNames(dicom_files)
        
        # Load the series
        # This automatically:
        # - Sorts slices by ImagePositionPatient
        # - Sets correct spacing (PixelSpacing + slice thickness)
        # - Sets origin from ImagePositionPatient
        # - Sets direction from ImageOrientationPatient
        ct_image = reader.Execute()
        
        # Log geometric information
        spacing = ct_image.GetSpacing()
        origin = ct_image.GetOrigin()
        size = ct_image.GetSize()
        
        logger.info(f"CT image loaded successfully:")
        logger.info(f"  Size: {size} voxels")
        logger.info(f"  Spacing: {spacing} mm")
        logger.info(f"  Origin: {origin} mm")
        
        return ct_image
        
    except Exception as e:
        logger.error(f"Failed to load CT series: {str(e)}")
        raise RuntimeError(f"SimpleITK failed to load CT series: {str(e)}")


def get_ct_geometry_info(ct_image: sitk.Image) -> Dict[str, Any]:
    """
    Extract geometric information from a SimpleITK CT image.
    
    Args:
        ct_image: SimpleITK image
        
    Returns:
        Dictionary containing:
            - 'spacing': Tuple of (x, y, z) spacing in mm
            - 'origin': Tuple of (x, y, z) origin in mm
            - 'direction': Tuple of 9 direction cosines
            - 'size': Tuple of (x, y, z) dimensions in voxels
            - 'physical_size': Tuple of (x, y, z) physical dimensions in mm
    """
    spacing = ct_image.GetSpacing()
    origin = ct_image.GetOrigin()
    direction = ct_image.GetDirection()
    size = ct_image.GetSize()
    
    # Calculate physical size
    physical_size = tuple(s * sp for s, sp in zip(size, spacing))
    
    geometry_info = {
        'spacing': spacing,
        'origin': origin,
        'direction': direction,
        'size': size,
        'physical_size': physical_size,
        'dimension': ct_image.GetDimension()
    }
    
    return geometry_info


def validate_mask_geometry(mask: sitk.Image, reference: sitk.Image) -> bool:
    """
    Validate that a mask has the same geometry as a reference image.
    
    This checks that spacing, origin, direction, and size match between
    the mask and reference image. This is critical for proper alignment
    when performing operations.
    
    Args:
        mask: SimpleITK mask image to validate
        reference: Reference SimpleITK image (typically the CT image)
        
    Returns:
        bool: True if geometries match, False otherwise
    """
    # Check spacing
    mask_spacing = mask.GetSpacing()
    ref_spacing = reference.GetSpacing()
    spacing_match = np.allclose(mask_spacing, ref_spacing, rtol=1e-5)
    
    # Check origin
    mask_origin = mask.GetOrigin()
    ref_origin = reference.GetOrigin()
    origin_match = np.allclose(mask_origin, ref_origin, rtol=1e-5)
    
    # Check direction
    mask_direction = mask.GetDirection()
    ref_direction = reference.GetDirection()
    direction_match = np.allclose(mask_direction, ref_direction, rtol=1e-5)
    
    # Check size
    mask_size = mask.GetSize()
    ref_size = reference.GetSize()
    size_match = mask_size == ref_size
    
    if not spacing_match:
        logger.warning(f"Spacing mismatch: mask={mask_spacing}, reference={ref_spacing}")
    if not origin_match:
        logger.warning(f"Origin mismatch: mask={mask_origin}, reference={ref_origin}")
    if not direction_match:
        logger.warning(f"Direction mismatch: mask={mask_direction}, reference={ref_direction}")
    if not size_match:
        logger.warning(f"Size mismatch: mask={mask_size}, reference={ref_size}")
    
    return spacing_match and origin_match and direction_match and size_match


def calculate_voxel_volume(ct_image: sitk.Image) -> float:
    """
    Calculate the volume of a single voxel in mm³.
    
    Args:
        ct_image: SimpleITK image
        
    Returns:
        float: Voxel volume in mm³
    """
    spacing = ct_image.GetSpacing()
    return spacing[0] * spacing[1] * spacing[2]


def calculate_structure_volume(mask: sitk.Image) -> float:
    """
    Calculate the volume of a structure in mm³.
    
    Args:
        mask: Binary SimpleITK mask
        
    Returns:
        float: Structure volume in mm³
    """
    voxel_volume = calculate_voxel_volume(mask)
    mask_array = sitk.GetArrayFromImage(mask)
    num_voxels = np.sum(mask_array > 0)
    return num_voxels * voxel_volume


def get_structure_bounding_box(mask: sitk.Image) -> Dict[str, Any]:
    """
    Get the bounding box of a structure in both voxel and physical coordinates.
    
    Args:
        mask: Binary SimpleITK mask
        
    Returns:
        Dictionary containing:
            - 'voxel_min': (x, y, z) minimum voxel indices
            - 'voxel_max': (x, y, z) maximum voxel indices
            - 'physical_min': (x, y, z) minimum physical coordinates in mm
            - 'physical_max': (x, y, z) maximum physical coordinates in mm
            - 'size_voxels': (x, y, z) size in voxels
            - 'size_mm': (x, y, z) size in mm
    """
    # Get mask array (Z, Y, X order in numpy)
    mask_array = sitk.GetArrayFromImage(mask)
    
    # Find non-zero voxels
    nonzero = np.argwhere(mask_array > 0)
    
    if len(nonzero) == 0:
        logger.warning("Empty mask - no bounding box")
        return None
    
    # Get min/max in array coordinates (Z, Y, X)
    min_zyx = nonzero.min(axis=0)
    max_zyx = nonzero.max(axis=0)
    
    # Convert to image coordinates (X, Y, Z)
    voxel_min = (int(min_zyx[2]), int(min_zyx[1]), int(min_zyx[0]))
    voxel_max = (int(max_zyx[2]), int(max_zyx[1]), int(max_zyx[0]))
    
    # Convert to physical coordinates
    physical_min = mask.TransformIndexToPhysicalPoint(voxel_min)
    physical_max = mask.TransformIndexToPhysicalPoint(voxel_max)
    
    # Calculate sizes
    size_voxels = tuple(vmax - vmin + 1 for vmin, vmax in zip(voxel_min, voxel_max))
    size_mm = tuple(pmax - pmin for pmin, pmax in zip(physical_min, physical_max))
    
    return {
        'voxel_min': voxel_min,
        'voxel_max': voxel_max,
        'physical_min': physical_min,
        'physical_max': physical_max,
        'size_voxels': size_voxels,
        'size_mm': size_mm
    }
