"""Synthesize legacy ``roi_generation_logic`` chains into RBS rules.

DEPRECATED (Phase 5) - not used by any live code path. The template's
additional structures are now authored directly as an RBS
``SegmentationPipeline`` (``template.additional_structures_pipeline``) and
executed by task2; this module is retained only because the historical
migration 0062 imports it at runtime, so a fresh-database ``manage.py migrate``
stays portable. See ``docs/superpowers/plans/2026-11-26-template-pipeline-redesign.md``
("Future cleanup") for the steps to remove it.

The legacy generated-contour system stored, per ``AdditionalStructures`` row, a
JSON chain::

    {"operations": [{"type": ..., "structures": [...], "parameters": {...}}, ...]}

and executed it with a running result that only the *final* operation's output
was written (see ``dicom_handler.utils.pipeline_executor``). This module
reproduces that chain as an ordered list of (saved) RBS ``PipelineRule``
objects:

* every operation except the last becomes an ``INTERMEDIATE`` rule (held in
  memory, never exported);
* the last becomes a ``CREATE_NEW`` rule named after the structure's
  ``roi_label`` with the structure's own color / interpreted type.

Role semantics mirror ``ProductionPipelineExecutor._build_roles`` exactly:
``margin``/boolean/``overlap``/``expand_subtract``/``avoid_margin``/``ring``
reference the *named* structures, while ``crop_to_boundary`` and every
refinement (cleanup) operation consume the *running result* (the previous
rule's output) as their source.

The rules are saved into a (caller-supplied or newly-created)
``SegmentationPipeline`` because the RBS engine resolves each rule's config
through the ORM. The caller owns the pipeline and is expected to delete it
after running (see ``dicom_handler`` task2).
"""

import logging
import re
from typing import List, Optional, Tuple

from ..models import (
    BooleanExpressionNode,
    CleanupRuleConfig,
    ExpandSubtractRuleConfig,
    IntensityRange,
    IntensityRuleConfig,
    MarginRuleConfig,
    OverlapOther,
    OverlapRuleConfig,
    PipelineRule,
    RingRuleConfig,
    SegmentationPipeline,
)
from .expression_evaluator import RuleEvaluationError
from dicom_handler.utils.structure_generation.operation_catalog import (
    resolve_operation_id,
)

logger = logging.getLogger(__name__)

# Refinement ops that consume the running result as their source (like
# crop_to_boundary). Everything else references its named structures.
_CLEANUP_OPS = {
    "smooth": ("SMOOTH_STRUCTURE", "smoothing_mm", "iterations"),
    "gaussian_smooth": ("GAUSSIAN_SMOOTH", "sigma_mm", "threshold"),
    "fill_holes": ("FILL_HOLES", "fully_connected", None),
    "remove_small_components": ("REMOVE_SMALL_COMPONENTS", "min_size_mm3", None),
    "keep_largest": ("KEEP_LARGEST_COMPONENT", None, None),
    "keep_n_largest": ("KEEP_N_LARGEST_COMPONENT", "n", None),
    "close_gaps": ("CLOSE_GAPS", "gap_size_mm", None),
    "remove_protrusions": ("REMOVE_PROTRUSIONS", "protrusion_size_mm", None),
}

_BOOLEAN_OPS = {
    "union": "UNION",
    "intersection": "INTERSECTION",
    "subtract": "SUBTRACT",
    "xor": "XOR",
}


class LegacySynthesisError(ValueError):
    """Raised when a legacy chain cannot be expressed as RBS rules."""


def _slug(name: str) -> str:
    """A short filesystem/identifier-safe token for namespacing intermediates."""
    return re.sub(r"[^A-Za-z0-9]+", "_", (name or "")).strip("_") or "roi"


def _next_order(pipeline: SegmentationPipeline) -> int:
    return int(pipeline.rules.count()) + 1


def _signed_margin_kwargs(op_type: str, params: dict) -> dict:
    """Margin config kwargs, applying the legacy ``contract`` sign flip."""
    kwargs = {
        "variant": params.get("variant", "UNIFORM"),
        "kernel_type": params.get("kernel_type", "ball"),
    }
    negate = op_type == "contract"
    fields = [
        "margin_mm", "margin_x_mm", "margin_y_mm", "margin_z_mm",
        "margin_l_mm", "margin_r_mm", "margin_a_mm",
        "margin_p_mm", "margin_h_mm", "margin_f_mm",
    ]
    for field in fields:
        if field in params and params[field] is not None:
            value = float(params[field])
            kwargs[field] = -value if negate else value
    if not any(
        kwargs.get(f) is not None for f in fields
    ) and "margin_mm" not in params:
        # No margin magnitude supplied: legacy would treat this as a 0/no-op.
        kwargs["margin_mm"] = 0.0
    return kwargs


def _build_boolean(rule: PipelineRule, op_type: str, operands: List[str]) -> None:
    root = BooleanExpressionNode.objects.create(
        pipeline_rule=rule,
        node_type="OPERATION",
        operation_type=_BOOLEAN_OPS[op_type],
        order=1,
    )
    for idx, name in enumerate(operands, start=1):
        BooleanExpressionNode.objects.create(
            pipeline_rule=rule,
            parent=root,
            node_type="ROI",
            roi_name=name,
            order=idx,
        )


