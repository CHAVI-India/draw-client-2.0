import numpy as np
import pandas as pd
import os
import pydicom
import SimpleITK as sitk
from scipy.spatial.distance import cdist, directed_hausdorff
from scipy.ndimage import distance_transform_edt, binary_fill_holes
from scipy.stats import kurtosis, skew
from shapely.geometry import Polygon
from skimage.draw import line
from sklearn.metrics.pairwise import cosine_similarity as sklearn_cosine_similarity
from sklearn.metrics import mutual_info_score

# Forumale for calculation of the metrics taken from : https://github.com/VendenIX/RTStructSegmentationAnalysis/blob/main/metrics.ipynb

def dice_similarity(volume1, volume2):
    """
    Calculate Dice Similarity Coefficient between two binary volumes.

    Args:
        volume1 (numpy.ndarray): First binary volume.
        volume2 (numpy.ndarray): Second binary volume.

    Returns:
        float: Dice Similarity Coefficient.
    """
    intersection = np.sum((volume1 > 0) & (volume2 > 0))
    size1 = np.sum(volume1 > 0)
    size2 = np.sum(volume2 > 0)
    
    if size1 + size2 == 0:
        return 1.0  # If two volumes are empty, the Dice similarity is 1
    return (2. * intersection) / (size1 + size2)

def jaccard_similarity(volume1,volume2):
    """
    Calculate Jaccard Similarity Coefficient between two binary volumes.

    Args:
        volume1 (numpy.ndarray): First binary volume.
        volume2 (numpy.ndarray): Second binary volume.

    Returns:
        float: Jaccard Similarity Coefficient.
    """
    intersection = np.sum((volume1 > 0) & (volume2 > 0))
    union = np.sum((volume1 > 0) | (volume2 > 0))
    
    if union == 0:
        return 1.0  # If two volumes are empty, the Jaccard similarity is 1
    
    return intersection / union

def mean_surface_distance(volume1, volume2):
    """
    Calculate Mean Surface Distance between two binary volumes.
    Uses distance transform for efficient computation (Plastimatch approach).

    Args:
        volume1 (numpy.ndarray): First binary volume.
        volume2 (numpy.ndarray): Second binary volume.

    Returns:
        float: Mean Surface Distance.
    """
    # Convert to binary
    vol1_binary = volume1 > 0
    vol2_binary = volume2 > 0
    
    # Check for empty volumes
    if not np.any(vol1_binary) or not np.any(vol2_binary):
        return np.inf
    
    # Compute distance transforms (distance from each voxel to nearest background voxel)
    # Invert to get distance to nearest foreground voxel
    dist1 = distance_transform_edt(~vol1_binary)
    dist2 = distance_transform_edt(~vol2_binary)
    
    # Get distances from surface of vol1 to vol2 and vice versa
    surface_distances_1_to_2 = dist2[vol1_binary]
    surface_distances_2_to_1 = dist1[vol2_binary]
    
    # Compute mean of both directions
    msd1 = np.mean(surface_distances_1_to_2)
    msd2 = np.mean(surface_distances_2_to_1)
    
    return (msd1 + msd2) / 2

def hausdorff_distance_95(volume1, volume2):
    """
    Calculate Hausdorff Distance 95th percentile between two binary volumes.
    Uses distance transform for efficient computation (Plastimatch approach).

    Args:
        volume1 (numpy.ndarray): First binary volume.
        volume2 (numpy.ndarray): Second binary volume.

    Returns:
        float: Hausdorff Distance 95th percentile. Maximum of the two HD returned
    """
    # Convert to binary
    vol1_binary = volume1 > 0
    vol2_binary = volume2 > 0
    
    # Check for empty volumes
    if not np.any(vol1_binary) or not np.any(vol2_binary):
        return np.inf
    
    # Compute distance transforms (distance from each voxel to nearest background voxel)
    # Invert to get distance to nearest foreground voxel
    dist1 = distance_transform_edt(~vol1_binary)
    dist2 = distance_transform_edt(~vol2_binary)
    
    # Get distances from surface of vol1 to vol2 and vice versa
    surface_distances_1_to_2 = dist2[vol1_binary]
    surface_distances_2_to_1 = dist1[vol2_binary]
    
    # Calculate the 95th percentile of the distances
    hd_95_1_to_2 = np.percentile(surface_distances_1_to_2, 95)
    hd_95_2_to_1 = np.percentile(surface_distances_2_to_1, 95)
    
    return max(hd_95_1_to_2, hd_95_2_to_1)

