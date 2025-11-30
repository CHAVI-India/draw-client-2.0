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





def mean_distance_to_conformity(volume1, volume2):
    """
    Calculate Mean Distance to Conformity between two binary volumes.
    """
    pass

def undercontouring_mean_distance_to_conformity(volume1, volume2):
    """
    Calculate Undercontouring Mean Distance to Conformity between two binary volumes.
    """
    pass

def overcontouring_mean_distance_to_conformity(volume1, volume2):
    """
    Calculate Overcontouring Mean Distance to Conformity between two binary volumes.
    """
    pass

def surface_dsc(volume1, volume2, threshold = 0.3):
    """
    Calculate Surface Dice Similarity Coefficient between two binary volumes.

    Args:
        volume1 (numpy.ndarray): First binary volume.
        volume2 (numpy.ndarray): Second binary volume.
        threshold (float): Threshold value for surface distance. Default is 3 mm

    Returns:
        float: Surface Dice Similarity Coefficient.
    """
    pass

def added_path_length(volume1, volume2, distance_threshold_mm=3, spacing=(1.0, 1.0, 1.0)):
    """
    Calculate Added Path Length between two binary volumes.
    Measures the total contour length in the reference that is missing in the test segmentation.
    Based on Platipy implementation.

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