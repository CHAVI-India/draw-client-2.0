"""Tests for InlineSegmentationRunner (in-memory RBS, no job / work dir)."""

import os
import shutil
import tempfile

import numpy as np
from django.test import TestCase

from ..models import (
    CleanupRuleConfig,
    MarginRuleConfig,
    PipelineRule,
    SegmentationPipeline,
)
from ..utils.inline_runner import InlineSegmentationRunner
from ..utils.rtstruct_io import load_rtstruct_and_image
from .helpers import (
    create_dicom_models,
    create_synthetic_ct_series,
    create_synthetic_rtstruct,
)


class InlineRunnerTests(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="rbs_inline_")
        self.series_uid = "1.2.3.4.5.6.7.8.9"
        self.study_uid = "1.2.3.4.5.6.7.8.10"
        self.ct_files = create_synthetic_ct_series(
            self.temp_dir, num_slices=10, rows=64, cols=64,
            series_uid=self.series_uid, study_uid=self.study_uid,
        )
        create_dicom_models(self.ct_files, self.series_uid, self.study_uid)
        self.mask = np.zeros((10, 64, 64), dtype=bool)
        self.mask[3:7, 28:36, 28:36] = True
        self.rtstruct_path = os.path.join(self.temp_dir, "rt.dcm")
        create_synthetic_rtstruct(
            self.rtstruct_path, self.ct_files, roi_name="CTV",
            mask_array=self.mask, color=[255, 0, 0],
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _chain_rules(self):
        pipeline = SegmentationPipeline.objects.create(name="p")
        grow = PipelineRule.objects.create(
            pipeline=pipeline, order=1, rule_type="MARGIN", name="grown",
            output_action="INTERMEDIATE", output_color="255\\255\\0",
        )
        MarginRuleConfig.objects.create(
            pipeline_rule=grow, variant="UNIFORM", source="CTV",
            margin_mm=3.0, kernel_type="ball",
        )
        keep = PipelineRule.objects.create(
            pipeline=pipeline, order=2, rule_type="CLEANUP", name="CTV_margin",
            output_action="CREATE_NEW", output_color="255\\0\\0",
            output_roi_type="PTV",
        )
        CleanupRuleConfig.objects.create(
            pipeline_rule=keep, operation="KEEP_LARGEST_COMPONENT", source="grown",
        )
        return [grow, keep]

    def test_chain_exports_only_final_roi(self):
        rtstruct, image, _ = load_rtstruct_and_image(self.rtstruct_path, self.series_uid)
        runner = InlineSegmentationRunner(rtstruct, image)
        summary = runner.run_rules(self._chain_rules())

        self.assertIn("grown", summary["intermediate"])
        self.assertEqual(summary["created"], ["CTV_margin"])
        # intermediate is held in memory, NOT exported
        self.assertNotIn("grown", rtstruct.get_roi_names())
        self.assertIn("CTV_margin", rtstruct.get_roi_names())

    def test_skip_existing_suppresses_final_output(self):
        rtstruct, image, _ = load_rtstruct_and_image(self.rtstruct_path, self.series_uid)
        runner = InlineSegmentationRunner(rtstruct, image)
        # "CTV_margin" is treated as already present -> skipped, nothing written.
        summary = runner.run_rules(
            self._chain_rules(), skip_existing={"CTV_margin"}
        )
        self.assertIn("CTV_margin", summary["skipped"])
        self.assertNotIn("CTV_margin", rtstruct.get_roi_names())

    def test_missing_source_raises(self):
        from ..utils.expression_evaluator import RuleEvaluationError

        pipeline = SegmentationPipeline.objects.create(name="p")
        rule = PipelineRule.objects.create(
            pipeline=pipeline, order=1, rule_type="MARGIN", name="out",
            output_action="CREATE_NEW",
        )
        MarginRuleConfig.objects.create(
            pipeline_rule=rule, variant="UNIFORM", source="MISSING",
            margin_mm=2.0, kernel_type="ball",
        )
        rtstruct, image, _ = load_rtstruct_and_image(self.rtstruct_path, self.series_uid)
        runner = InlineSegmentationRunner(rtstruct, image)
        with self.assertRaises(RuleEvaluationError):
            runner.run_rules([rule])
