"""Tests for the chain-step service functions (prepare/execute/finalize)."""

import os
import shutil
import tempfile
from unittest import mock

import numpy as np
from django.test import TestCase
from django.utils import timezone

from spatial_overlap.models import RTStructureSetFile
from rt_utils import RTStructBuilder

from ..models import RuleStep, SegmentationJob
from ..utils import job_service
from ..utils.expression_evaluator import RuleEvaluationError
from ..utils.job_workdir import JobWorkdir
from ..utils.job_service import MissingImageSeriesError
from .helpers import (
    create_dicom_models,
    create_pipeline_with_rules,
    create_synthetic_ct_series,
    create_synthetic_rtstruct,
)

RULES = [
    {
        "rule_type": "MARGIN",
        "name": "PTV",
        "config": {
            "variant": "UNIFORM",
            "source": "Box",
            "margin_mm": 2.0,
            "kernel_type": "ball",
        },
    },
    {
        "rule_type": "BOOLEAN",
        "name": "Union",
        "config": {
            "operation": "UNION",
            "operands": [{"name": "Box"}, {"name": "PTV"}],
        },
    },
]


class StepTestBase(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="rbs_steps_")
        self.base_dir = os.path.join(self.temp_dir, "work")
        self.series_uid = "1.2.3.4.5.6.7.8.9"
        self.study_uid = "1.2.3.4.5.6.7.8.10"
        self.ct_files = create_synthetic_ct_series(
            self.temp_dir,
            num_slices=10,
            rows=64,
            cols=64,
            spacing=(1.0, 1.0, 1.0),
            series_uid=self.series_uid,
            study_uid=self.study_uid,
        )
        self.series = create_dicom_models(
            self.ct_files, self.series_uid, self.study_uid
        )
        self.mask_array = np.zeros((10, 64, 64), dtype=bool)
        self.mask_array[3:7, 28:36, 28:36] = True
        self.rtstruct_path = os.path.join(self.temp_dir, "test_rtstruct.dcm")
        create_synthetic_rtstruct(
            self.rtstruct_path,
            self.ct_files,
            roi_name="Box",
            mask_array=self.mask_array,
        )
        self.rt_record = RTStructureSetFile.objects.create(
            patient_name="Test^Patient",
            patient_id="TESTPATIENT",
            study_instance_uid=self.study_uid,
            series_instance_uid=self.series_uid,
            sop_instance_uid="9.9.9.1",
            structure_set_label="Test",
            referenced_series_instance_uid=self.series_uid,
            rtstructure_file_path=self.rtstruct_path,
            working_directory=self.temp_dir,
        )
        self.pipeline = create_pipeline_with_rules(
            name="Step Pipeline", rules_data=RULES
        )
        self._base_patch = mock.patch(
            "rule_based_segmentation.utils.job_service.get_job_workdir_base",
            return_value=self.base_dir,
        )
        self._base_patch.start()

    def tearDown(self):
        self._base_patch.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def make_job(self, pipeline=None):
        return SegmentationJob.objects.create(
            pipeline=pipeline or self.pipeline,
            input_type="UPLOAD",
            input_upload=self.rt_record,
            status="PENDING",
        )

    def wd(self, job):
        return JobWorkdir(job.id, base_dir=self.base_dir)

    def _working_rtstruct(self, job):
        wd = self.wd(job)
        return RTStructBuilder.create_from(
            dicom_series_path=wd.images_dir, rt_struct_path=wd.working_path
        )


class PrepareJobTests(StepTestBase):
    def test_prepare_creates_workdir_caches_and_steps(self):
        job = self.make_job()
        job_service.prepare_job(job)
        job.refresh_from_db()

        self.assertEqual(job.status, "STARTED")
        self.assertIsNotNone(job.started_at)
        self.assertEqual(job.dicom_series_id, self.series.id)
        self.assertTrue(os.path.exists(job.backup_file_path))

        wd = self.wd(job)
        self.assertEqual(len(os.listdir(wd.images_dir)), 10)
        self.assertTrue(os.path.exists(wd.image_cache_path))
        self.assertTrue(os.path.exists(wd.working_path))
        self.assertEqual(
            set(RuleStep.objects.filter(job=job).values_list("order", flat=True)),
            {1, 2},
        )
        self.assertTrue(all(s.status == "PENDING" for s in job.steps.all()))

    def test_prepare_missing_series_marks_job_failed(self):
        self.rt_record.referenced_series_instance_uid = "0.0.0.missing"
        self.rt_record.save()
        job = self.make_job()
        with self.assertRaises(MissingImageSeriesError):
            job_service.prepare_job(job)
        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")
        self.assertIn("not available", job.error_message)
        self.assertIsNotNone(job.completed_at)

    def test_prepare_missing_file_marks_job_failed(self):
        os.remove(self.rtstruct_path)
        job = self.make_job()
        with self.assertRaises(ValueError):
            job_service.prepare_job(job)
        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")
        self.assertIn("not found", job.error_message)


