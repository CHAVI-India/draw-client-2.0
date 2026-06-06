"""
Core structure operations using SimpleITK.

This module provides fundamental operations for structure manipulation:
- Margin operations (expansion/contraction)
- Boolean operations (union, intersection, subtraction)
- Cropping and boundary operations

All operations work in physical space (millimeters) rather than voxel space,
ensuring consistent results regardless of image resolution.
"""

import SimpleITK as sitk
import numpy as np
import logging
from typing import Union, List, Tuple, Optional

logger = logging.getLogger(__name__)


# ============================================================================
# MARGIN OPERATIONS
# ============================================================================

def apply_uniform_margin(
    mask: sitk.Image,
    margin_mm: float,
    kernel_type: str = "ball"
) -> sitk.Image:
    """
    Apply uniform margin (positive = expansion, negative = contraction).
    
    This operation expands or contracts a structure by a specified distance
    in millimeters, uniformly in all directions.
    
    Args:
        mask: SimpleITK binary mask
        margin_mm: Margin in millimeters
                  - Positive values: expansion (dilation)
                  - Negative values: contraction (erosion)
                  - Zero: returns original mask
        kernel_type: Structuring element shape
                    - "ball": Spherical (isotropic, most common)
                    - "box": Rectangular (anisotropic)
                    - "cross": Cross-shaped
        
    Returns:
        sitk.Image: Modified mask with applied margin
        
    Examples:
        >>> # Expand CTV by 5mm to create PTV
        >>> ptv_mask = apply_uniform_margin(ctv_mask, margin_mm=5.0)
        
        >>> # Contract structure by 3mm
        >>> contracted = apply_uniform_margin(mask, margin_mm=-3.0)
    """
    if margin_mm == 0:
        logger.debug("Zero margin requested, returning original mask")
        return mask
    
    # Calculate kernel radius in voxels for each dimension
    spacing = mask.GetSpacing()
    radius = [int(np.ceil(abs(margin_mm) / s)) for s in spacing]
    
    logger.debug(f"Applying {margin_mm}mm margin with radius {radius} voxels")
    
    # Select kernel type
    kernel_map = {
        "ball": sitk.sitkBall,
        "box": sitk.sitkBox,
        "cross": sitk.sitkCross
    }
    kernel = kernel_map.get(kernel_type.lower(), sitk.sitkBall)
    
    if margin_mm > 0:
        # Expansion (dilation)
        dilate = sitk.BinaryDilateImageFilter()
        dilate.SetKernelRadius(radius)
        dilate.SetKernelType(kernel)
        dilate.SetForegroundValue(1)
        result = dilate.Execute(mask)
        logger.info(f"Applied {margin_mm}mm expansion")
        
    else:
        # Contraction (erosion)
        erode = sitk.BinaryErodeImageFilter()
        erode.SetKernelRadius(radius)
        erode.SetKernelType(kernel)
        erode.SetForegroundValue(1)
        result = erode.Execute(mask)
        logger.info(f"Applied {abs(margin_mm)}mm contraction")
    
    return result


