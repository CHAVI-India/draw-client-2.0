"""Tests for the rule evaluation engine."""

import numpy as np
import SimpleITK as sitk
from django.core.exceptions import ValidationError
from django.test import TestCase

from dicom_handler.utils.structure_generation.operations import (
    boolean_subtraction,
    boolean_union,
)

from ..models import (
    BooleanExpressionNode,
    MarginRuleConfig,
    PipelineRule,
    SegmentationPipeline,
)
from ..utils.expression_evaluator import (
    RuleEvaluationError,
    evaluate_boolean_tree,
    get_boolean_root,
)
from .helpers import assert_mask_equal, create_box_mask


class BooleanEvaluatorTests(TestCase):
    def test_nested_union_then_subtract(self):
        shape = (20, 20, 20)
        a = create_box_mask(shape, (2, 2, 2), (6, 6, 6))
        b = create_box_mask(shape, (5, 5, 5), (9, 9, 9))
        c = create_box_mask(shape, (7, 7, 7), (12, 12, 12))

        pipeline = SegmentationPipeline.objects.create(name="Test")
        rule = PipelineRule.objects.create(
            pipeline=pipeline,
            order=1,
            rule_type="BOOLEAN",
            name="Result",
        )
        root = BooleanExpressionNode.objects.create(
            pipeline_rule=rule,
            node_type="OPERATION",
            operation_type="SUBTRACT",
            order=1,
        )
        group = BooleanExpressionNode.objects.create(
            pipeline_rule=rule,
            parent=root,
            node_type="OPERATION",
            operation_type="UNION",
            order=1,
        )
        BooleanExpressionNode.objects.create(
            pipeline_rule=rule,
            parent=group,
            node_type="ROI",
            roi_name="A",
            order=1,
        )
        BooleanExpressionNode.objects.create(
            pipeline_rule=rule,
            parent=group,
            node_type="ROI",
            roi_name="B",
            order=2,
        )
        BooleanExpressionNode.objects.create(
            pipeline_rule=rule,
            parent=root,
            node_type="ROI",
            roi_name="C",
            order=2,
        )

        result = evaluate_boolean_tree(
            get_boolean_root(rule),
            {"A": a, "B": b, "C": c},
        )
        expected = boolean_subtraction(boolean_union(a, b), c)
        self.assertTrue(assert_mask_equal(result, expected))

    def test_missing_roi_raises(self):
        pipeline = SegmentationPipeline.objects.create(name="Test")
        rule = PipelineRule.objects.create(
            pipeline=pipeline,
            order=1,
            rule_type="BOOLEAN",
            name="Result",
        )
        root = BooleanExpressionNode.objects.create(
            pipeline_rule=rule,
            node_type="OPERATION",
            operation_type="UNION",
            order=1,
        )
        BooleanExpressionNode.objects.create(
            pipeline_rule=rule,
            parent=root,
            node_type="ROI",
            roi_name="A",
            order=1,
        )
        BooleanExpressionNode.objects.create(
            pipeline_rule=rule,
            parent=root,
            node_type="ROI",
            roi_name="B",
            order=2,
        )

        with self.assertRaises(RuleEvaluationError):
            evaluate_boolean_tree(get_boolean_root(rule), {"A": create_box_mask((10, 10, 10), (0, 0, 0), (2, 2, 2))})


class MarginRuleConfigTests(TestCase):
    def test_uniform_margin_config(self):
        pipeline = SegmentationPipeline.objects.create(name="Test")
        rule = PipelineRule.objects.create(
            pipeline=pipeline,
            order=1,
            rule_type="MARGIN",
            name="PTV",
        )
        MarginRuleConfig.objects.create(
            pipeline_rule=rule,
            variant="UNIFORM",
            source="CTV",
            margin_mm=5.0,
            kernel_type="ball",
        )
        rule.full_clean()

    def test_anisotropic_margin_requires_all_axes(self):
        pipeline = SegmentationPipeline.objects.create(name="Test")
        rule = PipelineRule.objects.create(
            pipeline=pipeline,
            order=1,
            rule_type="MARGIN",
            name="PTV",
        )
        MarginRuleConfig.objects.create(
            pipeline_rule=rule,
            variant="ANISOTROPIC",
            source="CTV",
            margin_x_mm=5.0,
        )
        with self.assertRaises(ValidationError):
            rule.full_clean()


