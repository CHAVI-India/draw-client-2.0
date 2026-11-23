"""
Shared execution dispatcher for structure operations.

:func:`execute_operation` maps a catalog operation id + its input structure
**roles** + parameters to a resulting :class:`SimpleITK.Image` mask, using the
low-level primitives in :mod:`.operations` and :mod:`.advanced_operations`.

Both the auto-segmentation pipeline executor (``dicom_handler``) and the
rule-based segmentation engine (``rule_based_segmentation``) route their
per-operation work through this single function, so the semantics of every
operation live in exactly one place.

Roles
-----
A role is a named input slot of an operation (see
:mod:`.operation_catalog`). The ``roles`` argument maps each role name to:

* a single :class:`SimpleITK.Image` for ``'single'`` roles, or
* an ordered ``list`` of :class:`SimpleITK.Image` for ``'multiple'`` roles.

Boolean operations take ``{'primary': mask, 'others': [mask, ...]}``;
boundary/composite operations take their named roles (``source``,
``boundaries``, ``subtract``, ``avoid``, ``seed``, ...).
"""

from typing import Any, Dict, List, Optional

import SimpleITK as sitk

from . import advanced_operations, operations
from .operation_catalog import VARIANT_ANISO, get_operation, resolve_operation_id

# The six patient-anatomical directions used by the canonical
# six-directional params (``{prefix}_l_mm`` ... ``{prefix}_f_mm``).
_DIRECTIONS = ("l", "r", "a", "p", "h", "f")


