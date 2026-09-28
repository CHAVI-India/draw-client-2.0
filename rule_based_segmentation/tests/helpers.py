"""Helpers for rule_based_segmentation tests."""

import os
import tempfile
import uuid
from datetime import date
from io import BytesIO
from typing import List, Tuple

import numpy as np
import pydicom
import SimpleITK as sitk
from django.core.files.uploadedfile import InMemoryUploadedFile
from pydicom.uid import ExplicitVRLittleEndian, ImplicitVRLittleEndian, generate_uid
from rt_utils import RTStructBuilder

from dicom_handler.models import DICOMInstance, DICOMSeries, DICOMStudy, Patient
from rule_based_segmentation.models import (
    BooleanExpressionNode,
    CleanupRuleConfig,
    CropBoundary,
    CropRuleConfig,
    IntensityRange,
    IntensityRuleConfig,
    MarginRuleConfig,
    PipelineRule,
    SegmentationPipeline,
)


def create_box_mask(shape, start, end, spacing=(1.0, 1.0, 1.0)):
    """Create a SimpleITK binary box mask."""
    arr = np.zeros(shape, dtype=np.uint8)
    slices = tuple(slice(s, e) for s, e in zip(start, end))
    arr[slices] = 1
    mask = sitk.GetImageFromArray(arr)
    mask.SetSpacing(spacing)
    return mask


def create_sphere_mask(shape, center, radius, spacing=(1.0, 1.0, 1.0)):
    """Create a SimpleITK binary sphere mask."""
    grid = np.ogrid[tuple(slice(0, s) for s in shape)]
    dist_sq = sum(
        ((grid[i] - center[i]) * spacing[i]) ** 2 for i in range(len(shape))
    )
    arr = (dist_sq <= radius ** 2).astype(np.uint8)
    mask = sitk.GetImageFromArray(arr)
    mask.SetSpacing(spacing)
    return mask


def create_test_image(shape, spacing=(1.0, 1.0, 1.0)):
    """Create a blank SimpleITK image."""
    image = sitk.Image(shape, sitk.sitkInt16)
    image.SetSpacing(spacing)
    return image


def assert_mask_equal(mask1, mask2):
    """Assert two SimpleITK masks are equal."""
    arr1 = sitk.GetArrayFromImage(mask1).astype(bool)
    arr2 = sitk.GetArrayFromImage(mask2).astype(bool)
    return np.array_equal(arr1, arr2)


def create_synthetic_ct_series(
    temp_dir: str,
    num_slices: int = 10,
    rows: int = 64,
    cols: int = 64,
    spacing: Tuple[float, float, float] = (1.0, 1.0, 1.0),
    series_uid: str = None,
    study_uid: str = None,
    patient_id: str = "TESTPATIENT",
    patient_name: str = "Test^Patient",
) -> List[str]:
    """Create a minimal synthetic CT DICOM series on disk."""
    series_uid = series_uid or generate_uid()
    study_uid = study_uid or generate_uid()
    frame_uid = generate_uid()

    file_paths = []
    for i in range(num_slices):
        sop_uid = generate_uid()
        ds = pydicom.Dataset()
        ds.PatientName = patient_name
        ds.PatientID = patient_id
        ds.StudyInstanceUID = study_uid
        ds.StudyDate = "20240101"
        ds.StudyTime = "120000"
        ds.StudyDescription = "Synthetic Study"
        ds.StudyID = "1"
        ds.SeriesInstanceUID = series_uid
        ds.SeriesDate = "20240101"
        ds.SeriesTime = "120000"
        ds.SeriesDescription = "Synthetic Series"
        ds.SeriesNumber = "1"
        ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
        ds.SOPInstanceUID = sop_uid
        ds.Modality = "CT"
        ds.Rows = rows
        ds.Columns = cols
        ds.SliceThickness = spacing[2]
        ds.PixelSpacing = [spacing[0], spacing[1]]
        ds.ImagePositionPatient = [0.0, 0.0, i * spacing[2]]
        ds.ImageOrientationPatient = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]
        ds.FrameOfReferenceUID = frame_uid
        ds.InstanceNumber = i + 1
        ds.SliceLocation = i * spacing[2]
        ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = "MONOCHROME2"
        ds.BitsAllocated = 16
        ds.BitsStored = 16
        ds.PixelRepresentation = 1
        ds.PixelData = np.zeros((rows, cols), dtype=np.int16).tobytes()

        ds.file_meta = pydicom.dataset.FileMetaDataset()
        ds.file_meta.MediaStorageSOPClassUID = ds.SOPClassUID
        ds.file_meta.MediaStorageSOPInstanceUID = sop_uid
        ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        ds.is_little_endian = True
        ds.is_implicit_VR = False

        path = os.path.join(temp_dir, f"ct_{i:03d}.dcm")
        ds.save_as(path, enforce_file_format=True)
        file_paths.append(path)

    return file_paths


