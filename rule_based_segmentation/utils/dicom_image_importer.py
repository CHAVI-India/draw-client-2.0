"""Import uploaded CT/MR/PT image series into the DICOM models."""

import logging
import os
import shutil
import tempfile
import zipfile
from datetime import date, datetime
from typing import List, Optional

import pydicom
from django.core.files.uploadedfile import UploadedFile

from dicom_handler.models import DICOMInstance, DICOMSeries, DICOMStudy, Patient, SystemConfiguration

logger = logging.getLogger(__name__)


ALLOWED_MODALITIES = {"CT", "MR", "PT"}


def import_uploaded_image_series(
    uploaded_files: List[UploadedFile],
    expected_series_instance_uid: Optional[str] = None,
) -> DICOMSeries:
    """
    Import an uploaded set of DICOM image files into the existing DICOM models.

    Args:
        uploaded_files: List of uploaded DICOM files, optionally including one zip file.
        expected_series_instance_uid: If provided, validate that the uploaded series matches.

    Returns:
        The created or updated DICOMSeries.

    Raises:
        ValueError: If validation fails or files cannot be read.
    """
    temp_dir = tempfile.mkdtemp(prefix="rbs_image_import_")
    try:
        _save_uploaded_files(uploaded_files, temp_dir)
        dicom_files = _collect_dicom_files(temp_dir)
        if not dicom_files:
            raise ValueError("No DICOM files found in upload.")

        datasets = _read_dicom_datasets(dicom_files)
        series_uid = _validate_single_series(datasets, expected_series_instance_uid)
        series_datasets = [ds for ds in datasets if str(ds.SeriesInstanceUID) == series_uid]

        patient = _get_or_create_patient(series_datasets[0])
        study = _get_or_create_study(patient, series_datasets[0])
        series = _get_or_create_series(study, series_datasets[0])

        target_dir = _get_series_target_directory(series_uid)
        _copy_datasets_to_directory(series_datasets, target_dir)

        _create_or_update_instances(series, series_datasets, target_dir)

        logger.info(
            f"Imported image series {series_uid} with {len(series_datasets)} instances into {target_dir}"
        )
        return series
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _save_uploaded_files(uploaded_files: List[UploadedFile], target_dir: str) -> None:
    for uploaded_file in uploaded_files:
        dest_path = os.path.join(target_dir, uploaded_file.name)
        with open(dest_path, "wb+") as dest:
            for chunk in uploaded_file.chunks():
                dest.write(chunk)

        if zipfile.is_zipfile(dest_path):
            with zipfile.ZipFile(dest_path, "r") as zf:
                zf.extractall(target_dir)
            os.remove(dest_path)


def _collect_dicom_files(directory: str) -> List[str]:
    dicom_files = []
    for root, _, files in os.walk(directory):
        for name in files:
            path = os.path.join(root, name)
            try:
                pydicom.dcmread(path, stop_before_pixels=True, force=True)
                dicom_files.append(path)
            except Exception:
                pass
    return dicom_files


def _read_dicom_datasets(file_paths: List[str]) -> List[pydicom.Dataset]:
    datasets = []
    for path in file_paths:
        try:
            ds = pydicom.dcmread(path, force=True)
        except Exception as e:
            logger.warning(f"Could not read DICOM file {path}: {e}")
            continue

        modality = str(getattr(ds, "Modality", "")).upper()
        if modality not in ALLOWED_MODALITIES:
            logger.warning(f"Skipping non-image modality {modality}: {path}")
            continue

        if not hasattr(ds, "SeriesInstanceUID"):
            logger.warning(f"Skipping file without SeriesInstanceUID: {path}")
            continue

        datasets.append(ds)
    return datasets