def _build_intensity(rule: PipelineRule, structures: List[str], params: dict) -> None:
    seed_roi = structures[0] if len(structures) >= 1 else None
    boundary_roi = structures[1] if len(structures) >= 2 else None
    if seed_roi and boundary_roi:
        seed_type = "STRUCTURE"
    elif boundary_roi and not seed_roi:
        seed_type = "BOUNDARY"
    else:
        seed_type = "STRUCTURE" if seed_roi else "IMAGE"
    config = IntensityRuleConfig.objects.create(
        pipeline_rule=rule,
        seed_type=seed_type,
        seed_roi=seed_roi,
        boundary_roi=boundary_roi,
    )
    for idx, rng in enumerate(params.get("ranges", []), start=1):
        IntensityRange.objects.create(
            intensity_rule=config,
            min_value=float(rng["min"]),
            max_value=float(rng["max"]),
            order=idx,
        )


def _make_rule(pipeline, order, rule_type, name, output_action, output_color, output_roi_type) -> PipelineRule:
    return PipelineRule.objects.create(
        pipeline=pipeline,
        order=order,
        rule_type=rule_type,
        name=name,
        output_action=output_action,
        output_color=output_color,
        output_roi_type=output_roi_type,
    )


def synthesize_rules(
    additional_structure,
    pipeline: Optional[SegmentationPipeline] = None,
) -> Tuple[List[PipelineRule], SegmentationPipeline]:
    """Create RBS rules that reproduce ``additional_structure.roi_generation_logic``.

    Args:
        additional_structure: an ``AdditionalStructures`` row.
        pipeline: an existing pipeline to attach the rules to (use a single one
            for a whole reidentification run). If ``None`` a new private,
            inactive pipeline is created.

    Returns:
        ``(rules, pipeline)`` where ``rules`` is the ordered list of (saved)
        ``PipelineRule`` objects. The caller is responsible for running the
        rules (``InlineSegmentationRunner``) and for deleting ``pipeline`` when
        it created it.

    Raises:
        LegacySynthesisError: if the chain is empty, or an operation id has no
            RBS mapping, or a running-result op appears with no predecessor.
    """
    logic = additional_structure.roi_generation_logic
    if not logic or not logic.get("operations"):
        return [], (pipeline or _new_pipeline(additional_structure))

    if pipeline is None:
        pipeline = _new_pipeline(additional_structure)

    roi_label = additional_structure.roi_label
    slug = _slug(roi_label)
    operations = logic["operations"]
    rules: List[PipelineRule] = []
    prev_name: Optional[str] = None

    for idx, op in enumerate(operations):
        raw_type = op.get("type")
        structures = list(op.get("structures", []))
        params = dict(op.get("parameters", {}))
        try:
            canonical = resolve_operation_id(raw_type)
        except KeyError as e:
            raise LegacySynthesisError(
                f"Operation type {raw_type!r} has no RBS mapping: {e}"
            ) from e

        is_last = idx == len(operations) - 1
        name = roi_label if is_last else f"__{slug}_step_{idx}"
        output_action = "CREATE_NEW" if is_last else "INTERMEDIATE"
        output_color = (
            additional_structure.roi_display_color if is_last else None
        )
        output_roi_type = (
            additional_structure.rt_roi_interpreted_type if is_last else None
        )
        order = _next_order(pipeline)

        uses_running_result = canonical in _CLEANUP_OPS or canonical == "crop_to_boundary"
        if uses_running_result and prev_name is None:
            raise LegacySynthesisError(
                f"Operation {idx} ({canonical}) needs a preceding operation to "
                "consume as its source; it is the first in the chain."
            )

        rule = _make_rule(
            pipeline, order, _rule_type_for(canonical), name,
            output_action, output_color, output_roi_type,
        )
        _attach_config(rule, canonical, raw_type, structures, params, prev_name)
        rules.append(rule)
        prev_name = name

    return rules, pipeline


def _new_pipeline(additional_structure) -> SegmentationPipeline:
    return SegmentationPipeline.objects.create(
        name=f"synthesized-{_slug(additional_structure.roi_label)}",
        is_public=False,
        is_active=False,
    )


def _rule_type_for(canonical: str) -> str:
    if canonical == "margin":
        return "MARGIN"
    if canonical in _BOOLEAN_OPS:
        return "BOOLEAN"
    if canonical == "crop_to_boundary":
        return "CROP"
    if canonical == "ring":
        return "RING"
    if canonical == "overlap":
        return "OVERLAP"
    if canonical == "expand_subtract":
        return "EXPAND_SUBTRACT"
    if canonical == "avoid_margin":
        return "AVOID_MARGIN"
    if canonical in _CLEANUP_OPS:
        return "CLEANUP"
    if canonical == "intensity_range":
        return "INTENSITY"
    raise LegacySynthesisError(f"No RBS rule type for operation {canonical!r}")


