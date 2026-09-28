"""Service layer for creating and running segmentation jobs."""

import logging
import os
import shutil
from typing import Optional, Tuple

from django.utils import timezone

import pydicom

from dicom_handler.models import DICOMSeries, RTStructureFileImport
from dicom_handler.import_services.task2_reidentify_rtstruct import _extract_and_save_voi_data
from spatial_overlap.models import RTStructureSetFile

from ..models import SegmentationJob, SegmentationPipeline
from .engine import SegmentationEngine
from .rtstruct_io import _backup_rtstruct

logger = logging.getLogger(__name__)


class MissingImageSeriesError(Exception):
    """Raised when the referenced image series cannot be found."""

    pass


def get_rtstruct_path_and_series_uid(
    job: SegmentationJob,
) -> Tuple[str, str]:
    """
    Resolve the RTStruct file path and referenced series UID for a job.

    Returns:
        Tuple of (rtstruct_path, series_instance_uid).

    Raises:
        ValueError: If input is missing or invalid.
        MissingImageSeriesError: If the referenced series is not in the database.
    """
    rtstruct_path = None
    series_uid = None

    if job.input_type == "UPLOAD" and job.input_upload:
        rtstruct_path = job.input_upload.rtstructure_file_path
        series_uid = job.input_upload.referenced_series_instance_uid
    elif job.input_type == "IMPORT" and job.input_import:
        rtstruct_path = (
            job.input_import.reidentified_rt_structure_file_path
            or job.input_import.deidentified_rt_structure_file_path
        )
        series_uid = _get_referenced_series_uid_from_rtstruct(rtstruct_path)

    if not rtstruct_path or not os.path.exists(rtstruct_path):
        raise ValueError(f"RTStruct file not found: {rtstruct_path}")

    if not series_uid:
        raise ValueError("Could not determine referenced series UID from RTStruct")

    if not DICOMSeries.objects.filter(series_instance_uid=series_uid).exists():
        raise MissingImageSeriesError(
            f"Referenced image series {series_uid} is not available. Please upload it."
        )

    return rtstruct_path, series_uid


def _get_referenced_series_uid_from_rtstruct(rtstruct_path: str) -> Optional[str]:
    """Extract the referenced image series UID from an RTStruct DICOM file."""
    try:
        ds = pydicom.dcmread(rtstruct_path, stop_before_pixels=True, force=True)
    except Exception as e:
        logger.error(f"Failed to read RTStruct for series UID extraction: {e}")
        return None

    if not hasattr(ds, "ReferencedFrameOfReferenceSequence"):
        return None

    for ref_frame in ds.ReferencedFrameOfReferenceSequence:
        if not hasattr(ref_frame, "RTReferencedStudySequence"):
            continue
        for ref_study in ref_frame.RTReferencedStudySequence:
            if not hasattr(ref_study, "RTReferencedSeriesSequence"):
                continue
            for ref_series in ref_study.RTReferencedSeriesSequence:
                if hasattr(ref_series, "SeriesInstanceUID"):
                    return str(ref_series.SeriesInstanceUID)

    return None


def create_segmentation_job(
    pipeline: SegmentationPipeline,
    input_type: str,
    input_id: str,
    user,
) -> SegmentationJob:
    """Create a pending segmentation job and enqueue the Celery task."""
    from ..tasks import run_segmentation_job

    input_upload = None
    input_import = None

    if input_type == "UPLOAD":
        input_upload = RTStructureSetFile.objects.get(id=input_id)
    elif input_type == "IMPORT":
        input_import = RTStructureFileImport.objects.get(id=input_id)
    else:
        raise ValueError(f"Invalid input_type: {input_type}")

    job = SegmentationJob.objects.create(
        pipeline=pipeline,
        input_type=input_type,
        input_upload=input_upload,
        input_import=input_import,
        created_by=user,
        status="PENDING",
    )

    run_segmentation_job.delay(str(job.id))
    return job


def run_job(job: SegmentationJob) -> None:
    """Execute the segmentation job synchronously."""
    rtstruct_path, series_uid = get_rtstruct_path_and_series_uid(job)

    job.status = "STARTED"
    job.started_at = timezone.now()
    job.dicom_series = DICOMSeries.objects.filter(
        series_instance_uid=series_uid
    ).first()
    job.save()

    backup_path = _backup_rtstruct(rtstruct_path)
    job.backup_file_path = backup_path
    job.save()

    try:
        engine = SegmentationEngine(rtstruct_path, series_uid)

        def progress_callback(current: int, total: int, message: str) -> None:
            logger.info(f"Job {job.id}: {message}")

        summary = engine.run_pipeline(job.pipeline, progress_callback=progress_callback)

        job.status = "SUCCESS"
        job.completed_at = timezone.now()
        job.output_file_path = rtstruct_path
        job.result_summary = summary
        job.save()

        # Mark the input RTStruct as having been processed by a rule-based
        # pipeline so it shows up clearly in the existing viewer/list.
        _mark_rtstruct_as_rule_based(job, rtstruct_path)

        logger.info(f"Segmentation job {job.id} completed successfully")
    except Exception as e:
        logger.error(f"Segmentation job {job.id} failed: {e}", exc_info=True)
        job.status = "FAILED"
        job.completed_at = timezone.now()
        job.error_message = str(e)
        job.save()
        raise


def _mark_rtstruct_as_rule_based(job: SegmentationJob, rtstruct_path: str) -> None:
    """Mark the input RTStruct as having been processed by a rule-based pipeline."""
    # For imported inputs, update the existing RTStructureFileImport record.
    if job.input_import:
        rt_import = job.input_import
        rt_import.server_segmentation_status = "RULE_BASED_COMPLETED"
        rt_import.server_segmentation_updated_datetime = timezone.now()
        rt_import.save(update_fields=["server_segmentation_status", "server_segmentation_updated_datetime"])
        _extract_and_save_voi_data(rtstruct_path, rt_import)
        return

    # For uploaded inputs, create an RTStructureFileImport record so it
    # appears in the standard "View RT Structures" list.
    rt_import = RTStructureFileImport.objects.create(
        deidentified_series_instance_uid=job.dicom_series,
        deidentified_rt_structure_file_path=rtstruct_path,
        reidentified_rt_structure_file_path=rtstruct_path,
        server_segmentation_status="RULE_BASED_COMPLETED",
        received_rt_structure_file_download_datetime=timezone.now(),
        reidentified_rt_structure_file_export_datetime=timezone.now(),
    )

    try:
        ds = pydicom.dcmread(rtstruct_path, stop_before_pixels=True, force=True)
        if hasattr(ds, "SOPInstanceUID"):
            rt_import.deidentified_sop_instance_uid = str(ds.SOPInstanceUID)
            rt_import.reidentified_rt_structure_file_sop_instance_uid = str(ds.SOPInstanceUID)
        if hasattr(ds, "StudyInstanceUID"):
            rt_import.reidentified_rt_structure_file_study_instance_uid = str(ds.StudyInstanceUID)
        if hasattr(ds, "SeriesInstanceUID"):
            rt_import.reidentified_rt_structure_file_series_instance_uid = str(ds.SeriesInstanceUID)
        if hasattr(ds, "SOPClassUID"):
            rt_import.reidentified_rt_structure_file_sop_class_uid = str(ds.SOPClassUID)
        rt_import.save()
    except Exception as e:
        logger.warning(f"Could not read RTStruct metadata for job {job.id}: {e}")

    _extract_and_save_voi_data(rtstruct_path, rt_import)
