"""
RT-Utils Patches
================
This module contains patches for the rt-utils library to handle edge cases
that are not properly handled in the upstream library.

These patches are applied at runtime to override the default rt-utils behavior.
"""

import cv2 as cv
import numpy as np
from pydicom.dataset import Dataset


def patched_get_slice_mask_from_slice_contour_data(
    series_slice: Dataset, slice_contour_data, transformation_matrix: np.ndarray
):
    """
    Patched version of rt_utils.image_helper.get_slice_mask_from_slice_contour_data
    
    This version handles degenerate contours (1-point and 2-point contours) gracefully:
    - Single point contours: Rendered as a small circle marker
    - Two point contours: Rendered as a line
    - Three or more points: Rendered as filled polygons (original behavior)
    
    This prevents OpenCV fillPoly assertion errors when encountering contours
    with fewer than 3 points, which are valid in DICOM RT Structure Sets but
    cannot form polygons.
    
    Args:
        series_slice: DICOM dataset for the current slice
        slice_contour_data: List of contour coordinate arrays
        transformation_matrix: 4x4 transformation matrix for patient-to-pixel conversion
        
    Returns:
        np.ndarray: Binary mask with contours rendered
    """
    from rt_utils.image_helper import (
        create_empty_slice_mask,
        apply_transformation_to_3d_points
    )
    
    # Go through all contours in a slice, create polygons in correct space and with a correct format 
    # and append to polygons array (appropriate for fillPoly) 
    slice_mask = create_empty_slice_mask(series_slice).astype(np.uint8)
    polygons = []
    
    for contour_coords in slice_contour_data:
        reshaped_contour_data = np.reshape(contour_coords, [len(contour_coords) // 3, 3])
        translated_contour_data = apply_transformation_to_3d_points(reshaped_contour_data, transformation_matrix)
        polygon = [np.around([translated_contour_data[:, :2]]).astype(np.int32)]
        polygon = np.array(polygon).squeeze()
        
        num_points = len(reshaped_contour_data)
        
        if num_points == 1:
            # Single point contour - draw a point marker
            point = tuple(polygon.flatten()[:2])
            cv.circle(slice_mask, point, radius=1, color=1, thickness=-1)
        elif num_points == 2:
            # Two point contour - draw a line
            pt1 = tuple(polygon[0])
            pt2 = tuple(polygon[1])
            cv.line(slice_mask, pt1, pt2, color=1, thickness=1)
        else:
            # Three or more points - use fillPoly
            polygons.append(polygon)
    
    # Fill all valid polygons (3+ points) at once
    if polygons:
        cv.fillPoly(img=slice_mask, pts=polygons, color=1)
    
    return slice_mask


def apply_rt_utils_patches():
    """
    Apply all rt-utils patches by monkey-patching the library functions.
    
    This should be called once at application startup, before any rt-utils
    functionality is used.
    """
    import rt_utils.image_helper
    
    # Patch the problematic function
    rt_utils.image_helper.get_slice_mask_from_slice_contour_data = (
        patched_get_slice_mask_from_slice_contour_data
    )
    
    return True