class OperationExecutionError(Exception):
    """Raised when an operation cannot be executed (bad roles/params)."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _single(roles: Dict[str, Any], name: str, spec_id: str) -> sitk.Image:
    value = roles.get(name)
    if value is None:
        raise OperationExecutionError(
            f"Operation '{spec_id}' is missing required role '{name}'"
        )
    if isinstance(value, list):
        if len(value) == 1:
            return value[0]
        raise OperationExecutionError(
            f"Operation '{spec_id}' role '{name}' expects a single mask, got {len(value)}"
        )
    return value


def _multiple(roles: Dict[str, Any], name: str, spec_id: str, required: bool = True) -> List[sitk.Image]:
    value = roles.get(name)
    if value is None:
        if required:
            raise OperationExecutionError(
                f"Operation '{spec_id}' is missing required role '{name}'"
            )
        return []
    if isinstance(value, list):
        return value
    # Tolerate a single mask where a list is expected.
    return [value]


def _fold(mask: sitk.Image, others: List[sitk.Image], fn) -> sitk.Image:
    """Fold ``fn`` over ``others`` starting from ``mask`` (in order)."""
    for other in others:
        mask = fn(mask, other)
    return mask


def _directional_margins(params: Dict[str, Any], prefix: str) -> Optional[Dict[str, float]]:
    """Return the six-directional margin dict (mm) if the op was given any of
    the canonical per-direction params (``{prefix}_l_mm`` ... ``{prefix}_f_mm``),
    else ``None`` (caller falls back to legacy params)."""
    if not any(f"{prefix}_{k}_mm" in params for k in _DIRECTIONS):
        return None
    return {k: float(params.get(f"{prefix}_{k}_mm", 0.0) or 0.0) for k in _DIRECTIONS}


def _expand(mask: sitk.Image, params: Dict[str, Any], prefix: str) -> sitk.Image:
    """Expand ``mask`` by the six per-direction distances (mm) for ``prefix``.

    The canonical params are ``{prefix}_l_mm`` ... ``{prefix}_f_mm`` (positive
    = expand toward that side, 0 = unchanged). To apply the same distance on
    every side, pass the same value in all six. Previously-saved pipelines
    that still carry the legacy ``variant`` / ``{prefix}_mm`` /
    ``{prefix}_x/y/z_mm`` / ``kernel_type`` params keep working through the
    legacy primitives (uniform ball dilation / per-axis anisotropic margin).
    """
    margins = _directional_margins(params, prefix)
    if margins is not None:
        return operations.apply_directional_margin(mask, margins)
    variant = params.get("variant", "UNIFORM")
    if variant == VARIANT_ANISO:
        return operations.apply_anisotropic_margin(
            mask,
            params[f"{prefix}_x_mm"],
            params[f"{prefix}_y_mm"],
            params[f"{prefix}_z_mm"],
        )
    return operations.apply_uniform_margin(
        mask,
        params.get(f"{prefix}_mm", 0.0),
        params.get("kernel_type", "ball"),
    )


def _margin_directional(params: Dict[str, Any], prefix: str = "margin") -> Dict[str, float]:
    """Return the six-directional margin dict (mm) for the canonical ``margin`` op.

    Prefers the per-direction params (``{prefix}_l_mm`` ...
    ``{prefix}_f_mm``) and maps legacy uniform/anisotropic params so
    previously-saved pipelines keep working. Legacy anisotropic (symmetric per
    array axis) is mapped to the two anatomical directions along that axis
    (axial assumption).
    """
    keys = _DIRECTIONS
    if any(f"{prefix}_{k}_mm" in params for k in keys):
        return {k: float(params.get(f"{prefix}_{k}_mm", 0.0) or 0.0) for k in keys}
    variant = params.get("variant", "UNIFORM")
    if variant == "ANISOTROPIC":
        x = float(params.get("margin_x_mm", 0.0) or 0.0)
        y = float(params.get("margin_y_mm", 0.0) or 0.0)
        z = float(params.get("margin_z_mm", 0.0) or 0.0)
        return {"h": x, "f": x, "a": y, "p": y, "l": z, "r": z}
    m = float(params.get("margin_mm", 0.0) or 0.0)
    return {k: m for k in keys}


# ---------------------------------------------------------------------------
# Per-operation handlers
# ---------------------------------------------------------------------------


def _h_margin(roles, params, image=None):
    source = _single(roles, "source", "margin")
    margins = _margin_directional(params, "margin")
    return operations.apply_directional_margin(source, margins)


def _h_union(roles, params, image=None):
    primary = _single(roles, "primary", "union")
    others = _multiple(roles, "others", "union")
    return _fold(primary, others, operations.boolean_union)


def _h_intersection(roles, params, image=None):
    primary = _single(roles, "primary", "intersection")
    others = _multiple(roles, "others", "intersection")
    return _fold(primary, others, operations.boolean_intersection)


def _h_subtract(roles, params, image=None):
    primary = _single(roles, "primary", "subtract")
    others = _multiple(roles, "others", "subtract")
    result = _fold(primary, others, operations.boolean_subtraction)
    margin_mm = params.get("margin_mm", 0.0)
    if margin_mm:
        result = operations.apply_uniform_margin(result, margin_mm, "ball")
    return result


def _h_xor(roles, params, image=None):
    primary = _single(roles, "primary", "xor")
    others = _multiple(roles, "others", "xor")
    return _fold(primary, others, operations.boolean_xor)


def _h_crop_to_boundary(roles, params, image=None):
    source = _single(roles, "source", "crop_to_boundary")
    boundaries = _multiple(roles, "boundaries", "crop_to_boundary")
    if not boundaries:
        raise OperationExecutionError("crop_to_boundary requires at least one boundary")
    result = source
    for boundary in boundaries:
        result = operations.boolean_intersection(result, boundary)
    return result


def _h_ring(roles, params, image=None):
    source = _single(roles, "source", "ring")
    expanded = _expand(source, params, "thickness")
    return operations.boolean_subtraction(expanded, source)


def _h_overlap(roles, params, image=None):
    source = _single(roles, "source", "overlap")
    others = _multiple(roles, "others", "overlap")
    if not others:
        raise OperationExecutionError("overlap requires at least one other structure")
    combined = others[0]
    for other in others[1:]:
        combined = operations.boolean_union(combined, other)
    return operations.boolean_intersection(source, combined)


def _h_expand_subtract(roles, params, image=None):
    source = _single(roles, "source", "expand_subtract")
    subtract = _single(roles, "subtract", "expand_subtract")
    expanded = _expand(source, params, "distance")
    return operations.boolean_subtraction(expanded, subtract)


def _h_avoid_margin(roles, params, image=None):
    source = _single(roles, "source", "avoid_margin")
    avoid = _single(roles, "avoid", "avoid_margin")
    expanded = _expand(avoid, params, "margin")
    return operations.boolean_subtraction(source, expanded)


def _h_smooth(roles, params, image=None):
    source = _single(roles, "source", "smooth")
    return advanced_operations.smooth_structure(
        source,
        smoothing_mm=params.get("smoothing_mm", 1.0),
        iterations=params.get("iterations", 1),
    )


def _h_gaussian_smooth(roles, params, image=None):
    source = _single(roles, "source", "gaussian_smooth")
    return advanced_operations.gaussian_smooth(
        source,
        sigma_mm=params.get("sigma_mm", 1.0),
        threshold=params.get("threshold", 0.5),
    )


def _h_fill_holes(roles, params, image=None):
    source = _single(roles, "source", "fill_holes")
    return advanced_operations.fill_holes(
        source, fully_connected=params.get("fully_connected", False)
    )


def _h_remove_small_components(roles, params, image=None):
    source = _single(roles, "source", "remove_small_components")
    return advanced_operations.remove_small_components(
        source, min_size_mm3=params.get("min_size_mm3", 100.0)
    )


def _h_keep_largest(roles, params, image=None):
    return advanced_operations.keep_largest_component(_single(roles, "source", "keep_largest"))


def _h_keep_n_largest(roles, params, image=None):
    source = _single(roles, "source", "keep_n_largest")
    return advanced_operations.keep_n_largest_components(source, n=params.get("n", 1))


def _h_close_gaps(roles, params, image=None):
    source = _single(roles, "source", "close_gaps")
    return advanced_operations.close_gaps(source, gap_size_mm=params.get("gap_size_mm", 2.0))


def _h_remove_protrusions(roles, params, image=None):
    source = _single(roles, "source", "remove_protrusions")
    return advanced_operations.remove_protrusions(
        source, protrusion_size_mm=params.get("protrusion_size_mm", 2.0)
    )


def _h_intensity_range(roles, params, image=None):
    if image is None:
        raise OperationExecutionError("intensity_range requires the CT image")
    # Lazy import to avoid a module-load-time dependency on the RBS package.
    from rule_based_segmentation.utils.intensity_segmentation import (
        intensity_range_segmentation,
    )

    seed = roles.get("seed")
    boundary = roles.get("boundary")
    ranges = params.get("ranges", [])
    return intensity_range_segmentation(image, ranges, seed_mask=seed, boundary_mask=boundary)


_HANDLERS = {
    "margin": _h_margin,
    "union": _h_union,
    "intersection": _h_intersection,
    "subtract": _h_subtract,
    "xor": _h_xor,
    "crop_to_boundary": _h_crop_to_boundary,
    "ring": _h_ring,
    "overlap": _h_overlap,
    "expand_subtract": _h_expand_subtract,
    "avoid_margin": _h_avoid_margin,
    "smooth": _h_smooth,
    "gaussian_smooth": _h_gaussian_smooth,
    "fill_holes": _h_fill_holes,
    "remove_small_components": _h_remove_small_components,
    "keep_largest": _h_keep_largest,
    "keep_n_largest": _h_keep_n_largest,
    "close_gaps": _h_close_gaps,
    "remove_protrusions": _h_remove_protrusions,
    "intensity_range": _h_intensity_range,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def execute_operation(
    op_id: str,
    roles: Dict[str, Any],
    params: Optional[Dict[str, Any]] = None,
    image: Optional[sitk.Image] = None,
) -> sitk.Image:
    """Execute one catalog operation and return the result mask.

    Args:
        op_id: canonical or legacy operation id (see
            :func:`operation_catalog.resolve_operation_id`).
        roles: mapping of role name -> mask (single) or list of masks
            (multiple).
        params: operation parameters (see the catalog schema).
        image: optional CT image, required for ``intensity_range``.

    Returns:
        The resulting binary :class:`SimpleITK.Image` mask.

    Raises:
        KeyError: if ``op_id`` is unknown.
        OperationExecutionError: if roles/params are invalid for the op.
    """
    params = dict(params or {})
    canonical = resolve_operation_id(op_id)
    if canonical not in _HANDLERS:
        raise KeyError(f"No execution handler for operation '{canonical}'")
    # Legacy pipeline-builder aliases carry a non-negative ``margin_mm`` and
    # rely on the op id for direction: ``expand`` grows, ``contract`` shrinks.
    # Apply that sign so both map onto the canonical signed ``margin`` op.
    if canonical == "margin" and op_id == "contract":
        for key in (
            "margin_mm",
            "margin_x_mm", "margin_y_mm", "margin_z_mm",
            "margin_l_mm", "margin_r_mm", "margin_a_mm",
            "margin_p_mm", "margin_h_mm", "margin_f_mm",
        ):
            if key in params and params[key]:
                params[key] = -float(params[key])
    # Validate that every required role is present (raises a clear error).
    spec = get_operation(canonical)
    for role in spec.structure_roles:
        value = roles.get(role.name)
        if role.required and value is None:
            raise OperationExecutionError(
                f"Operation '{canonical}' requires role '{role.name}'"
            )
        if role.kind == "multiple" and value is not None and not isinstance(value, list):
            # Tolerated in _multiple(); nothing to enforce here.
            pass
    return _HANDLERS[canonical](roles, params, image)


def supported_operation_ids() -> List[str]:
    """Canonical operation ids that have an execution handler."""
    return list(_HANDLERS.keys())


__all__ = [
    "OperationExecutionError",
    "execute_operation",
    "supported_operation_ids",
]
