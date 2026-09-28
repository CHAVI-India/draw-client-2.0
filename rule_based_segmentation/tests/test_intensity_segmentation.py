"""Tests for intensity range segmentation."""

import numpy as np
import SimpleITK as sitk
from django.test import TestCase

from ..utils.intensity_segmentation import intensity_range_segmentation


class IntensitySegmentationTests(TestCase):
    def test_single_range_segmentation(self):
        image = sitk.Image([10, 10, 10], sitk.sitkInt16)
        arr = sitk.GetArrayFromImage(image)
        arr[2:5, 2:5, 2:5] = 50
        image = sitk.GetImageFromArray(arr)

        mask = intensity_range_segmentation(image, [{"min": 40, "max": 60}])
        mask_arr = sitk.GetArrayFromImage(mask)

        self.assertEqual(np.sum(mask_arr), 27)

    def test_multiple_ranges(self):
        image = sitk.Image([10, 10, 10], sitk.sitkInt16)
        arr = sitk.GetArrayFromImage(image)
        arr[2:5, 2:5, 2:5] = 50
        arr[6:8, 6:8, 6:8] = -500
        image = sitk.GetImageFromArray(arr)

        mask = intensity_range_segmentation(
            image,
            [{"min": 40, "max": 60}, {"min": -600, "max": -400}],
        )
        mask_arr = sitk.GetArrayFromImage(mask)

        self.assertEqual(np.sum(mask_arr), 27 + 8)

    def test_seed_mask_constraint(self):
        image = sitk.Image([10, 10, 10], sitk.sitkInt16)
        arr = sitk.GetArrayFromImage(image)
        arr[2:5, 2:5, 2:5] = 50
        arr[6:8, 6:8, 6:8] = 50
        image = sitk.GetImageFromArray(arr)

        seed_arr = np.zeros((10, 10, 10), dtype=np.uint8)
        seed_arr[2:5, 2:5, 2:5] = 1
        seed_mask = sitk.GetImageFromArray(seed_arr)

        mask = intensity_range_segmentation(
            image,
            [{"min": 40, "max": 60}],
            seed_mask=seed_mask,
        )
        mask_arr = sitk.GetArrayFromImage(mask)

        self.assertEqual(np.sum(mask_arr), 27)