def volume_overlap_error(volume1, volume2):
    """
    Calculate Volume Overlap Error between two binary volumes.

    Args:
        volume1 (numpy.ndarray): First binary volume.
        volume2 (numpy.ndarray): Second binary volume.

    Returns:
        float: Volume Overlap Error.
    """
    intersection = np.sum((volume1 > 0) & (volume2 > 0))
    union = np.sum((volume1 > 0) | (volume2 > 0))
    
    if union == 0:
        return 0.0  # Return 0 if union value is 0 else divide by 0 error will occur
    
    return 1 - (intersection / union)

def variation_of_information(volume1, volume2):
    """
    Calculate Variation of Information between two binary volumes.

    Args:
        volume1 (numpy.ndarray): First binary volume.
        volume2 (numpy.ndarray): Second binary volume.

    Returns:
        float: Variation of Information.
    """

    volume1_flat = volume1.flatten()
    volume2_flat = volume2.flatten()
    
    h1 = mutual_info_score(volume1_flat, volume1_flat)
    h2 = mutual_info_score(volume2_flat, volume2_flat)
    mi = mutual_info_score(volume1_flat, volume2_flat)
    
    return h1 + h2 - 2 * mi

def cosine_similarity(volume1, volume2):
    """
    Calculate Cosine Similarity between two binary volumes.

    Args:
        volume1 (numpy.ndarray): First binary volume.
        volume2 (numpy.ndarray): Second binary volume.

    Returns:
        float: Cosine Similarity.
    """
    volume1_flat = volume1.flatten().reshape(1, -1)
    volume2_flat = volume2.flatten().reshape(1, -1)
    
    return sklearn_cosine_similarity(volume1_flat, volume2_flat)[0][0]


def surface_dsc(volume1, volume2, tau=3.0, spacing=(1.0, 1.0, 1.0)):
    """
    Calculate Surface Dice Similarity Coefficient between two binary volumes.
    Based on platipy implementation see here : https://github.com/pyplati/platipy/blob/main/platipy/label/visualise.py
    
    From: Nikolov S et al. Clinically Applicable Segmentation of Head and Neck Anatomy for
    Radiotherapy: Deep Learning Algorithm Development and Validation Study J Med Internet Res
    2021;23(7):e26151, DOI: 10.2196/26151

    Args:
        volume1 (numpy.ndarray): First binary volume (label_a).
        volume2 (numpy.ndarray): Second binary volume (label_b).
        tau (float): Accepted deviation between contours in mm. Default is 3.0 mm.
        spacing (tuple): Voxel spacing in (x, y, z) dimensions in mm. Default is (1.0, 1.0, 1.0).

    Returns:
        float: Surface Dice Similarity Coefficient (0 to 1, where 1 is perfect agreement).
    """
    # Convert numpy arrays to SimpleITK images
    vol1_binary = (volume1 > 0).astype(np.uint8)
    vol2_binary = (volume2 > 0).astype(np.uint8)
    
    # Check for empty volumes
    if not np.any(vol1_binary) and not np.any(vol2_binary):
        return 1.0  # Both empty, perfect agreement
    if not np.any(vol1_binary) or not np.any(vol2_binary):
        return 0.0  # One empty, one not, no agreement
    
    # Create SimpleITK images with proper spacing
    label_a = sitk.GetImageFromArray(vol1_binary)
    label_a.SetSpacing(spacing)
    
    label_b = sitk.GetImageFromArray(vol2_binary)
    label_b.SetSpacing(spacing)
    
    # Extract contours (surface) using BinaryContourImageFilter
    binary_contour_filter = sitk.BinaryContourImageFilter()
    binary_contour_filter.FullyConnectedOn()
    a_contour = binary_contour_filter.Execute(label_a)
    b_contour = binary_contour_filter.Execute(label_b)
    
    # Compute signed distance maps from each contour
    dist_to_a = sitk.SignedMaurerDistanceMap(
        a_contour, useImageSpacing=True, squaredDistance=False
    )
    
    dist_to_b = sitk.SignedMaurerDistanceMap(
        b_contour, useImageSpacing=True, squaredDistance=False
    )
    
    # Calculate intersection within tolerance tau
    # Points on b_contour that are within tau distance to a_contour
    b_intersection = sitk.GetArrayFromImage(b_contour * (dist_to_a <= tau)).sum()
    
    # Points on a_contour that are within tau distance to b_contour
    a_intersection = sitk.GetArrayFromImage(a_contour * (dist_to_b <= tau)).sum()
    
    # Total surface points
    surface_sum = (
        sitk.GetArrayFromImage(a_contour).sum()
        + sitk.GetArrayFromImage(b_contour).sum()
    )
    
    # Avoid division by zero
    if surface_sum == 0:
        return 0.0
    
    # Surface DSC formula
    return (b_intersection + a_intersection) / surface_sum

