"""Tests for the Celery chain tasks (chain shape, wrappers, resume; reap tests land in Task 7)."""

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from ..models import RuleStep, SegmentationJob, SegmentationPipeline
from ..tasks import (
    REAP_PENDING_GRACE_SECONDS,
    REAP_RUNNING_GRACE_SECONDS,
    build_job_chain,
    finalize_job,
    prepare_job,
    reap_stuck_jobs,
    resume_job,
    run_rule_step,
)
from .helpers import create_pipeline_with_rules

User = get_user_model()

RULES = [
    {
        "rule_type": "MARGIN",
        "name": "PTV",
        "config": {"variant": "UNIFORM", "source": "Box", "margin_mm": 2.0},
    },
    {
        "rule_type": "CROP",
        "name": "Clipped",
        "config": {"source": "Box", "boundaries": ["Box"]},
    },
]


def make_job():
    user = User.objects.create_user(username="chainuser", password="x")
    pipeline = create_pipeline_with_rules(name="Chain", rules_data=RULES)
    return SegmentationJob.objects.create(
        pipeline=pipeline, input_type="UPLOAD", created_by=user, status="PENDING"
    )


class ChainShapeTests(TestCase):
    def test_chain_is_prepare_rules_finalize_in_order(self):
        job = make_job()
        sigs = build_job_chain(job).tasks  # Celery 5.6: constituents live in .tasks
        self.assertEqual(
            [s.name for s in sigs],
            [
                "rule_based_segmentation.prepare_job",
                "rule_based_segmentation.run_rule_step",
                "rule_based_segmentation.run_rule_step",
                "rule_based_segmentation.finalize_job",
            ],
        )
        rule_sigs = [s for s in sigs if s.name == "rule_based_segmentation.run_rule_step"]
        # job_id is NOT stored in non-head signatures: the previous task's
        # return value is prepended as the first positional argument.
        self.assertEqual([tuple(s.args) for s in rule_sigs], [(1,), (2,)])
        self.assertEqual(tuple(sigs[-1].args), ())

    def test_empty_pipeline_chain_is_prepare_finalize(self):
        user = User.objects.create_user(username="emptyuser", password="x")
        pipeline = SegmentationPipeline.objects.create(name="Empty")
        job = SegmentationJob.objects.create(
            pipeline=pipeline, input_type="UPLOAD", status="PENDING"
        )
        sigs = build_job_chain(job).tasks
        self.assertEqual(
            [s.name for s in sigs],
            [
                "rule_based_segmentation.prepare_job",
                "rule_based_segmentation.finalize_job",
            ],
        )


class TaskWrapperTests(TestCase):
    def test_missing_job_raises(self):
        with self.assertRaises(SegmentationJob.DoesNotExist):
            prepare_job("00000000-0000-0000-0000-000000000000")

    @patch("rule_based_segmentation.utils.job_service.prepare_job")
    def test_prepare_job_returns_job_id(self, mock_prep):
        job = make_job()
        self.assertEqual(prepare_job(str(job.id)), str(job.id))
        mock_prep.assert_called_once_with(job)

    @patch("rule_based_segmentation.utils.job_service.execute_rule_step")
    def test_run_rule_step_returns_job_id(self, mock_exec):
        job = make_job()
        self.assertEqual(run_rule_step(str(job.id), 1), str(job.id))
        mock_exec.assert_called_once_with(job, 1)

    @patch("rule_based_segmentation.utils.job_service.finalize_job")
    def test_finalize_job_returns_summary(self, mock_fin):
        mock_fin.return_value = {"created_rois": []}
        job = make_job()
        self.assertEqual(finalize_job(str(job.id)), {"created_rois": []})
        mock_fin.assert_called_once_with(job)


