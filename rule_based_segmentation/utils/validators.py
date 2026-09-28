"""Rule-type-specific validators for pipeline rules."""

from django.core.exceptions import ValidationError


def validate_boolean_rule(rule):
    """Validate a boolean rule has exactly one well-formed tree."""
    try:
        root_nodes = rule.boolean_nodes.filter(parent=None)
    except Exception:
        return

    count = root_nodes.count()
    if count == 0:
        raise ValidationError({"__all__": "Boolean rule requires at least one expression node."})
    if count > 1:
        raise ValidationError({"__all__": "Boolean rule must have exactly one root expression node."})

    root = root_nodes.first()
    _validate_boolean_node(rule, root)


def _validate_boolean_node(rule, node):
    """Recursively validate a boolean expression node."""
    node.clean()

    if node.node_type == "OPERATION":
        children = rule.boolean_nodes.filter(parent=node).order_by("order")
        child_count = children.count()

        if node.operation_type == "XOR":
            if child_count != 2:
                raise ValidationError(
                    {"__all__": f"XOR operation requires exactly 2 operands, got {child_count}."}
                )
        elif child_count < 2:
            raise ValidationError(
                {"__all__": f"{node.operation_type} operation requires at least 2 operands, got {child_count}."}
            )

        for child in children:
            _validate_boolean_node(rule, child)
    else:
        if rule.boolean_nodes.filter(parent=node).exists():
            raise ValidationError({"__all__": f"ROI node '{node.roi_name}' cannot have children."})


def validate_intensity_rule(rule):
    """Validate an intensity-range rule."""
    try:
        config = rule.intensity_config
    except Exception:
        return

    if config.seed_type not in {"STRUCTURE", "IMAGE", "BOUNDARY"}:
        raise ValidationError({"seed_type": "Invalid seed type."})

    if config.seed_type == "STRUCTURE" and not config.seed_roi:
        raise ValidationError({"seed_roi": "Seed structure is required when seed type is 'Structure'."})

    if config.seed_type == "BOUNDARY" and not config.boundary_roi:
        raise ValidationError({"boundary_roi": "Boundary structure is required when seed type is 'Boundary'."})

    try:
        ranges = config.ranges.all()
    except Exception:
        ranges = []

    if not ranges:
        raise ValidationError({"__all__": "At least one intensity range is required."})

    for r in ranges:
        r.clean()


def validate_margin_rule(rule):
    """Validate a margin rule."""
    try:
        config = rule.margin_config
    except Exception:
        return

    if config.variant not in {"UNIFORM", "ANISOTROPIC"}:
        raise ValidationError({"variant": "Margin variant must be Uniform or Anisotropic."})

    if not config.source:
        raise ValidationError({"source": "Source structure is required."})

    if config.variant == "UNIFORM":
        if config.margin_mm is None:
            raise ValidationError({"margin_mm": "Uniform margin requires margin_mm."})
    else:
        missing = []
        if config.margin_x_mm is None:
            missing.append("margin_x_mm")
        if config.margin_y_mm is None:
            missing.append("margin_y_mm")
        if config.margin_z_mm is None:
            missing.append("margin_z_mm")
        if missing:
            raise ValidationError(
                {f: "Anisotropic margin requires this value." for f in missing}
            )


def validate_crop_rule(rule):
    """Validate a crop-to-boundary rule."""
    try:
        config = rule.crop_config
    except Exception:
        return

    if not config.source:
        raise ValidationError({"source": "Source structure is required."})

    try:
        boundaries = config.boundaries.all()
    except Exception:
        boundaries = []

    if not boundaries:
        raise ValidationError({"__all__": "At least one boundary structure is required."})


def validate_cleanup_rule(rule):
    """Validate a cleanup/refinement rule."""
    try:
        config = rule.cleanup_config
    except Exception:
        return

    if not config.source:
        raise ValidationError({"source": "Source structure is required."})

    required_params = {
        "SMOOTH_STRUCTURE": ["smoothing_mm", "iterations"],
        "GAUSSIAN_SMOOTH": ["sigma_mm", "threshold"],
        "FILL_HOLES": ["fully_connected"],
        "REMOVE_SMALL_COMPONENTS": ["min_size_mm3"],
        "KEEP_LARGEST_COMPONENT": [],
    }

    params = required_params.get(config.operation, [])
    missing = [p for p in params if getattr(config, p) is None]
    if missing:
        raise ValidationError(
            {f: f"{config.operation} requires this parameter." for f in missing}
        )
