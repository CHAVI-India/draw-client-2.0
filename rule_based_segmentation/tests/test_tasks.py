"""Tests for rule_based_segmentation Celery tasks."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from ..tasks import run_segmentation_job

User = get_user_model()


class TaskTests(TestCase):
    def test_job_not_found(self):
        result = run_segmentation_job("00000000-0000-0000-0000-000000000000")
        self.assertEqual(result["status"], "FAILED")
        self.assertIn("not found", result["error"])

    @patch("rule_based_segmentation.tasks.run_job")
    def test_job_execution(self, mock_run_job):
        from ..models import SegmentationJob, SegmentationPipeline

        user = User.objects.create_user(username="testuser2", password="testpass")
        pipeline = SegmentationPipeline.objects.create(name="Test")
        job = SegmentationJob.objects.create(
            pipeline=pipeline,
            input_type="UPLOAD",
            created_by=user,
            status="PENDING",
        )

        result = run_segmentation_job(str(job.id))
        mock_run_job.assert_called_once()
        self.assertEqual(result["status"], job.status)