def create_synthetic_rtstruct(
    rtstruct_path: str,
    ct_file_paths: List[str],
    roi_name: str,
    mask_array: np.ndarray,
    color: List[int] = None,
) -> str:
    """Create a synthetic RTStruct from a CT series and a 3D mask.

    mask_array is expected in (Z, Y, X) order and is transposed to
    (X, Y, Z) for rt-utils.
    """
    if color is None:
        color = [255, 0, 0]

    # rt-utils expects mask shape (X, Y, Z) where Z is the slice dimension.
    rt_mask = mask_array.astype(bool)
    if rt_mask.ndim == 3:
        rt_mask = rt_mask.transpose(2, 1, 0)

    rtstruct = RTStructBuilder.create_new(os.path.dirname(ct_file_paths[0]))
    rtstruct.add_roi(mask=rt_mask, name=roi_name, color=color)
    rtstruct.save(rtstruct_path)
    return rtstruct_path


def create_dicom_models(
    ct_file_paths: List[str],
    series_uid: str,
    study_uid: str,
    patient_id: str = "TESTPATIENT",
    patient_name: str = "Test^Patient",
) -> DICOMSeries:
    """Create Patient/Study/Series/Instance records for a synthetic CT series."""
    patient, _ = Patient.objects.get_or_create(
        patient_id=patient_id,
        defaults={"patient_name": patient_name},
    )
    study, _ = DICOMStudy.objects.get_or_create(
        study_instance_uid=study_uid,
        defaults={
            "patient": patient,
            "study_date": date.today(),
            "study_description": "Synthetic CT",
            "study_modality": "CT",
        },
    )
    series, _ = DICOMSeries.objects.get_or_create(
        series_instance_uid=series_uid,
        defaults={
            "study": study,
            "series_description": "Synthetic CT Series",
            "frame_of_reference_uid": generate_uid(),
        },
    )

    existing = {inst.sop_instance_uid for inst in series.dicominstance_set.all()}
    for path in ct_file_paths:
        ds = pydicom.dcmread(path, stop_before_pixels=True)
        sop_uid = str(ds.SOPInstanceUID)
        if sop_uid in existing:
            continue
        DICOMInstance.objects.create(
            series_instance_uid=series,
            sop_instance_uid=sop_uid,
            instance_path=path,
        )

    return series


def create_pipeline_with_rules(user=None, name="Test Pipeline", rules_data=None):
    """Create a pipeline with rules from a Python data structure."""
    pipeline = SegmentationPipeline.objects.create(name=name, created_by=user)
    if not rules_data:
        return pipeline

    for idx, rule_data in enumerate(rules_data, start=1):
        rule = PipelineRule.objects.create(
            pipeline=pipeline,
            order=idx,
            rule_type=rule_data["rule_type"],
            name=rule_data["name"],
            output_action=rule_data.get("output_action", "CREATE_NEW"),
            output_color=rule_data.get("output_color", "255\\255\\0"),
            output_roi_type=rule_data.get("output_roi_type", "ORGAN"),
        )

        config = rule_data.get("config", {})
        if rule.rule_type == "BOOLEAN":
            _create_boolean_tree(rule, config)
        elif rule.rule_type == "INTENSITY":
            _create_intensity_config(rule, config)
        elif rule.rule_type == "MARGIN":
            _create_margin_config(rule, config)
        elif rule.rule_type == "CROP":
            _create_crop_config(rule, config)
        elif rule.rule_type == "CLEANUP":
            _create_cleanup_config(rule, config)

    return pipeline


def _create_boolean_tree(rule, config, parent=None):
    if config.get("operation"):
        node = BooleanExpressionNode.objects.create(
            pipeline_rule=rule,
            parent=parent,
            node_type="OPERATION",
            operation_type=config["operation"],
            order=parent.children.count() + 1 if parent else 1,
        )
        for child in config.get("operands", []):
            _create_boolean_tree(rule, child, parent=node)
    else:
        BooleanExpressionNode.objects.create(
            pipeline_rule=rule,
            parent=parent,
            node_type="ROI",
            roi_name=config["name"],
            order=parent.children.count() + 1 if parent else 1,
        )