def added_path_length(volume1, volume2, distance_threshold_mm=3, spacing=(1.0, 1.0, 1.0)):
    """
    Calculate Added Path Length between two binary volumes.
    Measures the total contour length in the reference that is missing in the test segmentation.
    Based on Platipy implementation. See here : https://github.com/pyplati/platipy/blob/master/platipy/imaging/label/comparison.py

    Args:
        volume1 (numpy.ndarray): Reference (ground-truth) binary volume.
        volume2 (numpy.ndarray): Test binary volume.
        distance_threshold_mm (float): Distance threshold in mm. Distances under this threshold 
                                       will not contribute to the added path length. Default is 3mm.
        spacing (tuple): Voxel spacing in (x, y, z) dimensions in mm. Default is (1.0, 1.0, 1.0).

    Returns:
        float: Total (slice-wise) added path length in mm.
    """
    # Convert numpy arrays to SimpleITK images
    vol1_binary = (volume1 > 0).astype(np.uint8)
    vol2_binary = (volume2 > 0).astype(np.uint8)
    
    # Create SimpleITK images with proper spacing
    label_ref = sitk.GetImageFromArray(vol1_binary)
    label_ref.SetSpacing(spacing)
    
    label_test = sitk.GetImageFromArray(vol2_binary)
    label_test.SetSpacing(spacing)
    
    # Get number of slices (assuming z is the last dimension in numpy, first in SimpleITK)
    n_slices = label_ref.GetSize()[2]
    
    # Convert distance threshold from mm to voxel units
    distance_voxels = int(np.ceil(distance_threshold_mm / np.mean(spacing[:2])))
    
    added_path_length_list = []
    
    # Iterate over each slice
    for i in range(n_slices):
        # Check if both slices are empty
        ref_slice_array = sitk.GetArrayViewFromImage(label_ref)[i]
        test_slice_array = sitk.GetArrayViewFromImage(label_test)[i]
        
        if ref_slice_array.sum() + test_slice_array.sum() == 0:
            continue
        
        # Extract this slice
        label_ref_slice = label_ref[:, :, i]
        label_test_slice = label_test[:, :, i]
        
        # Extract contours (boundaries only)
        label_ref_contour = sitk.LabelContour(label_ref_slice)
        label_test_contour = sitk.LabelContour(label_test_slice)
        
        # Apply distance threshold by dilating the test contour
        if distance_threshold_mm > 0:
            kernel = [int(distance_voxels) for k in range(2)]
            label_test_contour = sitk.BinaryDilate(label_test_contour, kernel)
        
        # Mask out the locations in agreement
        # Keep only reference contour pixels that are NOT in the dilated test contour
        added_path = sitk.MaskNegated(label_ref_contour, label_test_contour)
        
        # Count the voxels on the added path
        added_path_length = sitk.GetArrayViewFromImage(added_path).sum()
        added_path_length_list.append(added_path_length)
    
    # Convert from voxels to mm using the average pixel spacing in x-y plane
    total_apl_mm = np.sum(added_path_length_list) * np.mean(spacing[:2])
    
    return total_apl_mm


