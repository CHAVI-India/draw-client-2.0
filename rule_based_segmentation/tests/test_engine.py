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
