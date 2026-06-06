"""
Advanced structure processing operations.

This module provides sophisticated operations for structure refinement:
- Surface smoothing
- Hole filling
- Connected component analysis and cleanup
- Gap closing and protrusion removal
- Morphological refinement
"""

import SimpleITK as sitk
import numpy as np
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


# ============================================================================
# SMOOTHING OPERATIONS
# ============================================================================

def smooth_structure(
    mask: sitk.Image,
    smoothing_mm: float = 1.0,
    iterations: int = 1
) -> sitk.Image:
    """
    Smooth structure surface using morphological operations.
    
    Applies morphological closing followed by opening to smooth the surface
    while preserving overall structure size and shape.
    
    Args:
        mask: SimpleITK binary mask
        smoothing_mm: Smoothing radius in millimeters
        iterations: Number of smoothing iterations
        
    Returns:
        sitk.Image: Smoothed mask
        
    Examples:
        >>> # Smooth jagged contours from autosegmentation
        >>> smoothed = smooth_structure(mask, smoothing_mm=2.0)
    """
    logger.info(f"Smoothing structure with {smoothing_mm}mm radius, {iterations} iterations")
    
    spacing = mask.GetSpacing()
    radius = [int(np.ceil(smoothing_mm / s)) for s in spacing]
    
    result = mask
    
    for i in range(iterations):
        # Morphological closing (dilate then erode) - fills small gaps
        dilate = sitk.BinaryDilateImageFilter()
        dilate.SetKernelRadius(radius)
        dilate.SetKernelType(sitk.sitkBall)
        dilate.SetForegroundValue(1)
        temp = dilate.Execute(result)
        
        erode = sitk.BinaryErodeImageFilter()
        erode.SetKernelRadius(radius)
        erode.SetKernelType(sitk.sitkBall)
        erode.SetForegroundValue(1)
        closed = erode.Execute(temp)
        
        # Morphological opening (erode then dilate) - removes small protrusions
        erode2 = sitk.BinaryErodeImageFilter()
        erode2.SetKernelRadius(radius)
        erode2.SetKernelType(sitk.sitkBall)
        erode2.SetForegroundValue(1)
        temp2 = erode2.Execute(closed)
        
        dilate2 = sitk.BinaryDilateImageFilter()
        dilate2.SetKernelRadius(radius)
        dilate2.SetKernelType(sitk.sitkBall)
        dilate2.SetForegroundValue(1)
        result = dilate2.Execute(temp2)
        
        logger.debug(f"Completed smoothing iteration {i+1}/{iterations}")
    
    logger.info("Structure smoothing completed")
    return result


def gaussian_smooth(
    mask: sitk.Image,
    sigma_mm: float = 1.0,
    threshold: float = 0.5
) -> sitk.Image:
    """
    Apply Gaussian smoothing to structure boundaries.
    
    Converts binary mask to distance map, applies Gaussian smoothing,
    then thresholds back to binary. Produces very smooth surfaces.
    
    Args:
        mask: SimpleITK binary mask
        sigma_mm: Gaussian sigma in millimeters
        threshold: Threshold for converting back to binary (0.0-1.0)
        
    Returns:
        sitk.Image: Smoothed binary mask
    """
    logger.info(f"Applying Gaussian smoothing with sigma={sigma_mm}mm")
    
    # Convert to float for smoothing
    mask_float = sitk.Cast(mask, sitk.sitkFloat32)
    
    # Apply Gaussian smoothing
    smoother = sitk.SmoothingRecursiveGaussianImageFilter()
    smoother.SetSigma(sigma_mm)
    smoothed = smoother.Execute(mask_float)
    
    # Threshold back to binary
    result = smoothed > threshold
    result = sitk.Cast(result, sitk.sitkUInt8)
    
    logger.info("Gaussian smoothing completed")
    return result


# ============================================================================
# HOLE FILLING
# ============================================================================

def fill_holes(mask: sitk.Image, fully_connected: bool = False) -> sitk.Image:
    """
    Fill internal holes in structure.
    
    Fills any enclosed cavities within the structure. Useful for cleaning up
    structures that should be solid but have internal gaps.
    
    Args:
        mask: SimpleITK binary mask
        fully_connected: If True, uses 26-connectivity (3D); if False, uses 6-connectivity
        
    Returns:
        sitk.Image: Mask with holes filled
        
    Examples:
        >>> # Fill internal cavities in tumor volume
        >>> solid_tumor = fill_holes(tumor_mask)
    """
    logger.info("Filling holes in structure")
    
    filler = sitk.BinaryFillholeImageFilter()
    filler.SetFullyConnected(fully_connected)
    filler.SetForegroundValue(1)
    result = filler.Execute(mask)
    
    logger.info("Hole filling completed")
    return result