def _create_intensity_config(rule, config):
    intensity = IntensityRuleConfig.objects.create(
        pipeline_rule=rule,
        seed_type=config.get("seed_type", "IMAGE"),
        seed_roi=config.get("seed_roi", ""),
        boundary_roi=config.get("boundary_roi", ""),
        modality_hint=config.get("modality_hint", ""),
    )
    for idx, r in enumerate(config.get("ranges", []), start=1):
        IntensityRange.objects.create(
            intensity_rule=intensity,
            min_value=r["min"],
            max_value=r["max"],
            order=idx,
        )


def _create_margin_config(rule, config):
    MarginRuleConfig.objects.create(
        pipeline_rule=rule,
        variant=config.get("variant", "UNIFORM"),
        source=config.get("source", ""),
        margin_mm=config.get("margin_mm"),
        margin_x_mm=config.get("margin_x_mm"),
        margin_y_mm=config.get("margin_y_mm"),
        margin_z_mm=config.get("margin_z_mm"),
        kernel_type=config.get("kernel_type", "ball"),
    )


def _create_crop_config(rule, config):
    crop = CropRuleConfig.objects.create(
        pipeline_rule=rule,
        source=config.get("source", ""),
    )
    for idx, boundary in enumerate(config.get("boundaries", []), start=1):
        CropBoundary.objects.create(
            crop_rule=crop,
            boundary_roi=boundary,
            order=idx,
        )


def _create_cleanup_config(rule, config):
    CleanupRuleConfig.objects.create(
        pipeline_rule=rule,
        operation=config.get("operation", ""),
        source=config.get("source", ""),
        smoothing_mm=config.get("smoothing_mm"),
        iterations=config.get("iterations"),
        min_size_mm3=config.get("min_size_mm3"),
        fully_connected=config.get("fully_connected"),
        sigma_mm=config.get("sigma_mm"),
        threshold=config.get("threshold"),
    )


def make_in_memory_file(name: str, content: bytes) -> InMemoryUploadedFile:
    """Create an InMemoryUploadedFile for testing file uploads."""
    from io import BytesIO

    return InMemoryUploadedFile(
        file=BytesIO(content),
        field_name="file",
        name=name,
        content_type="application/dicom",
        size=len(content),
        charset=None,
    )


def create_minimal_rtstruct_file(roi_names=None, sop_uid=None, colors=None) -> bytes:
    """Create a minimal RTStruct DICOM file with the given ROI names."""
    from pydicom.uid import ExplicitVRLittleEndian

    roi_names = roi_names or []
    colors = colors or []
    sop_uid = sop_uid or generate_uid()

    ds = pydicom.Dataset()
    ds.PatientName = "Test^Patient"
    ds.PatientID = "TESTPATIENT"
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.481.3"
    ds.SOPInstanceUID = sop_uid
    ds.Modality = "RTSTRUCT"
    ds.StructureSetLabel = "Test RTStruct"

    ds.StructureSetROISequence = pydicom.Sequence()
    ds.ROIContourSequence = pydicom.Sequence()
    ds.RTROIObservationsSequence = pydicom.Sequence()
    for idx, name in enumerate(roi_names, start=1):
        roi = pydicom.Dataset()
        roi.ROINumber = idx
        roi.ROIName = name
        roi.ReferencedFrameOfReferenceUID = generate_uid()
        ds.StructureSetROISequence.append(roi)

        color = colors[idx - 1] if idx - 1 < len(colors) else [255, 0, 0]
        contour = pydicom.Dataset()
        contour.ReferencedROINumber = idx
        contour.ROIDisplayColor = [int(c) for c in color]
        ds.ROIContourSequence.append(contour)

        obs = pydicom.Dataset()
        obs.ObservationNumber = idx
        obs.ReferencedROINumber = idx
        obs.RTROIInterpretedType = "ORGAN"
        ds.RTROIObservationsSequence.append(obs)

    ds.file_meta = pydicom.dataset.FileMetaDataset()
    ds.file_meta.MediaStorageSOPClassUID = ds.SOPClassUID
    ds.file_meta.MediaStorageSOPInstanceUID = sop_uid
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds.is_little_endian = True
    ds.is_implicit_VR = False

    buffer = BytesIO()
    ds.save_as(buffer, enforce_file_format=True)
    return buffer.getvalue()