class ResumeJobTests(TestCase):
    def test_resume_enqueues_only_unfinished_steps(self):
        job = make_job()
        r1, r2 = list(job.pipeline.rules.all().order_by("order"))
        RuleStep.objects.create(
            job=job, rule=r1, order=1, status="SUCCESS", output_roi_name="PTV"
        )
        RuleStep.objects.create(job=job, rule=r2, order=2, status="FAILED", error="boom")

        with patch("rule_based_segmentation.tasks.chain") as mock_chain:
            mock_chain.return_value.apply_async = lambda: None
            resume_job(job)
        sigs = mock_chain.call_args[0]
        self.assertEqual(
            [s.name for s in sigs],
            [
                "rule_based_segmentation.run_rule_step",
                "rule_based_segmentation.finalize_job",
            ],
        )
        self.assertEqual(sigs[0].args, (str(job.id), 2))
        # the resumed head carries job_id explicitly; finalize receives it
        # from the previous task's return value
        self.assertEqual(tuple(sigs[1].args), ())

    def test_resume_without_steps_builds_full_chain(self):
        job = make_job()
        with patch("rule_based_segmentation.tasks.chain") as mock_chain:
            mock_chain.return_value.apply_async = lambda: None
            resume_job(job)
        sigs = mock_chain.call_args[0]
        self.assertEqual(len(sigs), 4)
        self.assertEqual(sigs[0].name, "rule_based_segmentation.prepare_job")
        self.assertEqual(tuple(sigs[1].args), (1,))
        self.assertEqual(tuple(sigs[3].args), ())

    def test_resume_all_steps_successful_enqueues_bare_finalize(self):
        job = make_job()
        r1, r2 = list(job.pipeline.rules.all().order_by("order"))
        RuleStep.objects.create(
            job=job, rule=r1, order=1, status="SUCCESS", output_roi_name="PTV"
        )
        RuleStep.objects.create(
            job=job, rule=r2, order=2, status="SUCCESS", output_roi_name="Clipped"
        )
        with patch("rule_based_segmentation.tasks.finalize_job") as mock_fin:
            mock_fin.s.return_value.apply_async = lambda *a, **k: None
            resume_job(job)
        mock_fin.s.assert_called_once_with(str(job.id))


class ChainDispatchTests(TestCase):
    """Reproduce Celery's real chain dispatch arg check.

    celery.app.trace._dispatch_callbacks_and_chain applies the next
    signature with the previous task's return value PREPENDED to that
    signature's stored args (canvas.Signature._merge). These tests push
    each chain signature through that exact code path against an in-memory
    broker (nothing reaches a real queue), so a signature that stores the
    injected job_id again fails with 'takes N positional arguments but
    N+1 were given' — the production chain-breaker of 2026-11-22.
    """

    _CELERY_CONF_KEYS = ("broker_url", "result_backend", "task_publish_retry")

    def _dispatch(self, sig, injected_args, remaining):
        from draw_client.celery import app as celery_app

        saved = {k: celery_app.conf.get(k) for k in self._CELERY_CONF_KEYS}
        celery_app.conf.update(
            broker_url="memory://",
            result_backend="disabled",
            task_publish_retry=False,
        )
        try:
            # Same call production makes
            # (celery/app/trace.py:_dispatch_callbacks_and_chain):
            # the previous task's return value is prepended to this
            # signature's stored args.
            sig.apply_async(injected_args, chain=remaining)
        finally:
            celery_app.conf.update(saved)

    def test_full_chain_dispatch_arg_counts(self):
        job = make_job()
        sigs = list(build_job_chain(job).tasks)
        job_id = str(job.id)
        for i, sig in enumerate(sigs):
            with self.subTest(i=i, task=sig.name):
                self._dispatch(sig, () if i == 0 else (job_id,), sigs[i + 1 :])

    def test_resume_chain_dispatch_arg_counts(self):
        job = make_job()
        r1, r2 = list(job.pipeline.rules.all().order_by("order"))
        RuleStep.objects.create(job=job, rule=r1, order=1, status="SUCCESS")
        RuleStep.objects.create(
            job=job, rule=r2, order=2, status="FAILED", error="boom"
        )
        captured = {}

        def capture(*sigs):
            captured["sigs"] = sigs
            raise _SkipApply  # the chain object is never used further

        with patch("rule_based_segmentation.tasks.chain", side_effect=capture):
            with self.assertRaises(_SkipApply):
                resume_job(job)
        sigs = captured["sigs"]
        job_id = str(job.id)
        for i, sig in enumerate(sigs):
            with self.subTest(i=i, task=sig.name):
                self._dispatch(sig, () if i == 0 else (job_id,), sigs[i + 1 :])


class _SkipApply(Exception):
    """Raised to skip the (irrelevant) chain.apply_async in capture tests."""