# ============================================================================
# CONNECTED COMPONENT OPERATIONS
# ============================================================================

def remove_small_components(
    mask: sitk.Image,
    min_size_mm3: float
) -> sitk.Image:
    """
    Remove disconnected components smaller than threshold volume.
    
    Useful for cleaning up noise and small artifacts from segmentation.
    
    Args:
        mask: SimpleITK binary mask
        min_size_mm3: Minimum component size in cubic millimeters
        
    Returns:
        sitk.Image: Mask with small components removed
        
    Examples:
        >>> # Remove components smaller than 100 mm³
        >>> cleaned = remove_small_components(mask, min_size_mm3=100.0)
    """
    logger.info(f"Removing components smaller than {min_size_mm3} mm³")
    
    # Calculate minimum size in voxels
    spacing = mask.GetSpacing()
    voxel_volume = spacing[0] * spacing[1] * spacing[2]
    min_size_voxels = int(np.ceil(min_size_mm3 / voxel_volume))
    
    logger.debug(f"Minimum size: {min_size_voxels} voxels")
    
    # Label connected components
    connected = sitk.ConnectedComponentImageFilter()
    labeled = connected.Execute(mask)
    
    # Relabel and remove small components
    relabel = sitk.RelabelComponentImageFilter()
    relabel.SetMinimumObjectSize(min_size_voxels)
    relabeled = relabel.Execute(labeled)
    
    # Convert back to binary
    result = relabeled > 0
    result = sitk.Cast(result, sitk.sitkUInt8)
    
    num_removed = connected.GetObjectCount() - relabel.GetNumberOfObjects()
    logger.info(f"Removed {num_removed} small components")
    
    return result


def keep_largest_component(mask: sitk.Image) -> sitk.Image:
    """
    Keep only the largest connected component.
    
    Useful when you expect a single structure but have multiple disconnected pieces.
    
    Args:
        mask: SimpleITK binary mask
        
    Returns:
        sitk.Image: Mask containing only the largest component
        
    Examples:
        >>> # Keep only the main tumor, remove satellites
        >>> main_tumor = keep_largest_component(tumor_mask)
    """
    logger.info("Keeping only largest connected component")
    
    # Label connected components
    connected = sitk.ConnectedComponentImageFilter()
    labeled = connected.Execute(mask)
    
    # Relabel by size (largest gets label 1)
    relabel = sitk.RelabelComponentImageFilter()
    relabel.SetSortByObjectSize(True)
    relabeled = relabel.Execute(labeled)
    
    # Keep only label 1 (largest)
    result = relabeled == 1
    result = sitk.Cast(result, sitk.sitkUInt8)
    
    num_components = connected.GetObjectCount()
    logger.info(f"Kept largest component (removed {num_components - 1} others)")
    
    return result


def keep_n_largest_components(mask: sitk.Image, n: int = 1) -> sitk.Image:
    """
    Keep only the N largest connected components.
    
    Args:
        mask: SimpleITK binary mask
        n: Number of largest components to keep
        
    Returns:
        sitk.Image: Mask containing only the N largest components
    """
    logger.info(f"Keeping {n} largest connected components")
    
    # Label connected components
    connected = sitk.ConnectedComponentImageFilter()
    labeled = connected.Execute(mask)
    
    # Relabel by size
    relabel = sitk.RelabelComponentImageFilter()
    relabel.SetSortByObjectSize(True)
    relabeled = relabel.Execute(labeled)
    
    # Keep only labels 1 through n
    result = sitk.Image(mask.GetSize(), sitk.sitkUInt8)
    result.CopyInformation(mask)
    
    for i in range(1, n + 1):
        component = relabeled == i
        result = sitk.Or(result, component)
    
    result = sitk.Cast(result, sitk.sitkUInt8)
    
    num_components = connected.GetObjectCount()
    logger.info(f"Kept {min(n, num_components)} largest components")
    
    return result


# ============================================================================
# MORPHOLOGICAL REFINEMENT
# ============================================================================

