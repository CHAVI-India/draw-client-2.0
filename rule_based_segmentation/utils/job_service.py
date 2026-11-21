"""Service layer for creating and running segmentation jobs."""

import logging
import os
import shutil
from typing import Optional, Tuple

from django.db import transaction
from django.utils import timezone

import pydicom

from dicom_handler.models import DICOMSeries, RTStructureFileImport
from dicom_handler.import_services.task2_reidentify_rtstruct import _extract_and_save_voi_data
from spatial_overlap.models import RTStructureSetFile

from ..models import RuleStep, SegmentationJob, SegmentationPipeline
from .engine import SegmentationEngine
from .job_workdir import JobWorkdir, get_job_workdir_base
from .rtstruct_io import (
    _backup_rtstruct,
    load_rtstruct_and_image,
    regenerate_instance_uids,
    save_rtstruct,
)

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
    destination_node=None,
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
        destination_node=destination_node,
        status="PENDING",
    )

    run_segmentation_job.delay(str(job.id))
    return job


def _fail_job(job: SegmentationJob, message: str) -> None:
    """Mark a job FAILED with a reason; used by every chain-step failure path."""
    job.status = "FAILED"
    job.completed_at = timezone.now()
    job.error_message = message
    job.save()


def _job_input_rtstruct_path(job: SegmentationJob) -> str:
    """Filesystem path of the RTStruct this job processes (input file)."""
    if job.input_type == "UPLOAD" and job.input_upload:
        return job.input_upload.rtstructure_file_path
    if job.input_type == "IMPORT" and job.input_import:
        return (
            job.input_import.reidentified_rt_structure_file_path
            or job.input_import.deidentified_rt_structure_file_path
        )
    raise ValueError(f"Job {job.id} has no input")


def prepare_job(job: SegmentationJob) -> None:
    """
    Chain step 0 — resolve inputs, create the work dir, cache the series,
    seed one PENDING RuleStep per rule.

    Every failure path marks the job FAILED before re-raising, so a failed
    prepare never leaves the job stuck in PENDING.
    """
    try:
        rtstruct_path, series_uid = get_rtstruct_path_and_series_uid(job)
    except Exception as e:
        logger.error(f"Job {job.id} input resolution failed: {e}", exc_info=True)
        _fail_job(job, f"Could not resolve job inputs: {e}")
        raise

    job.status = "STARTED"
    job.started_at = timezone.now()
    job.dicom_series = DICOMSeries.objects.filter(
        series_instance_uid=series_uid
    ).first()
    job.save()

    wd = JobWorkdir(job.id, base_dir=get_job_workdir_base())
    try:
        wd.create()
        job.backup_file_path = _backup_rtstruct(rtstruct_path)
        job.save()
        rtstruct, image, _series = load_rtstruct_and_image(
            rtstruct_path, series_uid, instances_dir=wd.images_dir
        )
        wd.save_image_cache(image)
        wd.write_initial_working(rtstruct)
    except Exception as e:
        logger.error(f"Job {job.id} preparation failed: {e}", exc_info=True)
        _fail_job(job, f"Could not prepare job inputs: {e}")
        raise

    for rule in job.pipeline.rules.all().order_by("order"):
        RuleStep.objects.create(
            job=job, rule=rule, order=rule.order, status="PENDING"
        )
    logger.info(f"Job {job.id} prepared: {job.pipeline.rules.count()} steps queued")


def _claim_step(job: SegmentationJob, order: int) -> RuleStep:
    """Claim a step for execution (RUNNING) in a short transaction.

    Returns None if the step already completed (duplicate delivery).
    The transaction commits before evaluation starts so no row lock is held
    during the (potentially long) rule computation.
    """
    with transaction.atomic():
        step = RuleStep.objects.select_for_update().get(job=job, order=order)
        if step.status == "SUCCESS":
            return None
        step.status = "RUNNING"
        step.started_at = timezone.now()
        step.error = None
        step.save()
    return step


