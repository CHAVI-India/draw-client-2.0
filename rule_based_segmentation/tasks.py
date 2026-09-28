"""Celery tasks for rule-based segmentation."""

import logging

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
