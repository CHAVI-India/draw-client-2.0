"""Celery tasks for rule-based segmentation (chain-based execution).

One job runs as a sequential chain:

    prepare_job -> run_rule_step(order=1..N) -> finalize_job

Every step reloads persisted state from the job work dir (see
utils/job_workdir.py), so a step that is redelivered after a worker crash
re-does at most one rule instead of the whole pipeline. Chain contract: each
step returns the job_id string, which Celery injects into the next task.
"""

import logging
import time

from celery import chain, shared_task
from django.db import connections

from .models import SegmentationJob
from .utils import job_service

logger = logging.getLogger(__name__)

# Per-step time limits (seconds). Soft limit raises SoftTimeLimitExceeded,
# which the service layer turns into a clean step/job FAILED; the hard limit
# SIGKILLs the worker, and acks_late redelivers the step (idempotent by design).
RULE_STEP_SOFT_TIME_LIMIT = 600
RULE_STEP_HARD_TIME_LIMIT = 900
PREPARE_SOFT_TIME_LIMIT = 900
PREPARE_HARD_TIME_LIMIT = 1200
FINALIZE_SOFT_TIME_LIMIT = 600
FINALIZE_HARD_TIME_LIMIT = 900


def _close_db_connections() -> None:
    """Close real DB connections after a task (long-lived worker hygiene).

    Skipped while a connection is inside an atomic block — e.g. under Django
    test cases, where closing would poison the test transaction.
    """
    for alias in connections:
        conn = connections[alias]
        if conn.connection is not None and not conn.in_atomic_block:
            conn.close()


def _get_job(job_id: str) -> SegmentationJob:
    try:
        return SegmentationJob.objects.get(id=job_id)
    except SegmentationJob.DoesNotExist:
        logger.error(f"SegmentationJob {job_id} not found")
        raise


def build_job_chain(job: SegmentationJob):
    """Build the prepare -> rules -> finalize chain for a (new) job."""
    job_id = str(job.id)
    rule_sigs = [
        run_rule_step.s(job_id, rule.order)
        for rule in job.pipeline.rules.all().order_by("order")
    ]
    return chain(prepare_job.s(job_id), *rule_sigs, finalize_job.s(job_id))


def resume_job(job: SegmentationJob) -> None:
    """Re-enqueue the remaining chain steps for a job (retry after failure).

    Steps already SUCCESS are skipped; PENDING/RUNNING/FAILED steps (in
    order) are enqueued, followed by finalize. A job that never reached
    prepare (no steps) gets the full chain.
    """
    job_id = str(job.id)
    steps = list(job.steps.select_related("rule").order_by("order"))
    if not steps:
        build_job_chain(job).apply_async()
        return
    remaining = [
        run_rule_step.s(job_id, s.order) for s in steps if s.status != "SUCCESS"
    ]
    chain(*remaining, finalize_job.s(job_id)).apply_async()


@shared_task(
    name="rule_based_segmentation.prepare_job",
    soft_time_limit=PREPARE_SOFT_TIME_LIMIT,
    time_limit=PREPARE_HARD_TIME_LIMIT,
)
def prepare_job(job_id: str) -> str:
    try:
        job = _get_job(job_id)
        job_service.prepare_job(job)
        return job_id
    finally:
        _close_db_connections()


@shared_task(
    name="rule_based_segmentation.run_rule_step",
    soft_time_limit=RULE_STEP_SOFT_TIME_LIMIT,
    time_limit=RULE_STEP_HARD_TIME_LIMIT,
)
def run_rule_step(job_id: str, order: int) -> str:
    try:
        job = _get_job(job_id)
        job_service.execute_rule_step(job, order)
        return job_id
    finally:
        _close_db_connections()


@shared_task(
    name="rule_based_segmentation.finalize_job",
    soft_time_limit=FINALIZE_SOFT_TIME_LIMIT,
    time_limit=FINALIZE_HARD_TIME_LIMIT,
)
def finalize_job(job_id: str) -> dict:
    try:
        job = _get_job(job_id)
        return job_service.finalize_job(job)
    finally:
        _close_db_connections()


def _wait_for(query_fn, timeout_seconds: int = 120, interval: float = 2.0):
    """Poll query_fn until it returns a truthy value or the timeout expires."""
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        result = query_fn()
        if result:
            return result
        time.sleep(interval)
        # Release the DB connection while we sleep. The image-series wait runs
        # up to 600s; holding one idle Postgres connection per polling worker
        # for that long is a large share of max_connections under load. The
        # next query_fn() transparently opens a fresh connection.
        connections.close_all()
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