def execute_rule_step(job: SegmentationJob, order: int) -> None:
    """
    Chain step N — evaluate one rule and commit its output to the work dir.

    Idempotent under redelivery: SUCCESS steps are skipped; steps whose disk
    commit already applied (worker died before the step UPDATE) complete
    without re-adding the ROI.
    """
    step = _claim_step(job, order)
    if step is None:
        logger.info(f"Job {job.id} step {order} already completed; skipping")
        return

    wd = JobWorkdir(job.id, base_dir=get_job_workdir_base())
    rule = step.rule

    try:
        engine = SegmentationEngine.from_workdir(wd.root)
    except Exception as e:
        logger.error(f"Job {job.id} step {order} failed to reload state: {e}", exc_info=True)
        step.status = "FAILED"
        step.error = str(e)
        step.completed_at = timezone.now()
        step.save()
        _fail_job(job, f"Could not reload job state for step {order}: {e}")
        raise

    if wd.rule_already_committed(engine.rtstruct, order):
        # Commit already applied (crash between disk commit and step update).
        manifest = wd.read_step_manifest(order)
        step.status = "SUCCESS"
        step.output_roi_name = manifest.get("output_name") if manifest else None
        step.completed_at = timezone.now()
        step.save()
        return

    try:
        output_name = engine.run_rule(rule)
        wd.commit_rule_output(engine.rtstruct, order, output_name)
    except Exception as e:
        logger.error(f"Job {job.id} rule {order} ({rule.name}) failed: {e}", exc_info=True)
        step.status = "FAILED"
        step.error = str(e)
        step.completed_at = timezone.now()
        step.save()
        _fail_job(job, f"Rule '{rule.name}' (step {order}) failed: {e}")
        raise

    step.status = "SUCCESS"
    step.output_roi_name = output_name
    step.completed_at = timezone.now()
    step.save()
    logger.info(f"Job {job.id} step {order} ({rule.name}) committed as '{output_name}'")


def finalize_job(job: SegmentationJob) -> dict:
    """
    Chain final step — write the processed RTStruct, sync DB records, push to
    the destination node, mark the job SUCCESS, and clean up the work dir.

    Idempotent: a redelivered finalize on an already-SUCCESS job is a no-op.
    """
    if job.status == "SUCCESS":
        logger.warning(f"Job {job.id} finalize is a duplicate; skipping")
        return job.result_summary or {}

    rtstruct_path = _job_input_rtstruct_path(job)
    wd = JobWorkdir(job.id, base_dir=get_job_workdir_base())

    try:
        engine = SegmentationEngine.from_workdir(wd.root)
        new_sop_uid, new_series_uid = regenerate_instance_uids(engine.rtstruct)
        save_rtstruct(engine.rtstruct, rtstruct_path)
    except Exception as e:
        logger.error(f"Job {job.id} finalization failed: {e}", exc_info=True)
        _fail_job(job, f"Finalization failed: {e}")
        raise

    summary = {
        "created_rois": [
            s.output_roi_name
            for s in job.steps.filter(
                status="SUCCESS", rule__output_action="CREATE_NEW"
            ).order_by("order")
            if s.output_roi_name
        ],
        "replaced_rois": [
            s.output_roi_name
            for s in job.steps.filter(
                status="SUCCESS", rule__output_action="REPLACE_EXISTING"
            ).order_by("order")
            if s.output_roi_name
        ],
        "sop_instance_uid": new_sop_uid,
        "series_instance_uid": new_series_uid,
    }

    job.status = "SUCCESS"
    job.completed_at = timezone.now()
    job.output_file_path = rtstruct_path
    job.result_summary = summary
    job.error_message = None
    job.save()

    # Same post-processing as the legacy single-task run.
    _sync_record_uids(job, rtstruct_path, summary)
    _mark_rtstruct_as_rule_based(job, rtstruct_path)
    _push_output_to_destination(job, rtstruct_path)
    wd.cleanup()

    logger.info(f"Segmentation job {job.id} completed successfully")
    return summary


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

        # The engine assigned a new SOPInstanceUID/SeriesInstanceUID to the
        # modified file; sync the database records so they match the file.
        _sync_record_uids(job, rtstruct_path, summary)

        # Mark the input RTStruct as having been processed by a rule-based
        # pipeline so it shows up clearly in the existing viewer/list.
        _mark_rtstruct_as_rule_based(job, rtstruct_path)

        # Optionally push the processed RTStruct back to a remote node.
        _push_output_to_destination(job, rtstruct_path)

        logger.info(f"Segmentation job {job.id} completed successfully")
    except Exception as e:
        logger.error(f"Segmentation job {job.id} failed: {e}", exc_info=True)
        job.status = "FAILED"
        job.completed_at = timezone.now()
        job.error_message = str(e)
        job.save()
        raise


