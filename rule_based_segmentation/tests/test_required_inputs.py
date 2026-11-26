"""Rules with a missing required input must fail with a clear error, not a
cryptic ``KeyError: ''`` deep inside the evaluator (production regression: a
RING rule saved with an empty ``source`` crashed ``run_rule``)."""

import os
import shutil
import tempfile

import numpy as np
from django.test import TestCase

from ..models import (
    CleanupRuleConfig,
    MarginRuleConfig,
    PipelineRule,
    RingRuleConfig,
    SegmentationPipeline,
)
from ..utils.engine import SegmentationEngine
from ..utils.expression_evaluator import RuleEvaluationError
from ..utils.rtstruct_io import load_rtstruct_and_image
from .helpers import (
    create_dicom_models,
    create_synthetic_ct_series,
    create_synthetic_rtstruct,
)


class RequiredInputTests(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="rbs_req_")
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

    def _engine(self):
        rtstruct, image, _ = load_rtstruct_and_image(self.rtstruct_path, self.series_uid)
        return SegmentationEngine.from_rtstruct(rtstruct, image)

    def _rule(self, **kwargs):
        p = SegmentationPipeline.objects.create(name="p")
        defaults = dict(pipeline=p, order=1, name="out", output_action="CREATE_NEW")
        defaults.update(kwargs)
        return PipelineRule.objects.create(**defaults)

    def test_ring_with_empty_source_raises_clear_error(self):
        rule = self._rule(rule_type="RING")
        RingRuleConfig.objects.create(pipeline_rule=rule, source="")
        engine = self._engine()
        with self.assertRaises(RuleEvaluationError) as ctx:
            engine.run_rule(rule)
        self.assertIn("source", str(ctx.exception))
        self.assertNotIsInstance(ctx.exception, KeyError)

    def test_margin_with_empty_source_raises_clear_error(self):
        rule = self._rule(rule_type="MARGIN")
        MarginRuleConfig.objects.create(pipeline_rule=rule, source="", margin_mm=1.0)
        engine = self._engine()
        with self.assertRaises(RuleEvaluationError) as ctx:
            engine.run_rule(rule)
        self.assertIn("source", str(ctx.exception))

    def test_ring_missing_config_entirely_raises_clear_error(self):
        # A rule whose config object was never created (edge case).
        rule = self._rule(rule_type="RING")
        engine = self._engine()
        with self.assertRaises(RuleEvaluationError) as ctx:
            engine.run_rule(rule)
        self.assertIn("source", str(ctx.exception))

    def test_crop_with_empty_source_raises_clear_error(self):
        from ..models import CropRuleConfig

        rule = self._rule(rule_type="CROP")
        CropRuleConfig.objects.create(pipeline_rule=rule, source="")
        engine = self._engine()
        with self.assertRaises(RuleEvaluationError) as ctx:
            engine.run_rule(rule)
        self.assertIn("source", str(ctx.exception))

    def test_valid_ring_still_runs(self):
        # Regression guard: a well-formed RING rule must still work.
        rule = self._rule(rule_type="RING", name="ring")
        RingRuleConfig.objects.create(
            pipeline_rule=rule, source="CTV", thickness_mm=2.0
        )
        engine = self._engine()
        out = engine.run_rule(rule)
        self.assertEqual(out, "ring")

    def test_operation_error_converted_to_rule_evaluation_error(self):
        """Operation-level failures must surface as a RuleEvaluationError (so the
        inline runner + job service track/report them uniformly), not as a raw
        OperationExecutionError."""
        from unittest import mock

        from dicom_handler.utils.structure_generation import OperationExecutionError

        rule = self._rule(rule_type="RING", name="ring")
        RingRuleConfig.objects.create(pipeline_rule=rule, source="CTV", thickness_mm=2.0)
        engine = self._engine()
        with mock.patch(
            "rule_based_segmentation.utils.engine.execute_operation",
            side_effect=OperationExecutionError("boom"),
        ):
            with self.assertRaises(RuleEvaluationError) as ctx:
                engine.run_rule(rule)
        self.assertIn("boom", str(ctx.exception))
        self.assertIn("ring", str(ctx.exception).lower())

    def test_describe_error_handles_empty_and_normal_messages(self):
        from ..utils.job_service import _describe_error

        self.assertEqual(_describe_error(ValueError("")), "ValueError")
        self.assertEqual(_describe_error(KeyError("x")), "KeyError: 'x'")
        err = RuleEvaluationError("Rule 'x' needs a source structure")
        self.assertEqual(
            _describe_error(err),
            "RuleEvaluationError: Rule 'x' needs a source structure",
        )


class SaveGuardTests(TestCase):
    """The authoring path (save_pipeline_from_dict) must reject a source-less
    rule so it can never be persisted and then crash at run time (the exact
    production failure: a RING rule saved with source="")."""

    def test_ring_without_source_rejected_at_save(self):
        from ..utils.pipeline_persistence import save_pipeline_from_dict

        with self.assertRaises(ValueError) as ctx:
            save_pipeline_from_dict(
                {"name": "p", "rules": [{"rule_type": "RING", "name": "ring_ctvp",
                                         "output_action": "CREATE_NEW",
                                         "config": {"source": "", "thickness_l_mm": 0}}]},
                user=None,
            )
        self.assertIn("source", str(ctx.exception).lower())

    def test_ring_with_source_saves(self):
        from django.contrib.auth.models import User

        from ..utils.pipeline_persistence import save_pipeline_from_dict

        user = User.objects.create_user(username="author")
        p = save_pipeline_from_dict(
            {"name": "p", "rules": [{"rule_type": "RING", "name": "ring_ctvp",
                                     "output_action": "CREATE_NEW",
                                     "config": {"source": "CTV", "thickness_l_mm": 2}}]},
            user=user,
        )
        self.assertEqual(p.rules.count(), 1)
        self.assertEqual(p.rules.first().ring_config.source, "CTV")
