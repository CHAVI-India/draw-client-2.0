"""
Canonical structure-operation catalog (single source of truth).

Every structure operation available in the app is defined exactly once here,
with:
  * an ``id`` (stable, used by the execution dispatcher and the API),
  * a human name / description / category / icon / color (for the UIs),
  * its **structure roles** — the named input-structure slots it consumes, and
  * its **parameter schema** — the tunable knobs, with types and defaults.

Both the Pipeline Builder (``dicom_handler``) and Rule-Based Segmentation
(``rule_based_segmentation``) render their operation lists from this catalog,
and both executors dispatch through :mod:`.execution` which reads the same
``id``/roles/params. This keeps the two systems offering the SAME operations
and prevents them from drifting apart.

Parameter naming follows the existing RBS model fields so that the RBS rule
configs map 1:1 onto the catalog (e.g. RING uses ``thickness_mm``,
EXPAND_SUBTRACT uses ``distance_mm``, MARGIN/AVOID_MARGIN use ``margin_mm``).
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Choices shared across operations
# ---------------------------------------------------------------------------

VARIANT_UNIFROM = "UNIFORM"
VARIANT_ANISO = "ANISOTROPIC"
VARIANT_CHOICES = [VARIANT_UNIFROM, VARIANT_ANISO]

KERNEL_BALL = "ball"
KERNEL_BOX = "box"
KERNEL_CROSS = "cross"
KERNEL_CHOICES = [KERNEL_BALL, KERNEL_BOX, KERNEL_CROSS]


def _margin_params(prefix: str = "margin") -> List["Parameter"]:
    """Uniform + anisotropic distance knobs for a margin-like operation.

    ``prefix`` selects the field names (``margin_*``, ``thickness_*``,
    ``distance_*``) so the catalog matches the per-rule RBS model fields.
    """
    return [
        Parameter(
            name="variant",
            label="Margin type",
            type="select",
            default=VARIANT_UNIFROM,
            options=list(VARIANT_CHOICES),
        ),
        Parameter(
            name=f"{prefix}_mm",
            label="Margin (mm)",
            type="number",
            default=5.0,
            min=0.0,
            step=0.5,
            show_when={"variant": VARIANT_UNIFROM},
        ),
        Parameter(
            name="kernel_type",
            label="Kernel",
            type="select",
            default=KERNEL_BALL,
            options=list(KERNEL_CHOICES),
            show_when={"variant": VARIANT_UNIFROM},
        ),
        Parameter(
            name=f"{prefix}_x_mm",
            label="Margin X (mm)",
            type="number",
            default=5.0,
            min=0.0,
            step=0.5,
            show_when={"variant": VARIANT_ANISO},
        ),
        Parameter(
            name=f"{prefix}_y_mm",
            label="Margin Y (mm)",
            type="number",
            default=5.0,
            min=0.0,
            step=0.5,
            show_when={"variant": VARIANT_ANISO},
        ),
        Parameter(
            name=f"{prefix}_z_mm",
            label="Margin Z (mm)",
            type="number",
            default=5.0,
            min=0.0,
            step=0.5,
            show_when={"variant": VARIANT_ANISO},
        ),
    ]


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class StructureRole:
    """One named input-structure slot an operation consumes.

    ``kind`` is ``'single'`` (exactly one mask) or ``'multiple'`` (an ordered
    list of masks). For boolean operations the first ``single`` role is the
    primary and the ``multiple`` role holds the operands to combine with.
    """

    name: str
    label: str
    kind: str = "single"
    required: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "kind": self.kind,
            "required": self.required,
        }


@dataclass
class Parameter:
    """A tunable parameter of an operation."""

    name: str
    label: str
    type: str = "number"  # 'number' | 'select' | 'boolean'
    default: Any = None
    min: Optional[float] = None
    step: Optional[float] = None
    options: Optional[List[str]] = None
    show_when: Optional[Dict[str, str]] = None  # e.g. {"variant": "UNIFORM"}

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"name": self.name, "label": self.label, "type": self.type}
        if self.default is not None:
            d["default"] = self.default
        if self.min is not None:
            d["min"] = self.min
        if self.step is not None:
            d["step"] = self.step
        if self.options:
            d["options"] = self.options
        if self.show_when:
            d["show_when"] = self.show_when
        return d


@dataclass
class OperationSpec:
    """Full specification of a single structure operation."""

    id: str
    name: str
    description: str
    category: str
    icon: str
    color: str
    structure_roles: List[StructureRole]
    parameters: List[Parameter] = field(default_factory=list)
    legacy_ids: List[str] = field(default_factory=list)
    requires_image: bool = False  # True for ops that need the CT image

    def to_dict(self, include_legacy: bool = False) -> Dict[str, Any]:
        d = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "icon": self.icon,
            "color": self.color,
            "structure_roles": [r.to_dict() for r in self.structure_roles],
            "parameters": [p.to_dict() for p in self.parameters],
            "requires_image": self.requires_image,
        }
        if include_legacy and self.legacy_ids:
            d["legacy_ids"] = self.legacy_ids
        return d


# ---------------------------------------------------------------------------
# The catalog
# ---------------------------------------------------------------------------

OPERATIONS: Dict[str, OperationSpec] = {
    # ---- Margins ---------------------------------------------------------
    "margin": OperationSpec(
        id="margin",
        name="Margin (Grow / Shrink)",
        description="Expand or contract a structure by a distance (uniform or anisotropic).",
        category="margin",
        icon="⊕",
        color="blue",
        structure_roles=[StructureRole("source", "Source structure")],
        parameters=_margin_params("margin"),
        legacy_ids=["expand", "contract", "margin_uniform", "anisotropic_margin"],
    ),
    # ---- Boolean ---------------------------------------------------------
    "union": OperationSpec(
        id="union",
        name="Union",
        description="Combine structures (keep voxels in any of them).",
        category="boolean",
        icon="∪",
        color="green",
        structure_roles=[
            StructureRole("primary", "Primary structure"),
            StructureRole("others", "With structure(s)", kind="multiple"),
        ],
        legacy_ids=["union"],
    ),
    "intersection": OperationSpec(
        id="intersection",
        name="Intersection",
        description="Keep only the region common to all structures.",
        category="boolean",
        icon="∩",
        color="purple",
        structure_roles=[
            StructureRole("primary", "Primary structure"),
            StructureRole("others", "With structure(s)", kind="multiple"),
        ],
        legacy_ids=["intersection"],
    ),
    "subtract": OperationSpec(
        id="subtract",
        name="Subtract",
        description="Remove the other structures from the primary one.",
        category="boolean",
        icon="−",
        color="orange",
        structure_roles=[
            StructureRole("primary", "Primary structure"),
            StructureRole("others", "Subtract structure(s)", kind="multiple"),
        ],
        parameters=[
            Parameter(
                name="margin_mm",
                label="Extra margin (mm)",
                type="number",
                default=0.0,
                min=0.0,
                step=0.5,
            )
        ],
        legacy_ids=["subtract"],
    ),
    "xor": OperationSpec(
        id="xor",
        name="Symmetric Difference (XOR)",
        description="Keep voxels in either structure but not both.",
        category="boolean",
        icon="⊕",
        color="cyan",
        structure_roles=[
            StructureRole("primary", "Primary structure"),
            StructureRole("others", "With structure(s)", kind="multiple"),
        ],
    ),
    # ---- Boundary / crop -------------------------------------------------
    "crop_to_boundary": OperationSpec(
        id="crop_to_boundary",
        name="Crop to Boundary",
        description="Limit a structure to one or more boundary structures.",
        category="boundary",
        icon="⊏",
        color="indigo",
        structure_roles=[
            StructureRole("source", "Structure to crop"),
            StructureRole("boundaries", "Boundary structure(s)", kind="multiple"),
        ],
        legacy_ids=["crop_to_boundary"],
    ),
    # ---- Composite (feature-rich) ---------------------------------------
    "ring": OperationSpec(
        id="ring",
        name="Ring / Shell",
        description="Expand the source by a thickness, then remove the source (a shell).",
        category="composite",
        icon="◎",
        color="teal",
        structure_roles=[StructureRole("source", "Source structure")],
        parameters=_margin_params("thickness"),
    ),
    "overlap": OperationSpec(
        id="overlap",
        name="Overlap",
        description="Keep the part of the source that overlaps any of the other structures.",
        category="composite",
        icon="⧉",
        color="violet",
        structure_roles=[
            StructureRole("source", "Source structure"),
            StructureRole("others", "Overlap with structure(s)", kind="multiple"),
        ],
    ),
    "expand_subtract": OperationSpec(
        id="expand_subtract",
        name="Expand & Subtract",
        description="Expand the source by a distance, then remove the subtract structure.",
        category="composite",
        icon="⊖",
        color="amber",
        structure_roles=[
            StructureRole("source", "Source structure"),
            StructureRole("subtract", "Subtract structure"),
        ],
        parameters=_margin_params("distance"),
    ),
    "avoid_margin": OperationSpec(
        id="avoid_margin",
        name="Avoid with Margin",
        description="Remove a margin around the avoid structure from the source.",
        category="composite",
        icon="⊘",
        color="rose",
        structure_roles=[
            StructureRole("source", "Source structure"),
            StructureRole("avoid", "Avoid structure"),
        ],
        parameters=_margin_params("margin"),
    ),
    # ---- Refinement / cleanup -------------------------------------------
    "smooth": OperationSpec(
        id="smooth",
        name="Smooth Surface",
        description="Smooth structure boundaries over N iterations.",
        category="refine",
        icon="≈",
        color="teal",
        structure_roles=[StructureRole("source", "Source structure")],
        parameters=[
            Parameter("smoothing_mm", "Smoothing (mm)", "number", 2.0, 0.0, 0.5),
            Parameter("iterations", "Iterations", "number", 1, 1, 1),
        ],
        legacy_ids=["smooth"],
    ),
    "gaussian_smooth": OperationSpec(
        id="gaussian_smooth",
        name="Gaussian Smooth",
        description="Gaussian blur the surface and re-threshold.",
        category="refine",
        icon="∿",
        color="sky",
        structure_roles=[StructureRole("source", "Source structure")],
        parameters=[
            Parameter("sigma_mm", "Sigma (mm)", "number", 1.0, 0.0, 0.5),
            Parameter("threshold", "Threshold", "number", 0.5, 0.0, 0.1),
        ],
    ),
    "fill_holes": OperationSpec(
        id="fill_holes",
        name="Fill Holes",
        description="Fill internal cavities.",
        category="refine",
        icon="●",
        color="gray",
        structure_roles=[StructureRole("source", "Source structure")],
        parameters=[Parameter("fully_connected", "Fully connected", "boolean", False)],
        legacy_ids=["fill_holes"],
    ),
    "remove_small_components": OperationSpec(
        id="remove_small_components",
        name="Remove Small Components",
        description="Remove disconnected pieces smaller than a volume.",
        category="refine",
        icon="⊗",
        color="pink",
        structure_roles=[StructureRole("source", "Source structure")],
        parameters=[Parameter("min_size_mm3", "Min size (mm³)", "number", 100.0, 0.0, 10.0)],
        legacy_ids=["remove_small_components"],
    ),
    "keep_largest": OperationSpec(
        id="keep_largest",
        name="Keep Largest Component",
        description="Keep only the largest connected piece.",
        category="refine",
        icon="◉",
        color="yellow",
        structure_roles=[StructureRole("source", "Source structure")],
        parameters=[],
        legacy_ids=["keep_largest"],
    ),
    "keep_n_largest": OperationSpec(
        id="keep_n_largest",
        name="Keep N Largest Components",
        description="Keep the N largest connected pieces.",
        category="refine",
        icon="❖",
        color="lime",
        structure_roles=[StructureRole("source", "Source structure")],
        parameters=[Parameter("n", "Keep (N)", "number", 1, 1, 1)],
    ),
    "close_gaps": OperationSpec(
        id="close_gaps",
        name="Close Gaps",
        description="Close small gaps between nearby pieces.",
        category="refine",
        icon="⋔",
        color="emerald",
        structure_roles=[StructureRole("source", "Source structure")],
        parameters=[Parameter("gap_size_mm", "Gap size (mm)", "number", 2.0, 0.0, 0.5)],
    ),
    "remove_protrusions": OperationSpec(
        id="remove_protrusions",
        name="Remove Protrusions",
        description="Trim thin protrusions from the surface.",
        category="refine",
        icon="⊣",
        color="fuchsia",
        structure_roles=[StructureRole("source", "Source structure")],
        parameters=[
            Parameter("protrusion_size_mm", "Protrusion size (mm)", "number", 2.0, 0.0, 0.5)
        ],
    ),
    # ---- Intensity (requires the CT image) ------------------------------
    "intensity_range": OperationSpec(
        id="intensity_range",
        name="Intensity Range",
        description="Segment voxels within intensity ranges, optionally seeded / bounded.",
        category="intensity",
        icon="▤",
        color="indigo",
        structure_roles=[
            StructureRole("seed", "Seed structure", required=False),
            StructureRole("boundary", "Boundary structure", required=False),
        ],
        parameters=[],  # ranges are a special list supplied by the caller
        requires_image=True,
    ),
}


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

# Flat alias map: legacy / alternative id -> canonical id.
_ALIASES: Dict[str, str] = {}
for _spec in OPERATIONS.values():
    _ALIASES[_spec.id] = _spec.id
    for _legacy in _spec.legacy_ids:
        _ALIASES[_legacy] = _spec.id


def resolve_operation_id(op_id: str) -> str:
    """Map a (possibly legacy) operation id to its canonical id.

    Raises ``KeyError`` if the id is unknown.
    """
    try:
        return _ALIASES[op_id]
    except KeyError:
        raise KeyError(
            f"Unknown operation id: {op_id!r}. Available: {sorted(OPERATIONS)}"
        ) from None


def get_operation(op_id: str) -> OperationSpec:
    """Return the :class:`OperationSpec` for a (possibly legacy) id."""
    return OPERATIONS[resolve_operation_id(op_id)]


def all_ids() -> List[str]:
    """Canonical operation ids, in catalog order."""
    return list(OPERATIONS.keys())


def to_frontend_catalog(categories: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Serialize the catalog for the frontends.

    Optionally filter to a subset of ``categories`` (e.g. exclude
    ``'intensity'`` for the auto-segmentation pipeline builder).
    """
    specs = OPERATIONS.values()
    if categories is not None:
        keep = set(categories)
        specs = [s for s in specs if s.category in keep]
    return [s.to_dict() for s in specs]


__all__ = [
    "StructureRole",
    "Parameter",
    "OperationSpec",
    "OPERATIONS",
    "resolve_operation_id",
    "get_operation",
    "all_ids",
    "to_frontend_catalog",
    "VARIANT_CHOICES",
    "KERNEL_CHOICES",
]
