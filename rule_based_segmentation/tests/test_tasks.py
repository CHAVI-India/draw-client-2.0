"""Tests for the Celery chain tasks (chain shape, wrappers, resume; reap tests land in Task 7)."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from ..models import RuleStep, SegmentationJob, SegmentationPipeline
from ..tasks import (
    build_job_chain,
    finalize_job,
    prepare_job,
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
        self.assertEqual([s.args[0] for s in rule_sigs], [str(job.id)] * 2)
        self.assertEqual([s.args[1] for s in rule_sigs], [1, 2])

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

    def test_resume_without_steps_builds_full_chain(self):
        job = make_job()
        with patch("rule_based_segmentation.tasks.chain") as mock_chain:
            mock_chain.return_value.apply_async = lambda: None
            resume_job(job)
        sigs = mock_chain.call_args[0]
        self.assertEqual(len(sigs), 4)
        self.assertEqual(sigs[0].name, "rule_based_segmentation.prepare_job")
        self.assertEqual(sigs[1].args, (str(job.id), 1))