def _sync_record_uids(
    job: SegmentationJob, rtstruct_path: str, summary: dict
) -> None:
    """Update the input record's UIDs after the engine regenerated them."""
    new_sop_uid = summary.get("sop_instance_uid")
    new_series_uid = summary.get("series_instance_uid")
    if not new_sop_uid:
        return

    if job.input_type == "UPLOAD" and job.input_upload:
        job.input_upload.sop_instance_uid = new_sop_uid
        if new_series_uid:
            job.input_upload.series_instance_uid = new_series_uid
        job.input_upload.save(
            update_fields=["sop_instance_uid", "series_instance_uid"]
        )
    elif job.input_type == "IMPORT" and job.input_import:
        rt_import = job.input_import
        rt_import.deidentified_sop_instance_uid = new_sop_uid
        rt_import.reidentified_rt_structure_file_sop_instance_uid = new_sop_uid
        if new_series_uid:
            rt_import.reidentified_rt_structure_file_series_instance_uid = new_series_uid
        rt_import.save()


def _push_output_to_destination(job: SegmentationJob, rtstruct_path: str) -> None:
    """C-STORE the processed RTStruct back to the configured remote node."""
    node = job.destination_node
    if not node:
        return

    try:
        from dicom_server.cstore_push_service import send_dicom_files_to_node

        results = send_dicom_files_to_node(node, [rtstruct_path])
        if results.get("success"):
            logger.info(
                f"Job {job.id}: pushed output RTStruct to node '{node.name}'"
            )
            job.result_summary = job.result_summary or {}
            job.result_summary["pushed_to_node"] = node.name
            job.save(update_fields=["result_summary"])
        else:
            logger.error(
                f"Job {job.id}: C-STORE push to '{node.name}' failed: {results.get('error_message')}"
            )
            job.result_summary = job.result_summary or {}
            job.result_summary["push_error"] = (
                results.get("error_message") or "C-STORE push failed"
            )
            job.save(update_fields=["result_summary"])
    except Exception as e:
        # Push failure should not fail the whole job - the output file is valid.
        logger.error(
            f"Job {job.id}: error pushing output to '{node.name}': {e}",
            exc_info=True,
        )
        job.result_summary = job.result_summary or {}
        job.result_summary["push_error"] = str(e)
        job.save(update_fields=["result_summary"])


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

    # For uploaded inputs, reuse an existing RTStructureFileImport pointing at
    # this file when present so reruns do not create duplicate list entries.
    rt_import = RTStructureFileImport.objects.filter(
        reidentified_rt_structure_file_path=rtstruct_path
    ).first() or RTStructureFileImport.objects.filter(
        deidentified_rt_structure_file_path=rtstruct_path
    ).first()

    if rt_import is None:
        rt_import = RTStructureFileImport.objects.create(
            deidentified_series_instance_uid=job.dicom_series,
            deidentified_rt_structure_file_path=rtstruct_path,
            reidentified_rt_structure_file_path=rtstruct_path,
            received_rt_structure_file_download_datetime=timezone.now(),
        )

    rt_import.server_segmentation_status = "RULE_BASED_COMPLETED"
    rt_import.reidentified_rt_structure_file_export_datetime = timezone.now()

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
    except Exception as e:
        logger.warning(f"Could not read RTStruct metadata for job {job.id}: {e}")

    rt_import.save()
    _extract_and_save_voi_data(rtstruct_path, rt_import)