def _calculate_axis_aligned_distance(test_coords, ref_volume, spacing):
    """
    Calculate minimum axis-aligned distance from test voxels to reference volume boundary.
    Based on espadon's mdcC algorithm.
    
    Args:
        test_coords (numpy.ndarray): (N, 3) array of test voxel coordinates [i, j, k].
        ref_volume (numpy.ndarray): 3D binary reference volume.
        spacing (tuple): Voxel spacing in (x, y, z) dimensions.
    
    Returns:
        numpy.ndarray: (N,) array of minimum distances for each test voxel.
    """
    if len(test_coords) == 0:
        return np.array([])
    
    distances = []
    shape = ref_volume.shape
    
    # Maximum possible distance (diagonal of entire volume)
    dist_max = np.sqrt(
        (shape[0] * spacing[0])**2 + 
        (shape[1] * spacing[1])**2 + 
        (shape[2] * spacing[2])**2
    )
    
    for i, j, k in test_coords:
        min_dist = dist_max
        
        # Search in +i direction (right along x-axis)
        for idx in range(i + 1, shape[0]):
            di = abs(idx - i) * spacing[0]
            if di > min_dist:
                break
            if ref_volume[idx, j, k] > 0:
                min_dist = di
                break
        
        # Search in -i direction (left along x-axis)
        for idx in range(i - 1, -1, -1):
            di = abs(idx - i) * spacing[0]
            if di > min_dist:
                break
            if ref_volume[idx, j, k] > 0:
                min_dist = di
                break
        
        # Search in +j direction (forward along y-axis)
        for idx in range(j + 1, shape[1]):
            dj = abs(idx - j) * spacing[1]
            if dj > min_dist:
                break
            if ref_volume[i, idx, k] > 0:
                min_dist = dj
                break
        
        # Search in -j direction (backward along y-axis)
        for idx in range(j - 1, -1, -1):
            dj = abs(idx - j) * spacing[1]
            if dj > min_dist:
                break
            if ref_volume[i, idx, k] > 0:
                min_dist = dj
                break
        
        # Search in +k direction (up along z-axis)
        for idx in range(k + 1, shape[2]):
            dk = abs(idx - k) * spacing[2]
            if dk > min_dist:
                break
            if ref_volume[i, j, idx] > 0:
                min_dist = dk
                break
        
        # Search in -k direction (down along z-axis)
        for idx in range(k - 1, -1, -1):
            dk = abs(idx - k) * spacing[2]
            if dk > min_dist:
                break
            if ref_volume[i, j, idx] > 0:
                min_dist = dk
                break
        
        # Store distance (NaN if no boundary found)
        distances.append(min_dist if min_dist != dist_max else np.nan)
    
    return np.array(distances)


