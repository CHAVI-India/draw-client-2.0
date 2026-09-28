"""Tests for rule_based_segmentation models."""

from django.core.exceptions import ValidationError
from django.test import TestCase

from ..models import (
    BooleanExpressionNode,
    PipelineRule,
    SegmentationPipeline,
)


class ModelTests(TestCase):
    def test_create_pipeline_and_rule(self):
        pipeline = SegmentationPipeline.objects.create(name="Test Pipeline")
        rule = PipelineRule.objects.create(
            pipeline=pipeline,
            order=1,
            rule_type="MARGIN",
            name="PTV",
        )
        self.assertEqual(str(rule), "1. PTV (MARGIN)")

    def test_boolean_tree_validation_requires_root(self):
        pipeline = SegmentationPipeline.objects.create(name="Boolean Test")
        rule = PipelineRule.objects.create(
            pipeline=pipeline,
            order=1,
            rule_type="BOOLEAN",
            name="Result",
        )
        with self.assertRaises(ValidationError):
            rule.full_clean()

    def test_boolean_tree_validation_requires_two_operands(self):
        pipeline = SegmentationPipeline.objects.create(name="Boolean Test")
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
        with self.assertRaises(ValidationError):
            rule.full_clean()

    def test_boolean_tree_validation_passes_with_two_operands(self):
        pipeline = SegmentationPipeline.objects.create(name="Boolean Test")
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
        rule.full_clean()