class ExecuteRuleStepTests(StepTestBase):
    def _prepared_job(self):
        job = self.make_job()
        job_service.prepare_job(job)
        return job

    def test_execute_two_steps_in_order(self):
        job = self._prepared_job()
        job_service.execute_rule_step(job, 1)
        job_service.execute_rule_step(job, 2)

        rtstruct = self._working_rtstruct(job)
        names = rtstruct.get_roi_names()
        self.assertIn("PTV", names)
        self.assertIn("Union", names)

        step1 = RuleStep.objects.get(job=job, order=1)
        self.assertEqual(step1.status, "SUCCESS")
        self.assertEqual(step1.output_roi_name, "PTV")
        self.assertIsNotNone(step1.started_at)
        self.assertIsNotNone(step1.completed_at)
        self.assertEqual(
            RuleStep.objects.filter(job=job, status="SUCCESS").count(), 2
        )

    def test_duplicate_delivery_is_noop(self):
        job = self._prepared_job()
        job_service.execute_rule_step(job, 1)
        job_service.execute_rule_step(job, 1)  # redelivery

        rtstruct = self._working_rtstruct(job)
        self.assertEqual(rtstruct.get_roi_names().count("PTV"), 1)
        step = RuleStep.objects.get(job=job, order=1)
        self.assertEqual(step.status, "SUCCESS")

    def test_failed_rule_marks_step_and_job_failed(self):
        bad_pipeline = create_pipeline_with_rules(
            name="Bad",
            rules_data=[
                {
                    "rule_type": "MARGIN",
                    "name": "Bad",
                    "config": {
                        "variant": "UNIFORM",
                        "source": "NoSuchStructure",
                        "margin_mm": 2.0,
                        "kernel_type": "ball",
                    },
                }
            ],
        )
        job = self.make_job(pipeline=bad_pipeline)
        job_service.prepare_job(job)
        with self.assertRaises(RuleEvaluationError):
            job_service.execute_rule_step(job, 1)

        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")
        self.assertIn("NoSuchStructure", job.error_message)
        step = RuleStep.objects.get(job=job, order=1)
        self.assertEqual(step.status, "FAILED")
        self.assertIn("NoSuchStructure", step.error)

    def test_redelivery_after_commit_before_step_update(self):
        """Worker died between the disk commit and the step UPDATE: redelivery
        must not duplicate the ROI."""
        job = self._prepared_job()
        job_service.execute_rule_step(job, 1)
        step = RuleStep.objects.get(job=job, order=1)
        step.status = "RUNNING"  # simulate the lost SUCCESS update
        step.save()

        job_service.execute_rule_step(job, 1)  # redelivery

        step.refresh_from_db()
        self.assertEqual(step.status, "SUCCESS")
        rtstruct = self._working_rtstruct(job)
        self.assertEqual(rtstruct.get_roi_names().count("PTV"), 1)


class FinalizeJobTests(StepTestBase):
    def _completed_job(self):
        job = self.make_job()
        job_service.prepare_job(job)
        job_service.execute_rule_step(job, 1)
        job_service.execute_rule_step(job, 2)
        return job

    def test_finalize_writes_output_and_marks_success(self):
        job = self._completed_job()
        with open(self.rtstruct_path, "rb") as fh:
            original_bytes = fh.read()

        summary = job_service.finalize_job(job)
        job.refresh_from_db()

        self.assertEqual(job.status, "SUCCESS")
        self.assertEqual(job.output_file_path, self.rtstruct_path)
        self.assertIsNone(job.error_message)
        with open(self.rtstruct_path, "rb") as fh:
            self.assertNotEqual(original_bytes, fh.read())
        self.assertEqual(summary["created_rois"], ["PTV", "Union"])
        self.assertTrue(job.result_summary["sop_instance_uid"])
        self.assertTrue(job.result_summary["series_instance_uid"])

        # input record UIDs were synced to the regenerated file
        self.rt_record.refresh_from_db()
        self.assertEqual(
            self.rt_record.sop_instance_uid,
            job.result_summary["sop_instance_uid"],
        )
        # work dir cleaned up on success
        self.assertFalse(self.wd(job).exists())

    def test_finalize_is_idempotent(self):
        job = self._completed_job()
        first = job_service.finalize_job(job)
        second = job_service.finalize_job(job)
        self.assertEqual(first, second)
        job.refresh_from_db()
        self.assertEqual(job.status, "SUCCESS")
