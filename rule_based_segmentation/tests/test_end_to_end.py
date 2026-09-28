"""End-to-end segmentation tests using synthetic DICOM data."""

import os
import shutil
import tempfile
from unittest.mock import patch

import numpy as np
import pydicom
import SimpleITK as sitk
from django.test import TestCase
from rt_utils import RTStructBuilder

from dicom_handler.models import DICOMStudy

from ..utils.engine import SegmentationEngine
from ..utils.dicom_image_importer import import_uploaded_image_series
from ..utils.rtstruct_io import (
    add_mask_as_roi,
    load_rtstruct_and_image,
    load_roi_masks,
    save_rtstruct,
)
from .helpers import (
    create_dicom_models,
    create_pipeline_with_rules,
    create_synthetic_ct_series,
    create_synthetic_rtstruct,
    make_in_memory_file,
)


class EndToEndSegmentationTests(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="rbs_e2e_")
        self.series_uid = "1.2.3.4.5.6.7.8.9"
        self.study_uid = "1.2.3.4.5.6.7.8.10"

        self.ct_files = create_synthetic_ct_series(
            self.temp_dir,
            num_slices=10,
            rows=64,
            cols=64,
            spacing=(1.0, 1.0, 1.0),
            series_uid=self.series_uid,
            study_uid=self.study_uid,
        )
        self.series = create_dicom_models(
            self.ct_files,
            self.series_uid,
            self.study_uid,
        )

        # Create a 4x4x4 box ROI in the middle of the image.
        self.mask_array = np.zeros((10, 64, 64), dtype=bool)
        self.mask_array[3:7, 28:36, 28:36] = True
        self.rtstruct_path = os.path.join(self.temp_dir, "test_rtstruct.dcm")
        create_synthetic_rtstruct(
            self.rtstruct_path,
            self.ct_files,
            roi_name="Box",
            mask_array=self.mask_array,
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _engine(self):
        return SegmentationEngine(self.rtstruct_path, self.series_uid)

    def test_load_rtstruct_and_image(self):
        rtstruct, image, series = load_rtstruct_and_image(
            self.rtstruct_path, self.series_uid
        )
        self.assertIsNotNone(rtstruct)
        self.assertIsNotNone(image)
        self.assertEqual(series.series_instance_uid, self.series_uid)
        self.assertIn("Box", rtstruct.get_roi_names())

    def test_load_roi_masks(self):
        rtstruct, image, _ = load_rtstruct_and_image(
            self.rtstruct_path, self.series_uid
        )
        masks = load_roi_masks(rtstruct, image)
        self.assertIn("Box", masks)
        self.assertEqual(np.sum(sitk.GetArrayFromImage(masks["Box"])), np.sum(self.mask_array))

    def test_margin_expansion_changes_volume(self):
        pipeline = create_pipeline_with_rules(
            rules_data=[
                {
                    "rule_type": "MARGIN",
                    "name": "BoxExpanded",
                    "config": {
                        "variant": "UNIFORM",
                        "source": "Box",
                        "margin_mm": 2.0,
                        "kernel_type": "ball",
                    },
                }
            ]
        )
        engine = self._engine()
        summary = engine.run_pipeline(pipeline)

        self.assertEqual(summary["created_rois"], ["BoxExpanded"])
        rtstruct = RTStructBuilder.create_from(
            dicom_series_path=os.path.dirname(self.ct_files[0]),
            rt_struct_path=self.rtstruct_path,
        )
        self.assertIn("BoxExpanded", rtstruct.get_roi_names())

        expanded_mask = rtstruct.get_roi_mask_by_name("BoxExpanded")
        self.assertGreater(np.sum(expanded_mask), np.sum(self.mask_array))

    def test_margin_contraction_changes_volume(self):
        pipeline = create_pipeline_with_rules(
            rules_data=[
                {
                    "rule_type": "MARGIN",
                    "name": "BoxContracted",
                    "config": {
                        "variant": "UNIFORM",
                        "source": "Box",
                        "margin_mm": -1.0,
                        "kernel_type": "ball",
                    },
                }
            ]
        )
        engine = self._engine()
        summary = engine.run_pipeline(pipeline)

        self.assertEqual(summary["created_rois"], ["BoxContracted"])
        rtstruct = RTStructBuilder.create_from(
            dicom_series_path=os.path.dirname(self.ct_files[0]),
            rt_struct_path=self.rtstruct_path,
        )
        contracted_mask = rtstruct.get_roi_mask_by_name("BoxContracted")
        self.assertLess(np.sum(contracted_mask), np.sum(self.mask_array))

    def test_margin_on_empty_structure_raises_clear_error(self):
        # Add an empty ROI to the RTStruct.
        empty_mask = np.zeros((10, 64, 64), dtype=bool)
        rtstruct = RTStructBuilder.create_from(
            dicom_series_path=os.path.dirname(self.ct_files[0]),
            rt_struct_path=self.rtstruct_path,
        )
        add_mask_as_roi(
            rtstruct,
            sitk.GetImageFromArray(empty_mask.astype(np.uint8)),
            "EmptyROI",
            [128, 128, 128],
            replace_existing=False,
        )
        save_rtstruct(rtstruct, self.rtstruct_path)

        pipeline = create_pipeline_with_rules(
            rules_data=[
                {
                    "rule_type": "MARGIN",
                    "name": "ShouldFail",
                    "config": {
                        "variant": "UNIFORM",
                        "source": "EmptyROI",
                        "margin_mm": 2.0,
                        "kernel_type": "ball",
                    },
                }
            ]
        )
        engine = self._engine()
        from ..utils.expression_evaluator import RuleEvaluationError
        with self.assertRaises(RuleEvaluationError) as cm:
            engine.run_pipeline(pipeline)
        self.assertIn("empty", str(cm.exception).lower())

    def test_boolean_union_pipeline(self):
        # Add a second ROI shifted from the first.
        mask2 = np.zeros((10, 64, 64), dtype=bool)
        mask2[3:7, 32:40, 32:40] = True
        rtstruct = RTStructBuilder.create_from(
            dicom_series_path=os.path.dirname(self.ct_files[0]),
            rt_struct_path=self.rtstruct_path,
        )
        add_mask_as_roi(
            rtstruct,
            sitk.GetImageFromArray(mask2.astype(np.uint8)),
            "Box2",
            [0, 255, 0],
            replace_existing=False,
        )
        save_rtstruct(rtstruct, self.rtstruct_path)

        pipeline = create_pipeline_with_rules(
            rules_data=[
                {
                    "rule_type": "BOOLEAN",
                    "name": "UnionResult",
                    "config": {
                        "operation": "UNION",
                        "operands": [{"name": "Box"}, {"name": "Box2"}],
                    },
                }
            ]
        )
        engine = self._engine()
        summary = engine.run_pipeline(pipeline)

        self.assertEqual(summary["created_rois"], ["UnionResult"])
        rtstruct = RTStructBuilder.create_from(
            dicom_series_path=os.path.dirname(self.ct_files[0]),
            rt_struct_path=self.rtstruct_path,
        )
        union_mask = rtstruct.get_roi_mask_by_name("UnionResult")
        expected = np.logical_or(self.mask_array, mask2)
        self.assertEqual(np.sum(union_mask), np.sum(expected))

    def test_crop_pipeline(self):
        # Boundary is a larger box that only partially overlaps.
        boundary = np.zeros((10, 64, 64), dtype=bool)
        boundary[3:7, 28:34, 28:34] = True
        rtstruct = RTStructBuilder.create_from(
            dicom_series_path=os.path.dirname(self.ct_files[0]),
            rt_struct_path=self.rtstruct_path,
        )
        add_mask_as_roi(
            rtstruct,
            sitk.GetImageFromArray(boundary.astype(np.uint8)),
            "Boundary",
            [0, 0, 255],
            replace_existing=False,
        )
        save_rtstruct(rtstruct, self.rtstruct_path)

        pipeline = create_pipeline_with_rules(
            rules_data=[
                {
                    "rule_type": "CROP",
                    "name": "BoxCropped",
                    "config": {
                        "source": "Box",
                        "boundaries": ["Boundary"],
                    },
                }
            ]
        )
        engine = self._engine()
        summary = engine.run_pipeline(pipeline)

        self.assertEqual(summary["created_rois"], ["BoxCropped"])
        rtstruct = RTStructBuilder.create_from(
            dicom_series_path=os.path.dirname(self.ct_files[0]),
            rt_struct_path=self.rtstruct_path,
        )
        cropped_mask = rtstruct.get_roi_mask_by_name("BoxCropped")
        expected = np.logical_and(self.mask_array, boundary)
        self.assertEqual(np.sum(cropped_mask), np.sum(expected))

    def test_intensity_pipeline(self):
        # Modify the CT image so the box region has a distinct intensity.
        for i, path in enumerate(self.ct_files):
            ds = pydicom.dcmread(path)
            arr = ds.pixel_array.astype(np.int16)
            arr[self.mask_array[i]] = 100
            ds.PixelData = arr.tobytes()
            ds.save_as(path)

        pipeline = create_pipeline_with_rules(
            rules_data=[
                {
                    "rule_type": "INTENSITY",
                    "name": "IntensityROI",
                    "config": {
                        "seed_type": "IMAGE",
                        "ranges": [{"min": 90, "max": 110}],
                    },
                }
            ]
        )
        engine = self._engine()
        summary = engine.run_pipeline(pipeline)

        self.assertEqual(summary["created_rois"], ["IntensityROI"])
        rtstruct = RTStructBuilder.create_from(
            dicom_series_path=os.path.dirname(self.ct_files[0]),
            rt_struct_path=self.rtstruct_path,
        )
        intensity_mask = rtstruct.get_roi_mask_by_name("IntensityROI")
        self.assertGreater(np.sum(intensity_mask), 0)

    def test_cleanup_keep_largest(self):
        # Create a second small disconnected component in Box ROI.
        mask_with_noise = self.mask_array.copy()
        mask_with_noise[1, 10:12, 10:12] = True
        rtstruct = RTStructBuilder.create_from(
            dicom_series_path=os.path.dirname(self.ct_files[0]),
            rt_struct_path=self.rtstruct_path,
        )
        rtstruct = add_mask_as_roi(
            rtstruct,
            sitk.GetImageFromArray(mask_with_noise.astype(np.uint8)),
            "NoisyBox",
            [255, 255, 0],
            replace_existing=False,
        )
        save_rtstruct(rtstruct, self.rtstruct_path)

        pipeline = create_pipeline_with_rules(
            rules_data=[
                {
                    "rule_type": "CLEANUP",
                    "name": "BoxClean",
                    "config": {
                        "operation": "KEEP_LARGEST_COMPONENT",
                        "source": "NoisyBox",
                    },
                }
            ]
        )
        engine = self._engine()
        summary = engine.run_pipeline(pipeline)

        self.assertEqual(summary["created_rois"], ["BoxClean"])
        rtstruct = RTStructBuilder.create_from(
            dicom_series_path=os.path.dirname(self.ct_files[0]),
            rt_struct_path=self.rtstruct_path,
        )
        clean_mask = rtstruct.get_roi_mask_by_name("BoxClean")
        # Small component should be removed.
        self.assertLess(np.sum(clean_mask), np.sum(mask_with_noise))
        self.assertEqual(np.sum(clean_mask), np.sum(self.mask_array))

    def test_replace_existing_roi(self):
        pipeline = create_pipeline_with_rules(
            rules_data=[
                {
                    "rule_type": "MARGIN",
                    "name": "Box",
                    "output_action": "REPLACE_EXISTING",
                    "config": {
                        "variant": "UNIFORM",
                        "source": "Box",
                        "margin_mm": 3.0,
                        "kernel_type": "ball",
                    },
                }
            ]
        )
        engine = self._engine()
        summary = engine.run_pipeline(pipeline)

        self.assertEqual(summary["replaced_rois"], ["Box"])
        rtstruct = RTStructBuilder.create_from(
            dicom_series_path=os.path.dirname(self.ct_files[0]),
            rt_struct_path=self.rtstruct_path,
        )
        # Original Box should now be the expanded version.
        box_mask = rtstruct.get_roi_mask_by_name("Box")
        self.assertGreater(np.sum(box_mask), np.sum(self.mask_array))

    def test_duplicate_output_name_gets_suffix(self):
        pipeline = create_pipeline_with_rules(
            rules_data=[
                {
                    "rule_type": "MARGIN",
                    "name": "Box",
                    "config": {
                        "variant": "UNIFORM",
                        "source": "Box",
                        "margin_mm": 1.0,
                        "kernel_type": "ball",
                    },
                }
            ]
        )
        engine = self._engine()
        engine.run_pipeline(pipeline)

        rtstruct = RTStructBuilder.create_from(
            dicom_series_path=os.path.dirname(self.ct_files[0]),
            rt_struct_path=self.rtstruct_path,
        )
        roi_names = rtstruct.get_roi_names()
        self.assertIn("Box_1", roi_names)
        self.assertEqual(roi_names.count("Box"), 1)
        self.assertEqual(roi_names.count("Box_1"), 1)

    def test_missing_structure_raises_clear_error(self):
        pipeline = create_pipeline_with_rules(
            rules_data=[
                {
                    "rule_type": "MARGIN",
                    "name": "Missing",
                    "config": {
                        "variant": "UNIFORM",
                        "source": "DoesNotExist",
                        "margin_mm": 3.0,
                        "kernel_type": "ball",
                    },
                }
            ]
        )
        engine = self._engine()
        from ..utils.expression_evaluator import RuleEvaluationError

        with self.assertRaises(RuleEvaluationError):
            engine.run_pipeline(pipeline)


class DICOMImporterTests(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="rbs_import_")
        self.series_uid = "1.2.3.4.5.6.7.8.99"
        self.study_uid = "1.2.3.4.5.6.7.8.100"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_import_uploaded_image_series(self):
        ct_files = create_synthetic_ct_series(
            self.temp_dir,
            num_slices=5,
            series_uid=self.series_uid,
            study_uid=self.study_uid,
        )
        uploaded_files = [
            make_in_memory_file(os.path.basename(p), open(p, "rb").read())
            for p in ct_files
        ]

        import_target_dir = os.path.join(self.temp_dir, "imported")
        os.makedirs(import_target_dir, exist_ok=True)
        with patch(
            "rule_based_segmentation.utils.dicom_image_importer._get_series_target_directory",
            return_value=import_target_dir,
        ):
            series = import_uploaded_image_series(
                uploaded_files, expected_series_instance_uid=self.series_uid
            )

        self.assertEqual(series.series_instance_uid, self.series_uid)
        self.assertEqual(series.dicominstance_set.count(), 5)
        self.assertTrue(DICOMStudy.objects.filter(study_instance_uid=self.study_uid).exists())