def apply_anisotropic_margin(
    mask: sitk.Image,
    margin_x_mm: float,
    margin_y_mm: float,
    margin_z_mm: float
) -> sitk.Image:
    """
    Apply different margins in X, Y, Z directions.
    
    Useful for directional expansions where different margins are needed
    in different anatomical directions.
    
    Args:
        mask: SimpleITK binary mask
        margin_x_mm: Margin in X direction (left-right) in mm
        margin_y_mm: Margin in Y direction (anterior-posterior) in mm
        margin_z_mm: Margin in Z direction (superior-inferior) in mm
        
    Returns:
        sitk.Image: Modified mask with anisotropic margins
        
    Examples:
        >>> # Expand 5mm laterally, 3mm AP, 2mm SI
        >>> expanded = apply_anisotropic_margin(mask, 5.0, 3.0, 2.0)
    """
    spacing = mask.GetSpacing()
    
    # Calculate radius for each dimension
    radius = [
        int(np.ceil(abs(margin_x_mm) / spacing[0])),
        int(np.ceil(abs(margin_y_mm) / spacing[1])),
        int(np.ceil(abs(margin_z_mm) / spacing[2]))
    ]
    
    logger.debug(f"Applying anisotropic margin: X={margin_x_mm}mm, Y={margin_y_mm}mm, Z={margin_z_mm}mm")
    logger.debug(f"Radius in voxels: {radius}")
    
    # Check if all margins are positive (expansion) or negative (contraction)
    all_positive = all(m >= 0 for m in [margin_x_mm, margin_y_mm, margin_z_mm])
    all_negative = all(m <= 0 for m in [margin_x_mm, margin_y_mm, margin_z_mm])
    
    if all_positive:
        # Pure expansion
        dilate = sitk.BinaryDilateImageFilter()
        dilate.SetKernelRadius(radius)
        dilate.SetForegroundValue(1)
        result = dilate.Execute(mask)
        logger.info(f"Applied anisotropic expansion")
        
    elif all_negative:
        # Pure contraction
        erode = sitk.BinaryErodeImageFilter()
        erode.SetKernelRadius(radius)
        erode.SetForegroundValue(1)
        result = erode.Execute(mask)
        logger.info(f"Applied anisotropic contraction")
        
    else:
        # Mixed - need to apply separately per axis
        logger.warning("Mixed positive/negative margins - applying sequentially per axis")
        result = mask
        
        # Apply X margin
        if margin_x_mm != 0:
            radius_x = [radius[0], 0, 0]
            if margin_x_mm > 0:
                dilate = sitk.BinaryDilateImageFilter()
                dilate.SetKernelRadius(radius_x)
                dilate.SetForegroundValue(1)
                result = dilate.Execute(result)
            else:
                erode = sitk.BinaryErodeImageFilter()
                erode.SetKernelRadius(radius_x)
                erode.SetForegroundValue(1)
                result = erode.Execute(result)
        
        # Apply Y margin
        if margin_y_mm != 0:
            radius_y = [0, radius[1], 0]
            if margin_y_mm > 0:
                dilate = sitk.BinaryDilateImageFilter()
                dilate.SetKernelRadius(radius_y)
                dilate.SetForegroundValue(1)
                result = dilate.Execute(result)
            else:
                erode = sitk.BinaryErodeImageFilter()
                erode.SetKernelRadius(radius_y)
                erode.SetForegroundValue(1)
                result = erode.Execute(result)
        
        # Apply Z margin
        if margin_z_mm != 0:
            radius_z = [0, 0, radius[2]]
            if margin_z_mm > 0:
                dilate = sitk.BinaryDilateImageFilter()
                dilate.SetKernelRadius(radius_z)
                dilate.SetForegroundValue(1)
                result = dilate.Execute(result)
            else:
                erode = sitk.BinaryErodeImageFilter()
                erode.SetKernelRadius(radius_z)
                erode.SetForegroundValue(1)
                result = erode.Execute(result)
    
    return result


# ============================================================================
# BOOLEAN OPERATIONS
# ============================================================================

def boolean_union(mask1: sitk.Image, mask2: sitk.Image) -> sitk.Image:
    """
    Combine two structures (OR operation).
    
    Creates a structure that includes all voxels that are in either mask1 OR mask2.
    
    Args:
        mask1: First SimpleITK binary mask
        mask2: Second SimpleITK binary mask
        
    Returns:
        sitk.Image: Union of both masks
        
    Examples:
        >>> # Combine left and right parotid into single structure
        >>> both_parotids = boolean_union(left_parotid, right_parotid)
    """
    logger.debug("Performing boolean union (OR)")
    result = sitk.Or(mask1, mask2)
    logger.info("Boolean union completed")
    return result


def boolean_intersection(mask1: sitk.Image, mask2: sitk.Image) -> sitk.Image:
    """
    Keep only overlapping region (AND operation).
    
    Creates a structure that includes only voxels that are in BOTH mask1 AND mask2.
    
    Args:
        mask1: First SimpleITK binary mask
        mask2: Second SimpleITK binary mask
        
    Returns:
        sitk.Image: Intersection of both masks
        
    Examples:
        >>> # Find overlap between PTV and organ at risk
        >>> overlap = boolean_intersection(ptv_mask, oar_mask)
    """
    logger.debug("Performing boolean intersection (AND)")
    result = sitk.And(mask1, mask2)
    logger.info("Boolean intersection completed")
    return result


