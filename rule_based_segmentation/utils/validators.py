"""Rule-type-specific validators for pipeline rules."""

from django.core.exceptions import ValidationError


def _has_directional(config, prefix: str) -> bool:
    """True if any of the six per-directional ``{prefix}_{l,r,a,p,h,f}_mm``
    fields is set on a margin-like config."""
    return any(
        getattr(config, f"{prefix}_{k}_mm") is not None
        for k in ("l", "r", "a", "p", "h", "f")
    )


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

    # Six-directional margins (preferred): any set value makes this a
    # directional margin; unset directions are treated as 0 (no change).
    directional = [
        v
        for v in (
            config.margin_l_mm,
            config.margin_r_mm,
            config.margin_a_mm,
            config.margin_p_mm,
            config.margin_h_mm,
            config.margin_f_mm,
        )
        if v is not None
    ]
    if directional:
        return

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
        "KEEP_N_LARGEST_COMPONENT": ["n"],
        "CLOSE_GAPS": ["gap_size_mm"],
        "REMOVE_PROTRUSIONS": ["protrusion_size_mm"],
    }

    params = required_params.get(config.operation, [])
    missing = [p for p in params if getattr(config, p) is None]
    if missing:
        raise ValidationError(
            {f: f"{config.operation} requires this parameter." for f in missing}
        )


def validate_ring_rule(rule):
    """Validate a RING (ring/shell) rule."""
    try:
        config = rule.ring_config
    except Exception:
        return

    if not config.source:
        raise ValidationError({"source": "Source structure is required."})

    # Six-directional thicknesses (preferred): any set value makes this a
    # directional ring; unset directions are treated as 0 (no change).
    if _has_directional(config, "thickness"):
        return

    # Legacy uniform/anisotropic fallback.
    if config.variant not in {"UNIFORM", "ANISOTROPIC"}:
        raise ValidationError({"variant": "Ring variant must be Uniform or Anisotropic."})

    if config.variant == "UNIFORM":
        if config.thickness_mm is None:
            raise ValidationError({"thickness_mm": "Uniform ring requires thickness_mm."})
    else:
        missing = []
        if config.thickness_x_mm is None:
            missing.append("thickness_x_mm")
        if config.thickness_y_mm is None:
            missing.append("thickness_y_mm")
        if config.thickness_z_mm is None:
            missing.append("thickness_z_mm")
        if missing:
            raise ValidationError(
                {f: "Anisotropic ring requires this value." for f in missing}
            )


def validate_overlap_rule(rule):
    """Validate an OVERLAP rule."""
    try:
        config = rule.overlap_config
    except Exception:
        return

    if not config.source:
        raise ValidationError({"source": "Source structure is required."})

    if config.others.count() == 0:
        raise ValidationError({"others": "At least one other structure is required."})


def validate_expand_subtract_rule(rule):
    """Validate an EXPAND_SUBTRACT rule."""
    try:
        config = rule.expand_subtract_config
    except Exception:
        return

    if not config.source:
        raise ValidationError({"source": "Source structure is required."})

    if not config.subtract:
        raise ValidationError({"subtract": "Structure to subtract is required."})

    # Six-directional distances (preferred).
    if _has_directional(config, "distance"):
        return

    # Legacy uniform/anisotropic fallback.
    if config.variant not in {"UNIFORM", "ANISOTROPIC"}:
        raise ValidationError({"variant": "Expand & Subtract variant must be Uniform or Anisotropic."})

    if config.variant == "UNIFORM":
        if config.distance_mm is None:
            raise ValidationError({"distance_mm": "Uniform expand & subtract requires distance_mm."})
    else:
        missing = []
        if config.distance_x_mm is None:
            missing.append("distance_x_mm")
        if config.distance_y_mm is None:
            missing.append("distance_y_mm")
        if config.distance_z_mm is None:
            missing.append("distance_z_mm")
        if missing:
            raise ValidationError(
                {f: "Anisotropic expand & subtract requires this value." for f in missing}
            )


def validate_avoid_margin_rule(rule):
    """Validate an AVOID_MARGIN rule."""
    try:
        config = rule.avoid_margin_config
    except Exception:
        return

    if not config.source:
        raise ValidationError({"source": "Source structure is required."})

    if not config.avoid:
        raise ValidationError({"avoid": "Structure to avoid is required."})

    # Six-directional margins (preferred).
    if _has_directional(config, "margin"):
        return

    # Legacy uniform/anisotropic fallback.
    if config.variant not in {"UNIFORM", "ANISOTROPIC"}:
        raise ValidationError({"variant": "Avoid with Margin variant must be Uniform or Anisotropic."})

    if config.variant == "UNIFORM":
        if config.margin_mm is None:
            raise ValidationError({"margin_mm": "Uniform avoid with margin requires margin_mm."})
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
                {f: "Anisotropic avoid with margin requires this value." for f in missing}
            )
