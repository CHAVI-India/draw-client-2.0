import numpy as np
import pandas as pd
import os
import pydicom
from scipy.spatial.distance import cdist, directed_hausdorff
from scipy.ndimage import distance_transform_edt, binary_fill_holes
from scipy.stats import kurtosis, skew
from shapely.geometry import Polygon
from skimage.draw import line
from sklearn.metrics.pairwise import cosine_similarity
import matplotlib.pyplot as plt


def dice_similarity(vol1, vol2):
    """
    Calculate Dice Similarity Coefficient between two binary volumes.
    """
    pass

def jaccard_similarity(vol1,vol2):
    """
    Calculate Jaccard Similarity Coefficient between two binary volumes.
    """
    pass

def hausdorff_distance_95(vol1, vol2):
    """
    Calculate Hausdorff Distance 95th percentile between two binary volumes.
    """
    pass

def mean_surface_distance(vol1, vol2):
    """
    Calculate Mean Surface Distance between two binary volumes.
    """
    pass

def added_path_length(vol1, vol2):
    """
    Calculate Added Path Length between two binary volumes.
    """
    pass

def mean_distance_to_conformity(vol1, vol2):
    """
    Calculate Mean Distance to Conformity between two binary volumes.
    """
    pass

def undercontouring_mean_distance_to_conformity(vol1, vol2):
    """
    Calculate Undercontouring Mean Distance to Conformity between two binary volumes.
    """
    pass

def overcontouring_mean_distance_to_conformity(vol1, vol2):
    """
    Calculate Overcontouring Mean Distance to Conformity between two binary volumes.
    """
    pass

def volume_overlap_error(vol1, vol2):
    """
    Calculate Volume Overlap Error between two binary volumes.
    """
    pass

def variation_of_information(vol1, vol2):
    """
    Calculate Variation of Information between two binary volumes.
    """
    pass

def cosine_similarity(vol1, vol2):
    """
    Calculate Cosine Similarity between two binary volumes.
    """
    pass