def _validate_single_series(
    datasets: List[pydicom.Dataset],
    expected_series_instance_uid: Optional[str],
) -> str:
    series_uids = {str(ds.SeriesInstanceUID) for ds in datasets}
    if not series_uids:
        raise ValueError("No valid image series found in upload.")

    if expected_series_instance_uid:
        expected = expected_series_instance_uid.strip()
        if expected not in series_uids:
            raise ValueError(
                f"Uploaded series UID {series_uids} does not match expected UID {expected}"
            )
        return expected

    if len(series_uids) > 1:
        raise ValueError(
            f"Upload contains multiple series: {series_uids}. Please upload only one series."
        )

    return series_uids.pop()


def _parse_dicom_date(value) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y%m%d").date()
    except ValueError:
        return None


def _get_or_create_patient(dataset: pydicom.Dataset) -> Patient:
    patient_id = str(getattr(dataset, "PatientID", "") or "").strip()
    patient_name = str(getattr(dataset, "PatientName", "") or "").strip()

    if patient_id:
        patient, _ = Patient.objects.get_or_create(
            patient_id=patient_id,
            defaults={"patient_name": patient_name},
        )
    else:
        patient = Patient.objects.create(patient_name=patient_name)

    if patient_name and not patient.patient_name:
        patient.patient_name = patient_name
        patient.save(update_fields=["patient_name"])

    return patient


def _get_or_create_study(patient: Patient, dataset: pydicom.Dataset) -> DICOMStudy:
    study_uid = str(getattr(dataset, "StudyInstanceUID", "") or "").strip()
    if not study_uid:
        raise ValueError("DICOM file is missing StudyInstanceUID")

    study, _ = DICOMStudy.objects.get_or_create(
        study_instance_uid=study_uid,
        defaults={
            "patient": patient,
            "study_date": _parse_dicom_date(getattr(dataset, "StudyDate", None)),
            "study_description": str(getattr(dataset, "StudyDescription", "") or ""),
            "study_modality": str(getattr(dataset, "Modality", "") or ""),
        },
    )
    return study


def _get_or_create_series(study: DICOMStudy, dataset: pydicom.Dataset) -> DICOMSeries:
    series_uid = str(getattr(dataset, "SeriesInstanceUID", "") or "").strip()
    if not series_uid:
        raise ValueError("DICOM file is missing SeriesInstanceUID")

    series, _ = DICOMSeries.objects.get_or_create(
        series_instance_uid=series_uid,
        defaults={
            "study": study,
            "series_description": str(getattr(dataset, "SeriesDescription", "") or ""),
            "series_date": _parse_dicom_date(getattr(dataset, "SeriesDate", None)),
            "frame_of_reference_uid": str(
                getattr(dataset, "FrameOfReferenceUID", "") or ""
            ),
        },
    )
    return series


def _get_series_target_directory(series_uid: str) -> str:
    config = SystemConfiguration.load()
    base_dir = config.folder_configuration or os.getcwd()
    target_dir = os.path.join(
        base_dir, "rule_based_segmentation", "image_series", series_uid
    )
    os.makedirs(target_dir, exist_ok=True)
    return target_dir


def _copy_datasets_to_directory(
    datasets: List[pydicom.Dataset],
    target_dir: str,
) -> None:
    for idx, ds in enumerate(datasets):
        sop_uid = str(getattr(ds, "SOPInstanceUID", "") or f"instance_{idx:04d}")
        target_path = os.path.join(target_dir, f"{sop_uid}.dcm")
        ds.save_as(target_path, enforce_file_format=True)


def _create_or_update_instances(
    series: DICOMSeries,
    datasets: List[pydicom.Dataset],
    target_dir: str,
) -> None:
    existing = {inst.sop_instance_uid: inst for inst in series.dicominstance_set.all()}

    for idx, ds in enumerate(datasets):
        sop_uid = str(getattr(ds, "SOPInstanceUID", "") or f"instance_{idx:04d}")
        target_path = os.path.join(target_dir, f"{sop_uid}.dcm")

        if sop_uid in existing:
            existing[sop_uid].instance_path = target_path
            existing[sop_uid].save(update_fields=["instance_path"])
        else:
            DICOMInstance.objects.create(
                series_instance_uid=series,
                sop_instance_uid=sop_uid,
                instance_path=target_path,
            )