def _attach_config(
    rule: PipelineRule,
    canonical: str,
    raw_type: str,
    structures: List[str],
    params: dict,
    prev_name: Optional[str],
) -> None:
    """Attach the rule's config, wiring the correct source reference."""
    if canonical == "margin":
        kwargs = _signed_margin_kwargs(raw_type, params)
        if structures:
            kwargs["source"] = structures[0]
        MarginRuleConfig.objects.create(pipeline_rule=rule, **kwargs)
        return

    if canonical in _BOOLEAN_OPS:
        if len(structures) < 2:
            raise LegacySynthesisError(
                f"Boolean op {canonical} needs at least 2 structures, got {len(structures)}"
            )
        _build_boolean(rule, canonical, structures)
        return

    if canonical == "crop_to_boundary":
        if not structures:
            raise LegacySynthesisError("crop_to_boundary needs boundary structure(s)")
        from ..models import CropBoundary, CropRuleConfig

        config = CropRuleConfig.objects.create(pipeline_rule=rule, source=prev_name)
        for i, boundary in enumerate(structures, start=1):
            CropBoundary.objects.create(
                crop_rule=config, boundary_roi=boundary, order=i
            )
        return

    if canonical in _CLEANUP_OPS:
        operation, primary, secondary = _CLEANUP_OPS[canonical]
        kwargs = {"operation": operation, "source": prev_name}
        if primary and primary in params:
            kwargs[primary] = params[primary]
        if secondary and secondary in params:
            kwargs[secondary] = params[secondary]
        CleanupRuleConfig.objects.create(pipeline_rule=rule, **kwargs)
        return

    if canonical == "ring":
        RingRuleConfig.objects.create(
            pipeline_rule=rule,
            variant=params.get("variant", "UNIFORM"),
            source=structures[0] if structures else None,
            thickness_mm=params.get("thickness_mm"),
            thickness_x_mm=params.get("thickness_x_mm"),
            thickness_y_mm=params.get("thickness_y_mm"),
            thickness_z_mm=params.get("thickness_z_mm"),
            kernel_type=params.get("kernel_type", "ball"),
            thickness_l_mm=params.get("thickness_l_mm"),
            thickness_r_mm=params.get("thickness_r_mm"),
            thickness_a_mm=params.get("thickness_a_mm"),
            thickness_p_mm=params.get("thickness_p_mm"),
            thickness_h_mm=params.get("thickness_h_mm"),
            thickness_f_mm=params.get("thickness_f_mm"),
        )
        return

    if canonical == "overlap":
        if len(structures) < 2:
            raise LegacySynthesisError("overlap needs a source and at least one other")
        config = OverlapRuleConfig.objects.create(
            pipeline_rule=rule, source=structures[0]
        )
        for i, other in enumerate(structures[1:], start=1):
            OverlapOther.objects.create(overlap_rule=config, other_roi=other, order=i)
        return

    if canonical == "expand_subtract":
        if len(structures) < 2:
            raise LegacySynthesisError("expand_subtract needs a source and a subtract")
        ExpandSubtractRuleConfig.objects.create(
            pipeline_rule=rule,
            variant=params.get("variant", "UNIFORM"),
            source=structures[0],
            subtract=structures[1],
            distance_mm=params.get("distance_mm"),
            distance_x_mm=params.get("distance_x_mm"),
            distance_y_mm=params.get("distance_y_mm"),
            distance_z_mm=params.get("distance_z_mm"),
            kernel_type=params.get("kernel_type", "ball"),
            distance_l_mm=params.get("distance_l_mm"),
            distance_r_mm=params.get("distance_r_mm"),
            distance_a_mm=params.get("distance_a_mm"),
            distance_p_mm=params.get("distance_p_mm"),
            distance_h_mm=params.get("distance_h_mm"),
            distance_f_mm=params.get("distance_f_mm"),
        )
        return

    if canonical == "avoid_margin":
        if len(structures) < 2:
            raise LegacySynthesisError("avoid_margin needs a source and an avoid")
        from ..models import AvoidMarginRuleConfig

        AvoidMarginRuleConfig.objects.create(
            pipeline_rule=rule,
            variant=params.get("variant", "UNIFORM"),
            source=structures[0],
            avoid=structures[1],
            margin_mm=params.get("margin_mm"),
            margin_x_mm=params.get("margin_x_mm"),
            margin_y_mm=params.get("margin_y_mm"),
            margin_z_mm=params.get("margin_z_mm"),
            kernel_type=params.get("kernel_type", "ball"),
            margin_l_mm=params.get("margin_l_mm"),
            margin_r_mm=params.get("margin_r_mm"),
            margin_a_mm=params.get("margin_a_mm"),
            margin_p_mm=params.get("margin_p_mm"),
            margin_h_mm=params.get("margin_h_mm"),
            margin_f_mm=params.get("margin_f_mm"),
        )
        return

    if canonical == "intensity_range":
        _build_intensity(rule, structures, params)
        return

    raise LegacySynthesisError(f"No config builder for operation {canonical!r}")