def mean_distance_to_conformity(volume1, volume2, spacing=(1.0, 1.0, 1.0), return_detailed=False):
    """
    Calculate Mean Distance to Conformity between two binary volumes.
    Based on espadon R package implementation.
    
    MDC measures the average distance from voxels in the symmetric difference
    (XOR) of two volumes to the nearest boundary of the other volume.
    
    Args:
        volume1 (numpy.ndarray): Reference binary volume.
        volume2 (numpy.ndarray): Test binary volume.
        spacing (tuple): Voxel spacing in (x, y, z) dimensions in mm. Default is (1.0, 1.0, 1.0).
        return_detailed (bool): If True, returns detailed results with slice-wise data. Default is False.

    Returns:
        If return_detailed=False:
            float: Mean Distance to Conformity in mm.
        If return_detailed=True:
            dict: {
                'mdc': float,
                'under_mdc': float,
                'over_mdc': float,
                'slice_data': dict with slice indices as keys
            }
    """
    # Convert to binary
    vol1_binary = (volume1 > 0).astype(np.uint8)
    vol2_binary = (volume2 > 0).astype(np.uint8)
    
    # Undercontouring: voxels in reference but NOT in test
    under_region = vol1_binary & (~vol2_binary)
    under_coords = np.argwhere(under_region)
    
    # Overcontouring: voxels in test but NOT in reference
    over_region = vol2_binary & (~vol1_binary)
    over_coords = np.argwhere(over_region)
    
    # Calculate distances
    under_distances = np.array([])
    over_distances = np.array([])
    
    if len(under_coords) > 0:
        under_distances = _calculate_axis_aligned_distance(under_coords, vol2_binary, spacing)
    
    if len(over_coords) > 0:
        over_distances = _calculate_axis_aligned_distance(over_coords, vol1_binary, spacing)
    
    # Calculate mean values
    valid_under = under_distances[~np.isnan(under_distances)] if len(under_distances) > 0 else np.array([])
    valid_over = over_distances[~np.isnan(over_distances)] if len(over_distances) > 0 else np.array([])
    
    under_mdc = np.mean(valid_under) if len(valid_under) > 0 else 0.0
    over_mdc = np.mean(valid_over) if len(valid_over) > 0 else 0.0
    
    # Calculate overall MDC
    if len(valid_under) == 0 and len(valid_over) == 0:
        mdc = 0.0
    else:
        mdc = (under_mdc + over_mdc) / 2.0
    
    if not return_detailed:
        return mdc
    
    # Build slice-wise data
    slice_data = {}
    
    # Process undercontouring by slice
    if len(under_coords) > 0:
        for idx, (i, j, k) in enumerate(under_coords):
            slice_key = int(k)  # z-axis slice index
            if slice_key not in slice_data:
                slice_data[slice_key] = {
                    'under_distances': [],
                    'over_distances': []
                }
            
            dist = under_distances[idx]
            if not np.isnan(dist):
                slice_data[slice_key]['under_distances'].append(float(dist))
    
    # Process overcontouring by slice
    if len(over_coords) > 0:
        for idx, (i, j, k) in enumerate(over_coords):
            slice_key = int(k)  # z-axis slice index
            if slice_key not in slice_data:
                slice_data[slice_key] = {
                    'under_distances': [],
                    'over_distances': []
                }
            
            dist = over_distances[idx]
            if not np.isnan(dist):
                slice_data[slice_key]['over_distances'].append(float(dist))
    
    return {
        'mdc': float(mdc),
        'under_mdc': float(under_mdc),
        'over_mdc': float(over_mdc),
        'slice_data': slice_data
    }

def undercontouring_mean_distance_to_conformity(volume1, volume2, spacing=(1.0, 1.0, 1.0)):
    """
    Calculate Undercontouring Mean Distance to Conformity between two binary volumes.
    
    Undercontouring occurs where the reference volume extends beyond the test volume.
    This measures the average distance from voxels in (reference - test) to the test boundary.
    
    Args:
        volume1 (numpy.ndarray): Reference binary volume.
        volume2 (numpy.ndarray): Test binary volume.
        spacing (tuple): Voxel spacing in (x, y, z) dimensions in mm. Default is (1.0, 1.0, 1.0).

    Returns:
        float: Undercontouring Mean Distance to Conformity in mm.
    """
    result = mean_distance_to_conformity(volume1, volume2, spacing, return_detailed=True)
    return result['under_mdc']

def overcontouring_mean_distance_to_conformity(volume1, volume2, spacing=(1.0, 1.0, 1.0)):
    """
    Calculate Overcontouring Mean Distance to Conformity between two binary volumes.
    
    Overcontouring occurs where the test volume extends beyond the reference volume.
    This measures the average distance from voxels in (test - reference) to the reference boundary.
    
    Args:
        volume1 (numpy.ndarray): Reference binary volume.
        volume2 (numpy.ndarray): Test binary volume.
        spacing (tuple): Voxel spacing in (x, y, z) dimensions in mm. Default is (1.0, 1.0, 1.0).

    Returns:
        float: Overcontouring Mean Distance to Conformity in mm.
    """
    result = mean_distance_to_conformity(volume1, volume2, spacing, return_detailed=True)
    return result['over_mdc']