def close_gaps(
    mask: sitk.Image,
    gap_size_mm: float = 2.0
) -> sitk.Image:
    """
    Close small gaps in structure (morphological closing).
    
    Useful for connecting nearby structures or filling small discontinuities.
    
    Args:
        mask: SimpleITK binary mask
        gap_size_mm: Maximum gap size to close in millimeters
        
    Returns:
        sitk.Image: Mask with gaps closed
        
    Examples:
        >>> # Connect nearby nodules
        >>> connected = close_gaps(nodules_mask, gap_size_mm=3.0)
    """
    logger.info(f"Closing gaps up to {gap_size_mm}mm")
    
    spacing = mask.GetSpacing()
    radius = [int(np.ceil(gap_size_mm / s)) for s in spacing]
    
    # Morphological closing (dilate then erode)
    dilate = sitk.BinaryDilateImageFilter()
    dilate.SetKernelRadius(radius)
    dilate.SetKernelType(sitk.sitkBall)
    dilate.SetForegroundValue(1)
    temp = dilate.Execute(mask)
    
    erode = sitk.BinaryErodeImageFilter()
    erode.SetKernelRadius(radius)
    erode.SetKernelType(sitk.sitkBall)
    erode.SetForegroundValue(1)
    result = erode.Execute(temp)
    
    logger.info("Gap closing completed")
    return result


def remove_protrusions(
    mask: sitk.Image,
    protrusion_size_mm: float = 2.0
) -> sitk.Image:
    """
    Remove small protrusions from structure (morphological opening).
    
    Useful for removing spikes and irregularities from structure boundaries.
    
    Args:
        mask: SimpleITK binary mask
        protrusion_size_mm: Maximum protrusion size to remove in millimeters
        
    Returns:
        sitk.Image: Mask with protrusions removed
        
    Examples:
        >>> # Remove spiky artifacts from segmentation
        >>> cleaned = remove_protrusions(mask, protrusion_size_mm=2.0)
    """
    logger.info(f"Removing protrusions up to {protrusion_size_mm}mm")
    
    spacing = mask.GetSpacing()
    radius = [int(np.ceil(protrusion_size_mm / s)) for s in spacing]
    
    # Morphological opening (erode then dilate)
    erode = sitk.BinaryErodeImageFilter()
    erode.SetKernelRadius(radius)
    erode.SetKernelType(sitk.sitkBall)
    erode.SetForegroundValue(1)
    temp = erode.Execute(mask)
    
    dilate = sitk.BinaryDilateImageFilter()
    dilate.SetKernelRadius(radius)
    dilate.SetKernelType(sitk.sitkBall)
    dilate.SetForegroundValue(1)
    result = dilate.Execute(temp)
    
    logger.info("Protrusion removal completed")
    return result


# ============================================================================
# ADVANCED REFINEMENT
# ============================================================================

def convex_hull(mask: sitk.Image) -> sitk.Image:
    """
    Create convex hull of structure.
    
    Generates the smallest convex shape that contains the entire structure.
    
    Args:
        mask: SimpleITK binary mask
        
    Returns:
        sitk.Image: Convex hull of the mask
    """
    logger.info("Computing convex hull")
    
    # SimpleITK doesn't have built-in convex hull, so we use a workaround
    # Convert to numpy for processing
    mask_array = sitk.GetArrayFromImage(mask)
    
    # For 3D convex hull, we can use slice-by-slice 2D convex hull
    # or use scipy/scikit-image if needed
    # For now, return the original mask with a warning
    logger.warning("Convex hull operation not yet fully implemented - returning original mask")
    
    return mask


def distance_map(mask: sitk.Image, signed: bool = True) -> sitk.Image:
    """
    Compute distance map from structure boundaries.
    
    Args:
        mask: SimpleITK binary mask
        signed: If True, returns signed distance (negative inside, positive outside)
                If False, returns unsigned distance (always positive)
        
    Returns:
        sitk.Image: Distance map (float image)
    """
    logger.info(f"Computing {'signed' if signed else 'unsigned'} distance map")
    
    if signed:
        distance_filter = sitk.SignedMaurerDistanceMapImageFilter()
        distance_filter.SetSquaredDistance(False)
        distance_filter.SetUseImageSpacing(True)
        result = distance_filter.Execute(mask)
    else:
        distance_filter = sitk.DanielssonDistanceMapImageFilter()
        distance_filter.SetUseImageSpacing(True)
        result = distance_filter.Execute(mask)
    
    logger.info("Distance map computed")
    return result