class IntermediateActionTests(TestCase):
    """INTERMEDIATE rules are evaluated but never written to the RTStruct."""

    def _make_engine(self, masks):
        from ..utils.engine import SegmentationEngine

        eng = SegmentationEngine.__new__(SegmentationEngine)
        eng.available_masks = masks
        eng.summary = {
            "created_rois": [],
            "replaced_rois": [],
            "intermediate_rois": [],
            "failed_rules": [],
        }
        return eng

    class _FakeRtstruct:
        def __init__(self):
            self.added = []

        def get_roi_names(self):
            return list(self.added)

        def add_roi(self, **kwargs):
            self.added.append(kwargs["name"])

    def test_intermediate_is_not_exported_but_is_reusable(self):
        seed = create_box_mask((24, 24, 24), (6, 6, 6), (12, 12, 12))
        pipeline = SegmentationPipeline.objects.create(name="p")
        rule = PipelineRule.objects.create(
            pipeline=pipeline,
            order=1,
            rule_type="MARGIN",
            name="grown",
            output_action="INTERMEDIATE",
            output_color="255\\255\\0",
        )
        MarginRuleConfig.objects.create(
            pipeline_rule=rule,
            variant="UNIFORM",
            source="seed",
            margin_mm=3.0,
        )

        eng = self._make_engine({"seed": seed})
        eng.rtstruct = self._FakeRtstruct()

        out = eng.run_rule(rule)

        self.assertEqual(out, "grown")
        self.assertIn("grown", eng.available_masks)
        self.assertEqual(eng.rtstruct.added, [])
        self.assertIn("grown", eng.summary["intermediate_rois"])
        self.assertNotIn("grown", eng.summary["created_rois"])


class CleanupExtraOpsTests(TestCase):
    """The three refinement ops missing from the legacy CLEANUP rule."""

    def _engine_with(self, source):
        from ..utils.engine import SegmentationEngine

        eng = SegmentationEngine.__new__(SegmentationEngine)
        eng.available_masks = {"src": source}
        eng.summary = {
            "created_rois": [],
            "replaced_rois": [],
            "intermediate_rois": [],
            "failed_rules": [],
        }
        return eng

    def _make_cleanup_rule(self, operation, **fields):
        pipeline = SegmentationPipeline.objects.create(name="p")
        rule = PipelineRule.objects.create(
            pipeline=pipeline, order=1, rule_type="CLEANUP", name="out"
        )
        from ..models import CleanupRuleConfig

        CleanupRuleConfig.objects.create(
            pipeline_rule=rule, operation=operation, source="src", **fields
        )
        return rule

    def test_keep_n_largest_rule(self):
        src = create_box_mask((20, 20, 20), (0, 0, 0), (20, 20, 20))
        rule = self._make_cleanup_rule("KEEP_N_LARGEST_COMPONENT", n=1)
        out = self._engine_with(src)._evaluate_cleanup_rule(rule)
        self.assertIsNotNone(out)
        self.assertGreater(int(np.sum(sitk.GetArrayFromImage(out).astype(bool))), 0)

    def test_close_gaps_rule(self):
        src = create_box_mask((20, 20, 20), (4, 4, 4), (8, 8, 8))
        rule = self._make_cleanup_rule("CLOSE_GAPS", gap_size_mm=2.0)
        out = self._engine_with(src)._evaluate_cleanup_rule(rule)
        self.assertIsNotNone(out)

    def test_remove_protrusions_rule(self):
        src = create_box_mask((20, 20, 20), (4, 4, 4), (8, 8, 8))
        rule = self._make_cleanup_rule("REMOVE_PROTRUSIONS", protrusion_size_mm=2.0)
        out = self._engine_with(src)._evaluate_cleanup_rule(rule)
        self.assertIsNotNone(out)
