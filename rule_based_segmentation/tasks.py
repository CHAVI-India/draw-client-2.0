"""Celery tasks for rule-based segmentation."""

import logging
import time

from celery import shared_task

from .models import SegmentationJob
from .utils.job_service import run_job

logger = logging.getLogger(__name__)


@shared_task(bind=True, name="rule_based_segmentation.run_segmentation_job")
def run_segmentation_job(self, job_id: str) -> dict:
    """
    Celery task to run a segmentation job.

    Args:
        job_id: UUID string of the SegmentationJob.

    Returns:
        Dictionary with job status and summary.
    """
    try:
        job = SegmentationJob.objects.get(id=job_id)
    except SegmentationJob.DoesNotExist:
        logger.error(f"SegmentationJob {job_id} not found")
        return {"status": "FAILED", "error": f"Job {job_id} not found"}

    logger.info(f"Starting segmentation job {job_id}")
    run_job(job)

    return {
        "status": job.status,
        "job_id": job_id,
        "summary": job.result_summary,
        "error": job.error_message,
    }


def _wait_for(query_fn, timeout_seconds: int = 120, interval: float = 2.0):
    """Poll query_fn until it returns a truthy value or the timeout expires."""
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        result = query_fn()
        if result:
            return result
        time.sleep(interval)
    return None


@shared_task(bind=True, name="rule_based_segmentation.retrieve_rtstruct_for_pipeline")
def retrieve_rtstruct_for_pipeline(
    self,
    remote_node_id: int,
    study_uid: str,
    rtstruct_series_uid: str,
    pipeline_id: str,
    user_id: int,
    image_series_uid: str = "",
) -> dict:
    """
    Retrieve an RTStruct (and its referenced image series) from a remote DICOM
    node via C-MOVE or C-GET, then create a segmentation job.

    The processed RTStruct is pushed back to the same node on completion.
    """
    import os
    from django.contrib.auth import get_user_model

    from dicom_handler.models import DICOMSeries
    from dicom_server.models import RemoteDicomNode
    from dicom_server.query_retrieve_service import get_qr_service_instance
    from spatial_overlap.models import RTStructureSetFile

    from .models import SegmentationPipeline
    from .utils.job_service import create_segmentation_job

    def progress(step: str, extra: dict | None = None):
        meta = {"step": step}
        if extra:
            meta.update(extra)
        self.update_state(state="PROGRESS", meta=meta)

    try:
        node = RemoteDicomNode.objects.get(pk=remote_node_id)
        pipeline = SegmentationPipeline.objects.get(pk=pipeline_id)
        user = get_user_model().objects.get(pk=user_id)
        qr_service = get_qr_service_instance()

        def do_retrieve(study, series):
            if node.supports_c_move:
                return qr_service.retrieve_move(node, study, series_uid=series, user=user)
            if node.supports_c_get:
                return qr_service.retrieve_get(node, study, series_uid=series, user=user)
            raise ValueError(f"Node '{node.name}' supports neither C-MOVE nor C-GET")

        # 1. Retrieve the RTStruct series (or wait for an existing record).
        rtstruct_record = RTStructureSetFile.objects.filter(
            series_instance_uid=rtstruct_series_uid
        ).first()
        if not rtstruct_record:
            progress("retrieving_rtstruct")
            do_retrieve(study_uid, rtstruct_series_uid)
            rtstruct_record = _wait_for(
                lambda: RTStructureSetFile.objects.filter(
                    series_instance_uid=rtstruct_series_uid
                ).first()
            )
        if not rtstruct_record:
            raise RuntimeError(
                "Retrieve finished but the RTStruct file was not received "
                "by the local storage SCP. Check the DICOM server logs."
            )

        # 2. Determine the referenced image series and retrieve if missing.
        referenced_uid = (
            image_series_uid or rtstruct_record.referenced_series_instance_uid
        )
        if not referenced_uid:
            raise RuntimeError(
                "Could not determine the image series referenced by the RTStruct"
            )

        def series_ready():
            series = DICOMSeries.objects.filter(
                series_instance_uid=referenced_uid
            ).first()
            if not series:
                return None
            for inst in series.dicominstance_set.all():
                if not inst.instance_path or not os.path.exists(inst.instance_path):
                    return None
            return series

        series = series_ready()
        if not series:
            progress("retrieving_image_series", {"series_uid": referenced_uid})
            do_retrieve(study_uid, referenced_uid)
            series = _wait_for(series_ready, timeout_seconds=600, interval=5.0)
        if not series:
            raise RuntimeError(
                f"Image series {referenced_uid} was not received. "
                "Retrieve it manually or check the remote node."
            )

        # 3. Create the job; the output is pushed back to the source node.
        progress("creating_job")
        job = create_segmentation_job(
            pipeline,
            "UPLOAD",
            str(rtstruct_record.id),
            user,
            destination_node=node,
        )
        return {"status": "SUCCESS", "job_id": str(job.id)}

    except Exception as e:
        logger.error(f"retrieve_rtstruct_for_pipeline failed: {e}", exc_info=True)
        return {"status": "FAILED", "error": str(e)}