def boolean_subtraction(mask1: sitk.Image, mask2: sitk.Image) -> sitk.Image:
    """
    Remove mask2 from mask1 (mask1 AND NOT mask2).
    
    Creates a structure that includes voxels in mask1 but NOT in mask2.
    
    Args:
        mask1: SimpleITK binary mask to subtract from
        mask2: SimpleITK binary mask to subtract
        
    Returns:
        sitk.Image: mask1 with mask2 removed
        
    Examples:
        >>> # Create PTV minus spinal cord
        >>> ptv_safe = boolean_subtraction(ptv_mask, spinal_cord_mask)
    """
    logger.debug("Performing boolean subtraction (AND NOT)")
    result = sitk.And(mask1, sitk.Not(mask2))
    logger.info("Boolean subtraction completed")
    return result


def boolean_xor(mask1: sitk.Image, mask2: sitk.Image) -> sitk.Image:
    """
    Symmetric difference (regions in either mask but not both).
    
    Creates a structure that includes voxels that are in mask1 OR mask2,
    but NOT in both (exclusive OR).
    
    Args:
        mask1: First SimpleITK binary mask
        mask2: Second SimpleITK binary mask
        
    Returns:
        sitk.Image: Symmetric difference of both masks
    """
    logger.debug("Performing boolean XOR")
    result = sitk.Xor(mask1, mask2)
    logger.info("Boolean XOR completed")
    return result


def crop_to_boundary(
    mask_to_crop: sitk.Image,
    boundary_mask: sitk.Image
) -> sitk.Image:
    """
    Crop mask_to_crop to stay within boundary_mask.
    
    This is semantically equivalent to intersection, but named to clarify
    the intent of constraining one structure to another's boundaries.
    
    Args:
        mask_to_crop: SimpleITK binary mask to be cropped
        boundary_mask: SimpleITK binary mask defining the boundary
        
    Returns:
        sitk.Image: Cropped mask
        
    Examples:
        >>> # Ensure PTV stays within body contour
        >>> ptv_cropped = crop_to_boundary(ptv_mask, body_mask)
        
        >>> # Limit expansion to specific region
        >>> limited = crop_to_boundary(expanded_mask, region_of_interest)
    """
    logger.debug("Cropping structure to boundary")
    result = sitk.And(mask_to_crop, boundary_mask)
    logger.info("Cropping completed")
    return result


# ============================================================================
# COMBINED OPERATIONS
# ============================================================================

def expand_and_crop(
    mask: sitk.Image,
    expansion_mm: float,
    boundary_mask: sitk.Image,
    kernel_type: str = "ball"
) -> sitk.Image:
    """
    Expand a structure and then crop to a boundary in one operation.
    
    Common workflow: expand a target volume but ensure it stays within
    the body contour or other anatomical boundary.
    
    Args:
        mask: SimpleITK binary mask to expand
        expansion_mm: Expansion margin in millimeters
        boundary_mask: SimpleITK binary mask defining the boundary
        kernel_type: Structuring element shape
        
    Returns:
        sitk.Image: Expanded and cropped mask
        
    Examples:
        >>> # Create PTV with 5mm margin, limited to body
        >>> ptv = expand_and_crop(ctv_mask, 5.0, body_mask)
    """
    logger.info(f"Expanding by {expansion_mm}mm and cropping to boundary")
    
    # Expand
    expanded = apply_uniform_margin(mask, expansion_mm, kernel_type)
    
    # Crop to boundary
    result = crop_to_boundary(expanded, boundary_mask)
    
    logger.info("Expand and crop completed")
    return result


def subtract_with_margin(
    mask1: sitk.Image,
    mask2: sitk.Image,
    margin_mm: float
) -> sitk.Image:
    """
    Subtract mask2 from mask1, with an additional margin around mask2.
    
    Useful for creating avoidance structures with safety margins.
    
    Args:
        mask1: SimpleITK binary mask to subtract from
        mask2: SimpleITK binary mask to subtract (will be expanded first)
        margin_mm: Additional margin around mask2 before subtraction
        
    Returns:
        sitk.Image: mask1 with expanded mask2 removed
        
    Examples:
        >>> # Create PTV avoiding spinal cord with 3mm margin
        >>> ptv_safe = subtract_with_margin(ptv_mask, cord_mask, margin_mm=3.0)
    """
    logger.info(f"Subtracting with {margin_mm}mm margin")
    
    # Expand mask2
    expanded_mask2 = apply_uniform_margin(mask2, margin_mm)
    
    # Subtract
    result = boolean_subtraction(mask1, expanded_mask2)
    
    logger.info("Subtraction with margin completed")
    return result
