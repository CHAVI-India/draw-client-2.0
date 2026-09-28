"""Intensity-range based segmentation utilities."""

import logging
from typing import Dict, List, Optional

import numpy as np
import SimpleITK as sitk

logger = logging.getLogger(__name__)


def intensity_range_segmentation(
    image: sitk.Image,
    ranges: List[Dict[str, float]],
    seed_mask: Optional[sitk.Image] = None,
    boundary_mask: Optional[sitk.Image] = None,
) -> sitk.Image:
    """
    Generate a binary mask from voxels whose intensity falls inside any of the given ranges.

    Args:
        image: Reference CT/MR/PT image (SimpleITK).
        ranges: List of intensity ranges, each with 'min' and 'max' keys.
        seed_mask: Optional binary mask to restrict the search region.
        boundary_mask: Optional binary mask to further constrain the result.

    Returns:
        SimpleITK binary mask with the same geometry as image.
    """
    image_array = sitk.GetArrayFromImage(image)

    combined_mask = np.zeros(image_array.shape, dtype=bool)
    for r in ranges:
        min_value = r["min"]
        max_value = r["max"]
        combined_mask |= (image_array >= min_value) & (image_array <= max_value)

    if seed_mask is not None:
        seed_array = sitk.GetArrayFromImage(seed_mask).astype(bool)
        if seed_array.shape != combined_mask.shape:
            raise ValueError(
                f"Seed mask shape {seed_array.shape} does not match image shape {combined_mask.shape}"
            )
        combined_mask &= seed_array

    if boundary_mask is not None:
        boundary_array = sitk.GetArrayFromImage(boundary_mask).astype(bool)
        if boundary_array.shape != combined_mask.shape:
            raise ValueError(
                f"Boundary mask shape {boundary_array.shape} does not match image shape {combined_mask.shape}"
            )
        combined_mask &= boundary_array

    result_array = combined_mask.astype(np.uint8)
    result = sitk.GetImageFromArray(result_array)
    result.CopyInformation(image)
    return result
