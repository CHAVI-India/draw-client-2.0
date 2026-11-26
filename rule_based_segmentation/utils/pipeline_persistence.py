"""Pipeline (de)serialization shared by the RBS UI and the template-driven path.

Centralizes turning the builder's JSON into ``PipelineRule`` rows (and back), so
both the RBS pipeline views and the ``dicom_handler`` additional-structure views
author pipelines through one code path.

Public helpers:
- ``parse_pipeline_data(post_data)`` -> dict | None
- ``save_pipeline_from_dict(data, user, pipeline=None)`` -> SegmentationPipeline
- ``pipeline_data_from_pipeline(pipeline)`` -> dict (for the builder)
- ``pin_final_rule(pipeline, name, color, roi_type)`` (binding-aware finalization)
"""

import json

from django.db import transaction

from ..models import (
    AvoidMarginRuleConfig,
    BooleanExpressionNode,
    CleanupRuleConfig,
    CropBoundary,
    CropRuleConfig,
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


# ---------------------------------------------------------------------------
# Save direction (builder JSON -> rows)
# ---------------------------------------------------------------------------

def parse_pipeline_data(post_data):
    """Parse pipeline JSON from form data. Returns a dict or None."""
    json_data = post_data.get("pipeline_data")
    if not json_data:
        return None
    try:
        return json.loads(json_data)
    except json.JSONDecodeError:
        return None


def referenced_structure_names(rules):
    """Union of all structure names a rule list references (inputs only)."""
    names = set()
    for rule in rules:
        names |= _collect_required_structure_names(rule)
    return names


def save_pipeline_from_dict(data, user, pipeline=None):
    """Create or update a pipeline and all its rules from parsed builder JSON."""
    rules = data.get("rules", [])
    _validate_pipeline_rules(rules)

    with transaction.atomic():
        structures = data.get("structures", [])
        if pipeline is None:
            pipeline = SegmentationPipeline.objects.create(
                name=data.get("name", "Unnamed Pipeline"),
                description=data.get("description", ""),
                is_public=data.get("is_public", False),
                created_by=user,
                structures=structures,
            )
        else:
            pipeline.name = data.get("name", pipeline.name)
            pipeline.description = data.get("description", pipeline.description)
            pipeline.is_public = data.get("is_public", pipeline.is_public)
            pipeline.structures = structures
            pipeline.save()
            pipeline.rules.all().delete()

        for idx, rule_data in enumerate(rules, start=1):
            _save_rule(pipeline, idx, rule_data)

    return pipeline


def _validate_pipeline_rules(rules):
    """Validate pipeline rule ordering and output-name uniqueness."""
    name_max_len = PipelineRule._meta.get_field("name").max_length

    output_names = set()
    for idx, rule in enumerate(rules, start=1):
        name = rule.get("name", "").strip()
        if not name:
            raise ValueError(f"Rule {idx} has no output ROI name.")
        if len(name) > name_max_len:
            raise ValueError(
                f"Rule {idx} output ROI name '{name}' is too long "
                f"({len(name)} characters); the maximum is {name_max_len} characters."
            )
        if name in output_names:
            raise ValueError(
                f"Rule '{name}' is used more than once. Output ROI names must be unique."
            )
        output_names.add(name)

    produced_by_index = {}
    for idx, rule in enumerate(rules, start=1):
        produced_by_index[rule.get("name", "").strip()] = idx

    for idx, rule in enumerate(rules, start=1):
        for required in _collect_required_structure_names(rule):
            required_source = produced_by_index.get(required)
            if required_source is not None and required_source >= idx:
                raise ValueError(
                    f"Rule '{rule.get('name')}' references '{required}', which is produced by "
                    f"rule {required_source}. Move the source rule before this rule."
                )


def _collect_required_structure_names(rule):
    """Collect structure names referenced by a rule from builder JSON."""
    names = set()
    rule_type = rule.get("rule_type")
    config = rule.get("config", {})

    if rule_type == "BOOLEAN":
        _collect_boolean_operand_names(config, names)
    elif rule_type == "INTENSITY":
        if config.get("seed_type") == "STRUCTURE" and config.get("seed_roi"):
            names.add(config["seed_roi"])
        if config.get("boundary_roi"):
            names.add(config["boundary_roi"])
    elif rule_type in ("MARGIN", "CLEANUP"):
        if config.get("source"):
            names.add(config["source"])
    elif rule_type == "CROP":
        if config.get("source"):
            names.add(config["source"])
        for boundary in config.get("boundaries", []):
            if boundary:
                names.add(boundary)
    elif rule_type == "RING":
        if config.get("source"):
            names.add(config["source"])
    elif rule_type == "OVERLAP":
        if config.get("source"):
            names.add(config["source"])
        for other in config.get("others", []):
            if other:
                names.add(other)
    elif rule_type == "EXPAND_SUBTRACT":
        if config.get("source"):
            names.add(config["source"])
        if config.get("subtract"):
            names.add(config["subtract"])
    elif rule_type == "AVOID_MARGIN":
        if config.get("source"):
            names.add(config["source"])
        if config.get("avoid"):
            names.add(config["avoid"])

    return names


def _collect_boolean_operand_names(config, names):
    """Recursively collect ROI names from a boolean expression config."""
    if config.get("operation"):
        for operand in config.get("operands", []):
            _collect_boolean_operand_names(operand, names)
    elif config.get("name"):
        names.add(config["name"])


def _save_rule(pipeline, order, rule_data):
    """Create a PipelineRule and its related configuration."""
    rule = PipelineRule.objects.create(
        pipeline=pipeline,
        order=order,
        rule_type=rule_data.get("rule_type"),
        name=(rule_data.get("name") or "").strip(),
        output_action=rule_data.get("output_action", "CREATE_NEW"),
        output_color=rule_data.get("output_color") or "255\\255\\0",
        output_roi_type=rule_data.get("output_roi_type", "ORGAN"),
    )

    config = rule_data.get("config", {})
    if rule.rule_type == "BOOLEAN":
        _save_boolean_tree(rule, config)
    elif rule.rule_type == "INTENSITY":
        _save_intensity_config(rule, config)
    elif rule.rule_type == "MARGIN":
        _save_margin_config(rule, config)
    elif rule.rule_type == "CROP":
        _save_crop_config(rule, config)
    elif rule.rule_type == "CLEANUP":
        _save_cleanup_config(rule, config)
    elif rule.rule_type == "RING":
        _save_ring_config(rule, config)
    elif rule.rule_type == "OVERLAP":
        _save_overlap_config(rule, config)
    elif rule.rule_type == "EXPAND_SUBTRACT":
        _save_expand_subtract_config(rule, config)
    elif rule.rule_type == "AVOID_MARGIN":
        _save_avoid_margin_config(rule, config)

    return rule


def _save_boolean_tree(rule, config, parent=None):
    """Recursively save a boolean expression tree."""
    node_type = "OPERATION" if config.get("operation") else "ROI"
    node = BooleanExpressionNode.objects.create(
        pipeline_rule=rule,
        parent=parent,
        node_type=node_type,
        operation_type=config.get("operation") if node_type == "OPERATION" else None,
        roi_name=config.get("name") if node_type == "ROI" else None,
        order=parent.children.count() + 1 if parent else 1,
    )
    if node_type == "OPERATION":
        for child_data in config.get("operands", []):
            _save_boolean_tree(rule, child_data, parent=node)
    return node


def _save_intensity_config(rule, config):
    intensity_config = IntensityRuleConfig.objects.create(
        pipeline_rule=rule,
        seed_type=config.get("seed_type", "IMAGE"),
        seed_roi=config.get("seed_roi", ""),
        boundary_roi=config.get("boundary_roi", ""),
        modality_hint=config.get("modality_hint", ""),
    )
    for idx, r in enumerate(config.get("ranges", []), start=1):
        IntensityRange.objects.create(
            intensity_rule=intensity_config,
            min_value=r.get("min"),
            max_value=r.get("max"),
            order=idx,
        )


def _save_margin_config(rule, config):
    MarginRuleConfig.objects.create(
        pipeline_rule=rule,
        variant=config.get("variant", "UNIFORM"),
        source=config.get("source", ""),
        margin_mm=config.get("margin_mm"),
        margin_x_mm=config.get("margin_x_mm"),
        margin_y_mm=config.get("margin_y_mm"),
        margin_z_mm=config.get("margin_z_mm"),
        kernel_type=config.get("kernel_type", "ball"),
        margin_l_mm=config.get("margin_l_mm"),
        margin_r_mm=config.get("margin_r_mm"),
        margin_a_mm=config.get("margin_a_mm"),
        margin_p_mm=config.get("margin_p_mm"),
        margin_h_mm=config.get("margin_h_mm"),
        margin_f_mm=config.get("margin_f_mm"),
    )


def _save_crop_config(rule, config):
    crop_config = CropRuleConfig.objects.create(
        pipeline_rule=rule,
        source=config.get("source", ""),
    )
    for idx, boundary in enumerate(config.get("boundaries", []), start=1):
        CropBoundary.objects.create(
            crop_rule=crop_config,
            boundary_roi=boundary,
            order=idx,
        )


def _save_cleanup_config(rule, config):
    CleanupRuleConfig.objects.create(
        pipeline_rule=rule,
        operation=config.get("operation", ""),
        source=config.get("source", ""),
        smoothing_mm=config.get("smoothing_mm"),
        iterations=config.get("iterations"),
        min_size_mm3=config.get("min_size_mm3"),
        fully_connected=config.get("fully_connected"),
        sigma_mm=config.get("sigma_mm"),
        threshold=config.get("threshold"),
        n=config.get("n"),
        gap_size_mm=config.get("gap_size_mm"),
        protrusion_size_mm=config.get("protrusion_size_mm"),
    )


def _save_ring_config(rule, config):
    RingRuleConfig.objects.create(
        pipeline_rule=rule,
        variant=config.get("variant", "UNIFORM"),
        source=config.get("source", ""),
        thickness_mm=config.get("thickness_mm"),
        thickness_x_mm=config.get("thickness_x_mm"),
        thickness_y_mm=config.get("thickness_y_mm"),
        thickness_z_mm=config.get("thickness_z_mm"),
        kernel_type=config.get("kernel_type", "ball"),
        thickness_l_mm=config.get("thickness_l_mm"),
        thickness_r_mm=config.get("thickness_r_mm"),
        thickness_a_mm=config.get("thickness_a_mm"),
        thickness_p_mm=config.get("thickness_p_mm"),
        thickness_h_mm=config.get("thickness_h_mm"),
        thickness_f_mm=config.get("thickness_f_mm"),
    )


def _save_overlap_config(rule, config):
    overlap_config = OverlapRuleConfig.objects.create(
        pipeline_rule=rule,
        source=config.get("source", ""),
    )
    for idx, other in enumerate(config.get("others", []), start=1):
        if other:
            OverlapOther.objects.create(
                overlap_rule=overlap_config,
                other_roi=other,
                order=idx,
            )


def _save_expand_subtract_config(rule, config):
    ExpandSubtractRuleConfig.objects.create(
        pipeline_rule=rule,
        variant=config.get("variant", "UNIFORM"),
        source=config.get("source", ""),
        subtract=config.get("subtract", ""),
        distance_mm=config.get("distance_mm"),
        distance_x_mm=config.get("distance_x_mm"),
        distance_y_mm=config.get("distance_y_mm"),
        distance_z_mm=config.get("distance_z_mm"),
        kernel_type=config.get("kernel_type", "ball"),
        distance_l_mm=config.get("distance_l_mm"),
        distance_r_mm=config.get("distance_r_mm"),
        distance_a_mm=config.get("distance_a_mm"),
        distance_p_mm=config.get("distance_p_mm"),
        distance_h_mm=config.get("distance_h_mm"),
        distance_f_mm=config.get("distance_f_mm"),
    )


def _save_avoid_margin_config(rule, config):
    AvoidMarginRuleConfig.objects.create(
        pipeline_rule=rule,
        variant=config.get("variant", "UNIFORM"),
        source=config.get("source", ""),
        avoid=config.get("avoid", ""),
        margin_mm=config.get("margin_mm"),
        margin_x_mm=config.get("margin_x_mm"),
        margin_y_mm=config.get("margin_y_mm"),
        margin_z_mm=config.get("margin_z_mm"),
        kernel_type=config.get("kernel_type", "ball"),
        margin_l_mm=config.get("margin_l_mm"),
        margin_r_mm=config.get("margin_r_mm"),
        margin_a_mm=config.get("margin_a_mm"),
        margin_p_mm=config.get("margin_p_mm"),
        margin_h_mm=config.get("margin_h_mm"),
        margin_f_mm=config.get("margin_f_mm"),
    )


# ---------------------------------------------------------------------------
# Load direction (rows -> builder JSON)
# ---------------------------------------------------------------------------

def _rgb_dicom_to_hex(color_string):
    if not color_string:
        return "#FFFF00"
    parts = [p.strip() for p in color_string.split("\\")]
    if len(parts) != 3:
        return "#FFFF00"
    try:
        return "#" + "".join(f"{int(p):02X}" for p in parts)
    except ValueError:
        return "#FFFF00"


def _boolean_node_to_json(node):
    if node.node_type == "ROI":
        return {"name": node.roi_name}
    return {
        "operation": node.operation_type,
        "operands": [
            _boolean_node_to_json(child)
            for child in node.children.all().order_by("order")
        ],
    }


def rule_to_json(rule):
    """Convert a saved PipelineRule to the builder's rule format."""
    data = {
        "rule_type": rule.rule_type,
        "name": rule.name,
        "output_action": rule.output_action,
        "output_color": _rgb_dicom_to_hex(rule.output_color),
        "output_roi_type": rule.output_roi_type,
        "config": {},
    }

    if rule.rule_type == "BOOLEAN":
        root = rule.boolean_nodes.filter(parent=None).first()
        data["config"] = _boolean_node_to_json(root) if root else {}
    elif rule.rule_type == "INTENSITY":
        cfg = rule.intensity_config
        data["config"] = {
            "seed_type": cfg.seed_type,
            "seed_roi": cfg.seed_roi or "",
            "boundary_roi": cfg.boundary_roi or "",
            "modality_hint": cfg.modality_hint or "",
            "ranges": [
                {"min": r.min_value, "max": r.max_value} for r in cfg.ranges.all()
            ],
        }
    elif rule.rule_type == "MARGIN":
        cfg = rule.margin_config
        data["config"] = {
            "variant": cfg.variant,
            "source": cfg.source,
            "margin_mm": cfg.margin_mm,
            "margin_x_mm": cfg.margin_x_mm,
            "margin_y_mm": cfg.margin_y_mm,
            "margin_z_mm": cfg.margin_z_mm,
            "kernel_type": cfg.kernel_type,
            "margin_l_mm": cfg.margin_l_mm,
            "margin_r_mm": cfg.margin_r_mm,
            "margin_a_mm": cfg.margin_a_mm,
            "margin_p_mm": cfg.margin_p_mm,
            "margin_h_mm": cfg.margin_h_mm,
            "margin_f_mm": cfg.margin_f_mm,
        }
    elif rule.rule_type == "CROP":
        cfg = rule.crop_config
        data["config"] = {
            "source": cfg.source,
            "boundaries": [b.boundary_roi for b in cfg.boundaries.all()],
        }
    elif rule.rule_type == "CLEANUP":
        cfg = rule.cleanup_config
        data["config"] = {
            "operation": cfg.operation,
            "source": cfg.source,
            "smoothing_mm": cfg.smoothing_mm,
            "iterations": cfg.iterations,
            "min_size_mm3": cfg.min_size_mm3,
            "fully_connected": cfg.fully_connected,
            "sigma_mm": cfg.sigma_mm,
            "threshold": cfg.threshold,
            "n": cfg.n,
            "gap_size_mm": cfg.gap_size_mm,
            "protrusion_size_mm": cfg.protrusion_size_mm,
        }
    elif rule.rule_type == "RING":
        cfg = rule.ring_config
        data["config"] = {
            "variant": cfg.variant,
            "source": cfg.source,
            "thickness_mm": cfg.thickness_mm,
            "thickness_x_mm": cfg.thickness_x_mm,
            "thickness_y_mm": cfg.thickness_y_mm,
            "thickness_z_mm": cfg.thickness_z_mm,
            "kernel_type": cfg.kernel_type,
            "thickness_l_mm": cfg.thickness_l_mm,
            "thickness_r_mm": cfg.thickness_r_mm,
            "thickness_a_mm": cfg.thickness_a_mm,
            "thickness_p_mm": cfg.thickness_p_mm,
            "thickness_h_mm": cfg.thickness_h_mm,
            "thickness_f_mm": cfg.thickness_f_mm,
        }
    elif rule.rule_type == "OVERLAP":
        cfg = rule.overlap_config
        data["config"] = {
            "source": cfg.source,
            "others": [o.other_roi for o in cfg.others.all().order_by("order")],
        }
    elif rule.rule_type == "EXPAND_SUBTRACT":
        cfg = rule.expand_subtract_config
        data["config"] = {
            "variant": cfg.variant,
            "source": cfg.source,
            "subtract": cfg.subtract,
            "distance_mm": cfg.distance_mm,
            "distance_x_mm": cfg.distance_x_mm,
            "distance_y_mm": cfg.distance_y_mm,
            "distance_z_mm": cfg.distance_z_mm,
            "kernel_type": cfg.kernel_type,
            "distance_l_mm": cfg.distance_l_mm,
            "distance_r_mm": cfg.distance_r_mm,
            "distance_a_mm": cfg.distance_a_mm,
            "distance_p_mm": cfg.distance_p_mm,
            "distance_h_mm": cfg.distance_h_mm,
            "distance_f_mm": cfg.distance_f_mm,
        }
    elif rule.rule_type == "AVOID_MARGIN":
        cfg = rule.avoid_margin_config
        data["config"] = {
            "variant": cfg.variant,
            "source": cfg.source,
            "avoid": cfg.avoid,
            "margin_mm": cfg.margin_mm,
            "margin_x_mm": cfg.margin_x_mm,
            "margin_y_mm": cfg.margin_y_mm,
            "margin_z_mm": cfg.margin_z_mm,
            "kernel_type": cfg.kernel_type,
            "margin_l_mm": cfg.margin_l_mm,
            "margin_r_mm": cfg.margin_r_mm,
            "margin_a_mm": cfg.margin_a_mm,
            "margin_p_mm": cfg.margin_p_mm,
            "margin_h_mm": cfg.margin_h_mm,
            "margin_f_mm": cfg.margin_f_mm,
        }

    return data


def pipeline_data_from_pipeline(pipeline):
    """Build the builder payload for an existing pipeline (or empty if None)."""
    if pipeline is None:
        return {"rules": [], "structures": []}
    return {
        "rules": [rule_to_json(r) for r in pipeline.rules.all().order_by("order")],
        "structures": list(pipeline.structures or []),
    }


# ---------------------------------------------------------------------------
# Binding-aware finalization (template-driven additional structures)
# ---------------------------------------------------------------------------

def pin_final_rule(pipeline, name, color, roi_type):
    """Pin the last rule to the target ROI identity; mark the rest INTERMEDIATE.

    This mirrors ``synthesize_rules``: for a single target additional structure,
    the exported ROI is named ``name`` with the binding's color/type, and every
    earlier rule is held in memory (INTERMEDIATE).
    """
    rules = list(pipeline.rules.all().order_by("order"))
    if not rules:
        return pipeline
    for rule in rules[:-1]:
        if rule.output_action != "INTERMEDIATE":
            rule.output_action = "INTERMEDIATE"
            rule.save(update_fields=["output_action"])
    final = rules[-1]
    final.name = name
    final.output_action = "CREATE_NEW"
    if color:
        final.output_color = color
    if roi_type:
        final.output_roi_type = roi_type
    final.save()
    return pipeline