class ReapStuckJobsTests(TestCase):
    def _job_with_running_step(self, age_seconds):
        user = User.objects.create_user(username="reapuser", password="x")
        pipeline = create_pipeline_with_rules(name="Reap", rules_data=RULES)
        job = SegmentationJob.objects.create(
            pipeline=pipeline, input_type="UPLOAD", status="STARTED", created_by=user
        )
        rule = job.pipeline.rules.first()
        RuleStep.objects.create(
            job=job,
            rule=rule,
            order=1,
            status="RUNNING",
            started_at=timezone.now() - timedelta(seconds=age_seconds),
        )
        return job

    def test_old_running_step_marks_step_and_job_failed(self):
        job = self._job_with_running_step(REAP_RUNNING_GRACE_SECONDS + 60)
        reap_stuck_jobs()
        step = RuleStep.objects.get(job=job, order=1)
        self.assertEqual(step.status, "FAILED")
        self.assertIn("did not complete", step.error)
        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")
        self.assertIn("Step 1", job.error_message)

    def test_recent_running_step_untouched(self):
        job = self._job_with_running_step(60)
        reap_stuck_jobs()
        self.assertEqual(RuleStep.objects.get(job=job, order=1).status, "RUNNING")
        job.refresh_from_db()
        self.assertEqual(job.status, "STARTED")

    def test_old_pending_job_without_steps_failed(self):
        user = User.objects.create_user(username="reapuser2", password="x")
        pipeline = SegmentationPipeline.objects.create(name="P")
        job = SegmentationJob.objects.create(
            pipeline=pipeline, input_type="UPLOAD", status="PENDING", created_by=user
        )
        # backdate created_at (auto_now_add can't be set at create time)
        SegmentationJob.objects.filter(id=job.id).update(
            created_at=timezone.now() - timedelta(seconds=REAP_PENDING_GRACE_SECONDS + 60)
        )
        reap_stuck_jobs()
        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")
        self.assertIn("not started", job.error_message)

    def test_old_started_job_with_only_pending_steps_failed(self):
        user = User.objects.create_user(username="reapuser5", password="x")
        pipeline = create_pipeline_with_rules(name="Reap5", rules_data=RULES)
        job = SegmentationJob.objects.create(
            pipeline=pipeline,
            input_type="UPLOAD",
            status="STARTED",
            created_by=user,
            started_at=timezone.now() - timedelta(seconds=REAP_RUNNING_GRACE_SECONDS + 60),
        )
        rule = job.pipeline.rules.first()
        RuleStep.objects.create(job=job, rule=rule, order=1, status="PENDING")
        reap_stuck_jobs()
        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")
        self.assertIn("did not progress", job.error_message)

    def test_started_job_with_successful_step_not_reaped(self):
        user = User.objects.create_user(username="reapuser6", password="x")
        pipeline = create_pipeline_with_rules(name="Reap6", rules_data=RULES)
        job = SegmentationJob.objects.create(
            pipeline=pipeline,
            input_type="UPLOAD",
            status="STARTED",
            created_by=user,
            started_at=timezone.now() - timedelta(seconds=REAP_RUNNING_GRACE_SECONDS + 60),
        )
        r1, r2 = list(job.pipeline.rules.all().order_by("order"))
        RuleStep.objects.create(job=job, rule=r1, order=1, status="SUCCESS")
        RuleStep.objects.create(
            job=job, rule=r2, order=2, status="RUNNING", started_at=timezone.now()
        )
        reap_stuck_jobs()
        job.refresh_from_db()
        self.assertEqual(job.status, "STARTED")

    def test_old_failed_job_workdir_removed(self):
        import os
        import tempfile

        base = tempfile.mkdtemp(prefix="rbs_reap_")
        user = User.objects.create_user(username="reapuser3", password="x")
        pipeline = create_pipeline_with_rules(name="Reap2", rules_data=RULES)
        job = SegmentationJob.objects.create(
            pipeline=pipeline,
            input_type="UPLOAD",
            status="FAILED",
            created_by=user,
            completed_at=timezone.now() - timedelta(days=8),
        )
        workdir = os.path.join(base, str(job.id))
        os.makedirs(workdir)
        with patch(
            "rule_based_segmentation.utils.job_workdir.get_job_workdir_base",
            return_value=base,
        ):
            result = reap_stuck_jobs()
        self.assertEqual(result["cleaned_workdirs"], 1)
        self.assertFalse(os.path.exists(workdir))
