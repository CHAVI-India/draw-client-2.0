"""Recursive boolean expression evaluator for rule-based segmentation."""

import logging
from typing import Dict, List, Set

import SimpleITK as sitk

from dicom_handler.utils.structure_generation.operations import (
    boolean_intersection,
    boolean_subtraction,
    boolean_union,
    boolean_xor,
)

from ..models import BooleanExpressionNode

logger = logging.getLogger(__name__)


class RuleEvaluationError(Exception):
    """Raised when a rule cannot be evaluated."""

    pass


OPERATION_MAP = {
    "UNION": boolean_union,
    "INTERSECTION": boolean_intersection,
    "SUBTRACT": boolean_subtraction,
    "XOR": boolean_xor,
}


def evaluate_boolean_tree(
    root_node: BooleanExpressionNode,
    available_masks: Dict[str, sitk.Image],
) -> sitk.Image:
    """
    Evaluate a model-backed boolean expression tree.

    Args:
        root_node: Root BooleanExpressionNode (parent=None).
        available_masks: Dictionary mapping ROI names to SimpleITK masks.

    Returns:
        Resulting SimpleITK binary mask.
    """
    return _evaluate_node(root_node, available_masks)


def _evaluate_node(
    node: BooleanExpressionNode,
    available_masks: Dict[str, sitk.Image],
) -> sitk.Image:
    if node.node_type == "ROI":
        roi_name = node.roi_name
        if roi_name not in available_masks:
            raise RuleEvaluationError(
                f"Structure '{roi_name}' is not available. "
                f"Available structures: {sorted(available_masks.keys())}"
            )
        return available_masks[roi_name]

    children = list(node.children.all().order_by("order"))
    if not children:
        raise RuleEvaluationError(
            f"Operation '{node.operation_type}' has no operands"
        )

    masks = [_evaluate_node(child, available_masks) for child in children]
    operation = node.operation_type

    if operation not in OPERATION_MAP:
        raise RuleEvaluationError(f"Unknown boolean operation: {operation}")

    op_func = OPERATION_MAP[operation]

    if operation == "SUBTRACT":
        result = masks[0]
        for mask in masks[1:]:
            result = op_func(result, mask)
        return result

    result = masks[0]
    for mask in masks[1:]:
        result = op_func(result, mask)
    return result


def collect_boolean_roi_names(root_node: BooleanExpressionNode) -> Set[str]:
    """Collect all ROI names referenced in a boolean tree."""
    names: Set[str] = set()
    _collect_names(root_node, names)
    return names


def _collect_names(node: BooleanExpressionNode, names: Set[str]) -> None:
    if node.node_type == "ROI":
        names.add(node.roi_name)
    else:
        for child in node.children.all().order_by("order"):
            _collect_names(child, names)


def get_boolean_root(rule) -> BooleanExpressionNode:
    """Get the root node for a boolean rule."""
    try:
        return rule.boolean_nodes.get(parent=None)
    except BooleanExpressionNode.DoesNotExist:
        raise RuleEvaluationError("Boolean rule has no root expression node")
    except BooleanExpressionNode.MultipleObjectsReturned:
        raise RuleEvaluationError("Boolean rule has multiple root expression nodes")
