# Spatial Rule Operations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add four new structure-relationship operations to rule-based segmentation as first-class pipeline rule types: **Ring/Shell**, **Overlap**, **Expand & Subtract**, and **Avoid with Margin** — each composable from the existing SimpleITK mask primitives already in `dicom_handler/utils/structure_generation/operations.py`.

**Architecture:** Each new operation is a new `PipelineRule.rule_type` with its own config model (the established pattern used by MARGIN/CROP/CLEANUP), a `validators.py` entry, a `SegmentationEngine._evaluate_*` method that composes existing primitives, the builder wiring in `views.py` (JSON round-trip, save, duplicate, structure-name collection), the vanilla-JS pipeline-builder editor, the `_rule_summary.html` display branch, and a test-helper branch. No changes are needed to the mask primitives or the Celery chain — these are pure engine rule types that flow through the existing `run_rule` → work-dir commit → `finalize_job` machinery unchanged.

**Tech Stack:** Python 3.13 (venv at `venv/`), Django 6.0.10, SimpleITK, rt-utils 2.5.0, numpy. Mask primitives live in `dicom_handler/utils/structure_generation/operations.py` (`apply_uniform_margin`, `apply_anisotropic_margin`, `boolean_union`, `boolean_intersection`, `boolean_subtraction`).

**Spec:** Agreed in the 2026-11-22 conversation; the four operations and their exact semantics are defined in "Design notes" below.

## Global Constraints

- Test command: `venv/bin/python manage.py test rule_based_segmentation.tests.<module> -v 2` (no broker needed — engine tests run in-process).
- Dev DB on this machine is Postgres via `.env`; new models require `makemigrations` + `migrate`.
- One commit per task. Conventional-style messages (`feat:` / `test:` / `chore:`).
- The existing suites (`tests/test_engine.py`, `tests/test_end_to_end.py`, `tests/test_pipeline_e2e_physics.py`, `tests/test_models.py`, `tests/test_views.py`, `tests/test_tasks.py`) must stay green with **all assertions unchanged**.
- Do NOT touch the mask axis conventions in `utils/rtstruct_io.py` or the Celery chain arg-contract in `tasks.py` — out of scope.
- All mask math is in physical space (mm) via the existing primitives; spacing is read from the mask, never hard-coded.
- A new rule type touches a fixed set of integration points (see "Per-operation integration points" below). Every task MUST update all of them, or the rule will be creatable in the DB but unusable (or vice-versa).

## Design notes

### The four operations (exact semantics)

All inputs/outputs are `sitk.Image` binary masks (foreground = 1). `expand(mask, d)` is `apply_uniform_margin(mask, d, kernel)` for UNIFORM or `apply_anisotropic_margin(mask, x, y, z)` for ANISOTROPIC. Distances are in mm; positive = expansion, negative = contraction, zero = identity (consistent with the existing MARGIN rule).

1. **RING** — "Ring / Shell" around a structure.
   - `result = expand(source, thickness) − source`
   - A shell of `thickness` thickness surrounding `source`, excluding `source` itself.
   - Config: `variant` (UNIFORM/ANISOTROPIC), `source`, `thickness_mm` (UNIFORM) or `thickness_x_mm/y/z` (ANISOTROPIC), `kernel_type` (UNIFORM only).

2. **OVERLAP** — "Overlap (A ∩ others)".
   - `result = source ∩ (other1 ∪ other2 ∪ …)`
   - The part of `source` that overlaps any of the user-selected `others` (one or many).
   - Config: `source`, `others` (ordered list of ≥1 structure names — child model `OverlapOther`).

3. **EXPAND_SUBTRACT** — "Expand & Subtract".
   - `result = expand(source, distance) − subtract`
   - Grow `source` by `distance`, then remove `subtract`. (User's "crop structure B from structure A by 5 mm" = expand A by 5 mm, subtract B.)
   - Config: `variant`, `source`, `subtract`, `distance_mm` (UNIFORM) or `distance_x/y/z` (ANISOTROPIC), `kernel_type` (UNIFORM only).

4. **AVOID_MARGIN** — "Avoid with Margin" *(optional — the inverse of EXPAND_SUBTRACT, a very common "avoid organ by N mm" workflow; drop this task if not wanted)*.
   - `result = source − expand(avoid, margin)`
   - Keep `source` but remove everything within `margin` of `avoid`.
   - Config: `variant`, `source`, `avoid`, `margin_mm` (UNIFORM) or `margin_x/y/z` (ANISOTROPIC), `kernel_type` (UNIFORM only).

### Why no new primitives are needed

Every operation composes primitives that already exist and are already unit-tested in `dicom_handler/utils/structure_generation/operations.py`:
- `apply_uniform_margin(mask, mm, kernel)` / `apply_anisotropic_margin(mask, x, y, z)`
- `boolean_union(a, b)`, `boolean_intersection(a, b)`, `boolean_subtraction(a, b)`

The engine already imports `apply_uniform_margin`, `apply_anisotropic_margin`, `boolean_intersection`. This plan adds `boolean_subtraction` and `boolean_union` to that import (Task 1).

### Per-operation integration points (the "fixed set")

For each new rule type `XYZ` (config model `XyzRuleConfig`, `related_name="xyz_config"`):

1. `rule_based_segmentation/models.py` — add `("XYZ", "…label…")` to `RULE_TYPE_CHOICES`; add `XyzRuleConfig` model; add the `elif self.rule_type == "XYZ": validate_xyz_rule(self)` branch in `PipelineRule.clean()`; add `validate_xyz_rule` to the import from `.utils.validators`.
2. `rule_based_segmentation/migrations/000X_*.py` — `makemigrations`.
3. `rule_based_segmentation/utils/validators.py` — `validate_xyz_rule(rule)`.
4. `rule_based_segmentation/utils/engine.py` — `_collect_required_structures` branch; `_evaluate_rule` branch; `_evaluate_xyz_rule(self, rule)` method.
5. `rule_based_segmentation/views.py` — `_rule_to_json` branch; `_collect_required_structure_names` branch; `_save_rule` branch + `_save_xyz_config(rule, config)`; `_duplicate_rule` branch; `_collect_rule_structure_names` branch; add `XyzRuleConfig` (+ child model if any) to the `from .models import (...)` block.
6. `rule_based_segmentation/tests/helpers.py` — `create_pipeline_with_rules` dispatch branch + `_create_xyz_config(rule, config)`.
7. `static/js/rule_based_pipeline_builder.js` — `RULE_TYPES` label; `_defaultConfig` case; `_summarizeRule` case; `_renderRuleEditor` switch case + a `_renderXyzEditor(config)` method; `_collectConfigFromEditor` case; `_attachConfigEventListeners` case (only if the editor has dynamic parts, e.g. the UNIFORM/ANISOTROPIC toggle or an add/remove list).
8. `templates/rule_based_segmentation/_rule_summary.html` — display branch for the new type.
9. `rule_based_segmentation/tests/test_spatial_rules.py` — engine test(s) for the operation.

### Shared test fixture

`tests/test_spatial_rules.py` uses a synthetic 10-slice 64×64 CT (spacing 1.0 mm) and a multi-ROI RTStruct with two overlapping boxes (defined in Task 1, reused by all tasks):
- `Box`  = voxels `z[3:7], y[28:36], x[28:36]`  (4×8×8 = 256 voxels)
- `Box2` = voxels `z[3:7], y[32:40], x[32:40]`  (4×8×8 = 256 voxels)
- `Box ∩ Box2` = `z[3:7], y[32:36], x[32:36]` = 4×4×4 = **64 voxels** (used by the OVERLAP test).

A new `create_synthetic_rtstruct_multi(path, ct_files, rois: {name: mask})` helper (added in Task 1) builds a multi-ROI RTStruct; `mask` arrays are `(Z, Y, X)` boolean, transposed to `(X, Y, Z)` exactly like the existing `create_synthetic_rtstruct`.

---

## Task 1: RING rule (ring/shell around a structure) + shared expand helper + test scaffolding

**Files:**
- Modify: `rule_based_segmentation/models.py`
- Modify: `rule_based_segmentation/utils/validators.py`
- Modify: `rule_based_segmentation/utils/engine.py`
- Modify: `rule_based_segmentation/views.py`
- Modify: `rule_based_segmentation/tests/helpers.py`
- Modify: `static/js/rule_based_pipeline_builder.js`
- Modify: `templates/rule_based_segmentation/_rule_summary.html`
- Create: `rule_based_segmentation/tests/test_spatial_rules.py`
- Create: `rule_based_segmentation/migrations/0005_ringruleconfig.py` (via `makemigrations`)

**Interfaces:**
- Consumes: `apply_uniform_margin`, `apply_anisotropic_margin`, `boolean_subtraction` from `dicom_handler.utils.structure_generation.operations`; `create_synthetic_ct_series`, `create_dicom_models` from `tests.helpers`; `SegmentationEngine`.
- Produces: `RingRuleConfig` model; `validate_ring_rule(rule)`; `SegmentationEngine._expand_mask_by_variant(mask, variant, uniform_mm, x_mm, y_mm, z_mm, kernel_type)` (shared by Tasks 3–4); `create_synthetic_rtstruct_multi(path, ct_files, rois)`; `create_pipeline_with_rules(rules_data=[{..., "rule_type": "RING", ...}])`.

- [ ] **Step 1: Write the failing engine test + shared multi-ROI fixture helper**

Create `rule_based_segmentation/tests/test_spatial_rules.py`:

```python
"""Engine tests for the spatial rule operations (RING, OVERLAP, EXPAND_SUBTRACT, AVOID_MARGIN)."""

import os
import shutil
import tempfile

import numpy as np
import SimpleITK as sitk
from django.test import TestCase

from dicom_handler.utils.structure_generation.operations import (
    apply_uniform_margin,
)

from ..utils.engine import SegmentationEngine
from .helpers import (
    create_dicom_models,
    create_pipeline_with_rules,
    create_synthetic_ct_series,
    create_synthetic_rtstruct_multi,
)


class SpatialRulesBase(TestCase):
    """Shared fixture: 10-slice 64x64 CT (1.0 mm spacing) with two overlapping boxes."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="rbs_spatial_")
        self.series_uid = "1.2.3.4.5.6.7.8.9"
        self.study_uid = "1.2.3.4.5.6.7.8.10"
        self.ct_files = create_synthetic_ct_series(
            self.temp_dir,
            num_slices=10,
            rows=64,
            cols=64,
            spacing=(1.0, 1.0, 1.0),
            series_uid=self.series_uid,
            study_uid=self.study_uid,
        )
        self.series = create_dicom_models(self.ct_files, self.series_uid, self.study_uid)

        # Box = z[3:7], y[28:36], x[28:36]  (4x8x8 = 256 voxels)
        self.box = np.zeros((10, 64, 64), dtype=bool)
        self.box[3:7, 28:36, 28:36] = True
        # Box2 = z[3:7], y[32:40], x[32:40] (4x8x8 = 256 voxels)
        self.box2 = np.zeros((10, 64, 64), dtype=bool)
        self.box2[3:7, 32:40, 32:40] = True

        self.rtstruct_path = os.path.join(self.temp_dir, "test_rtstruct.dcm")
        create_synthetic_rtstruct_multi(
            self.rtstruct_path,
            self.ct_files,
            {"Box": self.box, "Box2": self.box2},
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _engine(self):
        return SegmentationEngine(self.rtstruct_path, self.series_uid)

    def _run_single_rule(self, rules_data):
        pipeline = create_pipeline_with_rules(rules_data=rules_data)
        engine = self._engine()
        engine.run_rule(pipeline.rules.first())
        return engine

    @staticmethod
    def _volume(mask):
        return int(np.sum(sitk.GetArrayFromImage(mask)))


class RingRuleTests(SpatialRulesBase):
    def test_ring_is_a_shell_excluding_source(self):
        engine = self._run_single_rule(
            [
                {
                    "rule_type": "RING",
                    "name": "Ring",
                    "config": {
                        "variant": "UNIFORM",
                        "source": "Box",
                        "thickness_mm": 1.0,
                        "kernel_type": "ball",
                    },
                }
            ]
        )
        ring = engine.available_masks["Ring"]
        box = engine.available_masks["Box"]
        # The ring must exclude the source structure entirely.
        self.assertEqual(self._volume(sitk.And(ring, box)), 0)
        # The ring is non-empty.
        self.assertGreater(self._volume(ring), 0)
        # Ring volume == expanded(Box) - Box.
        expanded = apply_uniform_margin(box, 1.0, "ball")
        expected = self._volume(expanded) - self._volume(box)
        self.assertEqual(self._volume(ring), expected)

    def test_ring_anisotropic_variant(self):
        engine = self._run_single_rule(
            [
                {
                    "rule_type": "RING",
                    "name": "RingA",
                    "config": {
                        "variant": "ANISOTROPIC",
                        "source": "Box",
                        "thickness_x_mm": 1.0,
                        "thickness_y_mm": 1.0,
                        "thickness_z_mm": 0.0,
                    },
                }
            ]
        )
        ring = engine.available_masks["RingA"]
        box = engine.available_masks["Box"]
        self.assertEqual(self._volume(sitk.And(ring, box)), 0)
        # z-thickness 0 means the shell only grows in x/y; it must still be non-empty.
        self.assertGreater(self._volume(ring), 0)
```

Add `create_synthetic_rtstruct_multi` to `rule_based_segmentation/tests/helpers.py` (append near `create_synthetic_rtstruct`):

```python
def create_synthetic_rtstruct_multi(
    rtstruct_path: str,
    ct_file_paths: List[str],
    rois: Dict[str, np.ndarray],
) -> str:
    """Create a synthetic RTStruct with multiple ROIs.

    rois maps ROI name -> 3D boolean mask in (Z, Y, X) order (transposed to
    (X, Y, Z) for rt-utils, same as create_synthetic_rtstruct).
    """
    rtstruct = RTStructBuilder.create_new(os.path.dirname(ct_file_paths[0]))
    for name, mask_array in rois.items():
        rt_mask = mask_array.astype(bool)
        if rt_mask.ndim == 3:
            rt_mask = rt_mask.transpose(2, 1, 0)
        rtstruct.add_roi(mask=rt_mask, name=name, color=[255, 0, 0])
    rtstruct.save(rtstruct_path)
    return rtstruct_path
```

> `List` is already imported in `helpers.py` (`from typing import ...`). If `Dict` is not imported, add it to the existing `from typing import` line.

- [ ] **Step 2: Run the test to confirm it fails**

Run: `venv/bin/python manage.py test rule_based_segmentation.tests.test_spatial_rules -v 2`
Expected: FAIL — `RingRuleConfig.DoesNotExist` (or `create_pipeline_with_rules` raises / `rule.ring_config` missing), because `RING` is not yet a known rule type with a config model.

- [ ] **Step 3: Add `RING` to `RULE_TYPE_CHOICES` and add `RingRuleConfig` in `models.py`**

In `rule_based_segmentation/models.py`, extend the `RULE_TYPE_CHOICES` list (currently ends with `("CLEANUP", "Cleanup / Refinement"),`):

```python
    RULE_TYPE_CHOICES = [
        ("BOOLEAN", "Boolean Expression"),
        ("INTENSITY", "Intensity Range"),
        ("MARGIN", "Margin"),
        ("CROP", "Crop to Boundary"),
        ("CLEANUP", "Cleanup / Refinement"),
        ("RING", "Ring / Shell"),
    ]
```

Add the new config model after `CleanupRuleConfig` (near the other config models):

```python
class RingRuleConfig(models.Model):
    """Configuration for RING (ring/shell) rules."""

    VARIANT_CHOICES = [("UNIFORM", "Uniform"), ("ANISOTROPIC", "Anisotropic")]
    KERNEL_CHOICES = [("ball", "Ball"), ("box", "Box"), ("cross", "Cross")]

    pipeline_rule = models.OneToOneField(
        PipelineRule,
        on_delete=models.CASCADE,
        related_name="ring_config",
        limit_choices_to={"rule_type": "RING"},
    )
    variant = models.CharField(max_length=16, choices=VARIANT_CHOICES, default="UNIFORM")
    source = models.CharField(max_length=256, help_text="Structure to build the ring around")
    thickness_mm = models.FloatField(null=True, blank=True, help_text="Uniform thickness (mm) for UNIFORM variant")
    thickness_x_mm = models.FloatField(null=True, blank=True, help_text="X thickness (mm) for ANISOTROPIC variant")
    thickness_y_mm = models.FloatField(null=True, blank=True, help_text="Y thickness (mm) for ANISOTROPIC variant")
    thickness_z_mm = models.FloatField(null=True, blank=True, help_text="Z thickness (mm) for ANISOTROPIC variant")
    kernel_type = models.CharField(max_length=16, choices=KERNEL_CHOICES, default="ball", help_text="Structuring element for UNIFORM variant")

    def __str__(self):
        return f"Ring config for {self.pipeline_rule_id}"
```

Add `validate_ring_rule` to the import block at the top of `models.py`:

```python
from .utils.validators import (
    validate_boolean_rule,
    validate_cleanup_rule,
    validate_crop_rule,
    validate_intensity_rule,
    validate_margin_rule,
    validate_ring_rule,
)
```

Add the `clean()` branch in `PipelineRule.clean()` (after the `CLEANUP` branch):

```python
        elif self.rule_type == "RING":
            validate_ring_rule(self)
```

- [ ] **Step 4: Add `validate_ring_rule` to `validators.py`**

Append to `rule_based_segmentation/utils/validators.py` (model it on `validate_margin_rule`):

```python
def validate_ring_rule(rule):
    config = getattr(rule, "ring_config", None)
    if not config:
        raise ValidationError("Ring rules require a ring configuration.")
    if not config.source or not config.source.strip():
        raise ValidationError("Ring rules require a source structure.")
    if config.variant == "UNIFORM":
        if config.thickness_mm is None:
            raise ValidationError("Uniform ring thickness is required.")
    else:
        if config.thickness_x_mm is None or config.thickness_y_mm is None or config.thickness_z_mm is None:
            raise ValidationError("Anisotropic ring thickness (X, Y, Z) is required.")
```

- [ ] **Step 5: Generate and apply the migration**

Run: `venv/bin/python manage.py makemigrations rule_based_segmentation`
Then: `venv/bin/python manage.py migrate`
Expected: a new migration file (e.g. `0005_ringruleconfig.py`) referencing `RingRuleConfig`; `migrate` applies it to the dev Postgres DB.

- [ ] **Step 6: Add the engine evaluation for RING + the shared expand helper**

In `rule_based_segmentation/utils/engine.py`, extend the operations import:

```python
from dicom_handler.utils.structure_generation.operations import (
    apply_anisotropic_margin,
    apply_uniform_margin,
    boolean_intersection,
    boolean_subtraction,
    boolean_union,
)
```

Add a shared helper method on `SegmentationEngine` (place it near the other `_evaluate_*` private helpers):

```python
    def _expand_mask_by_variant(
        self,
        mask: sitk.Image,
        variant: str,
        uniform_mm: float = None,
        x_mm: float = None,
        y_mm: float = None,
        z_mm: float = None,
        kernel_type: str = "ball",
    ) -> sitk.Image:
        """Expand (or contract) a mask by a UNIFORM or ANISOTROPIC distance (mm)."""
        if variant == "UNIFORM":
            return apply_uniform_margin(mask, uniform_mm, kernel_type or "ball")
        return apply_anisotropic_margin(mask, x_mm, y_mm, z_mm)
```

Add the `RING` branch to `_collect_required_structures` (after the existing `CROP`/`CLEANUP` branches):

```python
        elif rule.rule_type == "RING":
            config = getattr(rule, "ring_config", None)
            if config and config.source:
                required_names.add(config.source)
```

Add the `RING` branch to `_evaluate_rule` (after the existing `CLEANUP` branch):

```python
        elif rule_type == "RING":
            return self._evaluate_ring_rule(rule)
```

Add the evaluator method on `SegmentationEngine` (near `_evaluate_margin_rule`):

```python
    def _evaluate_ring_rule(self, rule) -> sitk.Image:
        """Ring/shell: expand(source, thickness) - source."""
        config = rule.ring_config
        source_mask = self.available_masks[config.source]
        self._ensure_mask_not_empty(source_mask, config.source)
        expanded = self._expand_mask_by_variant(
            source_mask,
            config.variant,
            uniform_mm=config.thickness_mm,
            x_mm=config.thickness_x_mm,
            y_mm=config.thickness_y_mm,
            z_mm=config.thickness_z_mm,
            kernel_type=config.kernel_type,
        )
        return boolean_subtraction(expanded, source_mask)
```

> Confirm `_ensure_mask_not_empty` exists on the engine (it is used by other evaluators). If the method has a different name in the current engine, call the equivalent guard; the goal is to fail fast when the source is empty.

- [ ] **Step 7: Wire the builder in `views.py`**

Add `RingRuleConfig` to the `from .models import (...)` block in `views.py`.

Add a `RING` branch to `_rule_to_json` (after the `CLEANUP` branch):

```python
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
        }
```

Add a `RING` branch to `_collect_required_structure_names` (after the `CROP` branch):

```python
    elif rule_type == "RING":
        if config.get("source"):
            names.add(config["source"])
```

Add a `RING` branch to `_save_rule` (after the `CLEANUP` branch) and the new save function:

```python
    elif rule_type == "RING":
        _save_ring_config(rule, config)
```

```python
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
    )
```

Add a `RING` branch to `_duplicate_rule` (after the `CLEANUP` branch):

```python
    elif rule.rule_type == "RING":
        src = rule.ring_config
        RingRuleConfig.objects.create(
            pipeline_rule=new_rule,
            variant=src.variant,
            source=src.source,
            thickness_mm=src.thickness_mm,
            thickness_x_mm=src.thickness_x_mm,
            thickness_y_mm=src.thickness_y_mm,
            thickness_z_mm=src.thickness_z_mm,
            kernel_type=src.kernel_type,
        )
```

Add a `RING` branch to `_collect_rule_structure_names` (after the `CROP` branch):

```python
    elif rule.rule_type == "RING":
        config = getattr(rule, "ring_config", None)
        if config and config.source:
            names.add(config.source)
```

- [ ] **Step 8: Add the test-helper branch in `helpers.py`**

In `create_pipeline_with_rules` (the `for raw_rule in rules_data:` loop), add a `RING` branch next to the other config-creation branches:

```python
        elif rule_type == "RING":
            _create_ring_config(rule, raw.get("config", {}))
```

Add the helper function (near the other `_create_*_config` helpers):

```python
def _create_ring_config(rule, config):
    return RingRuleConfig.objects.create(
        pipeline_rule=rule,
        variant=config.get("variant", "UNIFORM"),
        source=config.get("source", ""),
        thickness_mm=config.get("thickness_mm"),
        thickness_x_mm=config.get("thickness_x_mm"),
        thickness_y_mm=config.get("thickness_y_mm"),
        thickness_z_mm=config.get("thickness_z_mm"),
        kernel_type=config.get("kernel_type", "ball"),
    )
```

> `RingRuleConfig` must be importable in `helpers.py` (add it to the existing `from ..models import (...)` block there).

- [ ] **Step 9: Add the JS builder editor for RING**

In `static/js/rule_based_pipeline_builder.js`, mirror the existing MARGIN rule (the `_renderMarginEditor` renderer, the `MARGIN` case in `_collectConfigFromEditor`, and the `MARGIN` block in the *effective* `_attachConfigEventListeners`):

Add the `RING` label to `RULE_TYPES`:

```js
    RING: "Ring / Shell",
```

In `_defaultConfig(ruleType)` (the `switch`), add:

```js
    case "RING":
      return {
        variant: "UNIFORM",
        source: "",
        thickness_mm: 5,
        thickness_x_mm: 5,
        thickness_y_mm: 5,
        thickness_z_mm: 5,
        kernel_type: "ball",
      };
```

In `_summarizeRule(rule)` (the `switch`), add:

```js
    case "RING": {
      const c = rule.config || {};
      const d = c.variant === "ANISOTROPIC" ? `${c.thickness_x_mm}/${c.thickness_y_mm}/${c.thickness_z_mm} mm` : `${c.thickness_mm} mm`;
      return `Ring around ${c.source || "—"} (${d})`;
    }
```

In `_renderRuleEditor(rule)`, add a `RING` case to the `switch` that builds `configHtml` (the MARGIN case is `case "MARGIN": configHtml = this._renderMarginEditor(rule.config);`):

```js
        case "RING":
          configHtml = this._renderRingEditor(rule.config);
          break;
```

Add the renderer method, modeled directly on `_renderMarginEditor` (same ids, `hidden`-class toggle pattern, and `MARGIN_KERNELS` for the kernel):

```js
    _renderRingEditor(config) {
      return `
        <div class="space-y-4">
          <div>
            <label class="block text-sm font-medium text-gray-700">Variant</label>
            <select id="rbs-ring-variant" class="mt-1 block w-full border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm px-3 py-2">
              <option value="UNIFORM" ${config.variant === "UNIFORM" ? "selected" : ""}>Uniform</option>
              <option value="ANISOTROPIC" ${config.variant === "ANISOTROPIC" ? "selected" : ""}>Anisotropic</option>
            </select>
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-700">Source Structure</label>
            ${this._renderStructureSelect("rbs-ring-source", config.source)}
          </div>
          <div id="rbs-ring-uniform" class="${config.variant !== "UNIFORM" ? "hidden" : ""}">
            <label class="block text-sm font-medium text-gray-700">Ring thickness (mm)</label>
            <input type="number" step="any" id="rbs-ring-mm" value="${config.thickness_mm}" class="mt-1 block w-full border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm px-3 py-2">
            <label class="block text-sm font-medium text-gray-700 mt-2">Kernel</label>
            <select id="rbs-ring-kernel" class="mt-1 block w-full border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm px-3 py-2">
              ${MARGIN_KERNELS.map((k) => `<option value="${k.value}" ${config.kernel_type === k.value ? "selected" : ""}>${k.label}</option>`).join("")}
            </select>
          </div>
          <div id="rbs-ring-anisotropic" class="${config.variant !== "ANISOTROPIC" ? "hidden" : ""}">
            <label class="block text-sm font-medium text-gray-700">Thickness X (mm)</label>
            <input type="number" step="any" id="rbs-ring-x" value="${config.thickness_x_mm}" class="mt-1 block w-full border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm px-3 py-2">
            <label class="block text-sm font-medium text-gray-700 mt-2">Thickness Y (mm)</label>
            <input type="number" step="any" id="rbs-ring-y" value="${config.thickness_y_mm}" class="mt-1 block w-full border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm px-3 py-2">
            <label class="block text-sm font-medium text-gray-700 mt-2">Thickness Z (mm)</label>
            <input type="number" step="any" id="rbs-ring-z" value="${config.thickness_z_mm}" class="mt-1 block w-full border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm px-3 py-2">
          </div>
        </div>
      `;
    }
```

In `_collectConfigFromEditor(rule)` (the `switch`, after the `MARGIN` case), add:

```js
        case "RING":
          cfg.variant = this.container.querySelector("#rbs-ring-variant").value;
          cfg.source = this._getValue("#rbs-ring-source");
          cfg.thickness_mm = parseFloat(this._getValue("#rbs-ring-mm")) || 0;
          cfg.thickness_x_mm = parseFloat(this._getValue("#rbs-ring-x")) || 0;
          cfg.thickness_y_mm = parseFloat(this._getValue("#rbs-ring-y")) || 0;
          cfg.thickness_z_mm = parseFloat(this._getValue("#rbs-ring-z")) || 0;
          cfg.kernel_type = this._getValue("#rbs-ring-kernel");
          break;
```

> `_getValue(selector)` is an existing helper on the builder (used by the CLEANUP collector). Use it for id lookups.

In `_attachConfigEventListeners(ruleType)` — the **second, effective** definition (the class declares this method twice; the later one, near the `_getValue` helper, is the one that runs) — add a `RING` block mirroring the `MARGIN` block:

```js
      if (ruleType === "RING") {
        const variant = this.container.querySelector("#rbs-ring-variant");
        variant.addEventListener("change", () => {
          const isUniform = variant.value === "UNIFORM";
          this.container.querySelector("#rbs-ring-uniform").classList.toggle("hidden", !isUniform);
          this.container.querySelector("#rbs-ring-anisotropic").classList.toggle("hidden", isUniform);
        });
      }
```

- [ ] **Step 10: Add the `_rule_summary.html` display branch for RING**

In `templates/rule_based_segmentation/_rule_summary.html`, add a branch matching the existing per-type structure (a `{% if rule.rule_type == "..." %}` block) so RING rules render their config (source + thickness + variant) in the read-only rule list. Mirror the MARGIN branch layout.

- [ ] **Step 11: Run the RING tests to confirm they pass**

Run: `venv/bin/python manage.py test rule_based_segmentation.tests.test_spatial_rules -v 2`
Expected: PASS (2 RING tests).

- [ ] **Step 12: Run the full test suite to confirm no regression**

Run: `venv/bin/python manage.py test rule_based_segmentation -v 1`
Expected: all existing tests still pass (the new model/migration and added branches are additive).

- [ ] **Step 13: Commit**

```bash
git add rule_based_segmentation/models.py rule_based_segmentation/utils/validators.py rule_based_segmentation/utils/engine.py rule_based_segmentation/views.py rule_based_segmentation/tests/helpers.py rule_based_segmentation/tests/test_spatial_rules.py static/js/rule_based_pipeline_builder.js templates/rule_based_segmentation/_rule_summary.html rule_based_segmentation/migrations/
git commit -m "feat(rbs): add RING (ring/shell) rule type"
```

---

## Task 2: OVERLAP rule (A ∩ others, one or many)

**Files:**
- Modify: `rule_based_segmentation/models.py`
- Modify: `rule_based_segmentation/utils/validators.py`
- Modify: `rule_based_segmentation/utils/engine.py`
- Modify: `rule_based_segmentation/views.py`
- Modify: `rule_based_segmentation/tests/helpers.py`
- Modify: `static/js/rule_based_pipeline_builder.js`
- Modify: `templates/rule_based_segmentation/_rule_summary.html`
- Modify: `rule_based_segmentation/tests/test_spatial_rules.py`
- Create: `rule_based_segmentation/migrations/0006_overlapruleconfig_overlapother.py` (via `makemigrations`)

**Interfaces:**
- Consumes: `boolean_intersection`, `boolean_union` (already imported in Task 1); `create_pipeline_with_rules`.
- Produces: `OverlapRuleConfig` model + `OverlapOther` child model (ordered list of structure names); `validate_overlap_rule(rule)`; config JSON shape `{"source": "...", "others": ["A", "B"]}`.

- [ ] **Step 1: Add the failing engine tests**

Append to `rule_based_segmentation/tests/test_spatial_rules.py`:

```python
class OverlapRuleTests(SpatialRulesBase):
    def test_overlap_single_other(self):
        engine = self._run_single_rule(
            [
                {
                    "rule_type": "OVERLAP",
                    "name": "Ovl",
                    "config": {"source": "Box", "others": ["Box2"]},
                }
            ]
        )
        # Box ∩ Box2 = 4x4x4 = 64 voxels.
        self.assertEqual(self._volume(engine.available_masks["Ovl"]), 64)

    def test_overlap_multiple_others_union(self):
        # Box ∩ (Box2 ∪ Box2) is still Box ∩ Box2 = 64 (duplicate-safe union).
        engine = self._run_single_rule(
            [
                {
                    "rule_type": "OVERLAP",
                    "name": "Ovl2",
                    "config": {"source": "Box", "others": ["Box2", "Box2"]},
                }
            ]
        )
        self.assertEqual(self._volume(engine.available_masks["Ovl2"]), 64)
```

> (If you want a genuinely different second structure, add a third box to the fixture in `SpatialRulesBase.setUp` and assert the union grows the overlap accordingly. The two tests above are sufficient to prove single- and multi-other wiring.)

- [ ] **Step 2: Run the tests to confirm they fail**

Run: `venv/bin/python manage.py test rule_based_segmentation.tests.test_spatial_rules.OverlapRuleTests -v 2`
Expected: FAIL — `OVERLAP` is not yet a known rule type (no config model).

- [ ] **Step 3: Add `OVERLAP` choice + config + child model in `models.py`**

Add `("OVERLAP", "Overlap")` to `RULE_TYPE_CHOICES` (after `RING`):

```python
        ("RING", "Ring / Shell"),
        ("OVERLAP", "Overlap"),
```

Add the config + child models (after `RingRuleConfig`):

```python
class OverlapRuleConfig(models.Model):
    """Configuration for OVERLAP rules: source ∩ (union of others)."""

    pipeline_rule = models.OneToOneField(
        PipelineRule,
        on_delete=models.CASCADE,
        related_name="overlap_config",
        limit_choices_to={"rule_type": "OVERLAP"},
    )
    source = models.CharField(max_length=256, help_text="Structure to keep (the part that overlaps others)")

    def __str__(self):
        return f"Overlap config for {self.pipeline_rule_id}"


class OverlapOther(models.Model):
    """One selected 'other' structure for an OVERLAP rule (ordered)."""

    overlap_rule = models.ForeignKey(
        OverlapRuleConfig,
        on_delete=models.CASCADE,
        related_name="others",
    )
    other_roi = models.CharField(max_length=256)
    order = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["order"]
        unique_together = [("overlap_rule", "order")]

    def __str__(self):
        return f"{self.order}: {self.other_roi}"
```

Add `validate_overlap_rule` to the import block in `models.py` and add the `clean()` branch:

```python
        elif self.rule_type == "OVERLAP":
            validate_overlap_rule(self)
```

- [ ] **Step 4: Add `validate_overlap_rule` to `validators.py`**

```python
def validate_overlap_rule(rule):
    config = getattr(rule, "overlap_config", None)
    if not config:
        raise ValidationError("Overlap rules require an overlap configuration.")
    if not config.source or not config.source.strip():
        raise ValidationError("Overlap rules require a source structure.")
    if config.others.count() == 0:
        raise ValidationError("Overlap rules require at least one other structure.")
```

- [ ] **Step 5: Generate and apply the migration**

Run: `venv/bin/python manage.py makemigrations rule_based_segmentation`
Then: `venv/bin/python manage.py migrate`
Expected: a new migration for `OverlapRuleConfig` + `OverlapOther`; applied to dev DB.

- [ ] **Step 6: Add engine evaluation for OVERLAP**

In `rule_based_segmentation/utils/engine.py`:

Add the `OVERLAP` branch to `_collect_required_structures`:

```python
        elif rule.rule_type == "OVERLAP":
            config = getattr(rule, "overlap_config", None)
            if config:
                if config.source:
                    required_names.add(config.source)
                for other in config.others.all():
                    required_names.add(other.other_roi)
```

Add the `OVERLAP` branch to `_evaluate_rule`:

```python
        elif rule_type == "OVERLAP":
            return self._evaluate_overlap_rule(rule)
```

Add the evaluator method on `SegmentationEngine`:

```python
    def _evaluate_overlap_rule(self, rule) -> sitk.Image:
        """Overlap: source ∩ (other1 ∪ other2 ∪ …)."""
        config = rule.overlap_config
        result = self.available_masks[config.source]
        others = list(config.others.values_list("other_roi", flat=True).order_by("order"))
        if not others:
            raise RuleEvaluationError("Overlap rule requires at least one other structure.")
        combined = self.available_masks[others[0]]
        for name in others[1:]:
            combined = boolean_union(combined, self.available_masks[name])
        return boolean_intersection(result, combined)
```

> `RuleEvaluationError` is the engine's existing exception for evaluation failures (used by other evaluators); use the same name the engine already uses.

- [ ] **Step 7: Wire the builder in `views.py`**

Add `OverlapRuleConfig` and `OverlapOther` to the `from .models import (...)` block.

Add an `OVERLAP` branch to `_rule_to_json`:

```python
    elif rule.rule_type == "OVERLAP":
        cfg = rule.overlap_config
        data["config"] = {
            "source": cfg.source,
            "others": [o.other_roi for o in cfg.others.all().order_by("order")],
        }
```

Add an `OVERLAP` branch to `_collect_required_structure_names`:

```python
    elif rule_type == "OVERLAP":
        if config.get("source"):
            names.add(config["source"])
        for other in config.get("others", []):
            if other:
                names.add(other)
```

Add an `OVERLAP` branch to `_save_rule` and the save function:

```python
    elif rule_type == "OVERLAP":
        _save_overlap_config(rule, config)
```

```python
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
```

Add an `OVERLAP` branch to `_duplicate_rule`:

```python
    elif rule.rule_type == "OVERLAP":
        src = rule.overlap_config
        new_overlap = OverlapRuleConfig.objects.create(
            pipeline_rule=new_rule,
            source=src.source,
        )
        for other in src.others.all().order_by("order"):
            OverlapOther.objects.create(
                overlap_rule=new_overlap,
                other_roi=other.other_roi,
                order=other.order,
            )
```

Add an `OVERLAP` branch to `_collect_rule_structure_names`:

```python
    elif rule.rule_type == "OVERLAP":
        config = getattr(rule, "overlap_config", None)
        if config:
            if config.source:
                names.add(config.source)
            for other in config.others.all():
                names.add(other.other_roi)
```

- [ ] **Step 8: Add the test-helper branch in `helpers.py`**

In `create_pipeline_with_rules`, add the `OVERLAP` branch:

```python
        elif rule_type == "OVERLAP":
            _create_overlap_config(rule, raw.get("config", {}))
```

Add the helper (import `OverlapRuleConfig`, `OverlapOther` from `..models`):

```python
def _create_overlap_config(rule, config):
    overlap = OverlapRuleConfig.objects.create(
        pipeline_rule=rule,
        source=config.get("source", ""),
    )
    for idx, other in enumerate(config.get("others", []), start=1):
        OverlapOther.objects.create(
            overlap_rule=overlap,
            other_roi=other,
            order=idx,
        )
    return overlap
```

- [ ] **Step 9: Add the JS builder editor for OVERLAP**

In `static/js/rule_based_pipeline_builder.js`, mirror the existing CROP rule (`_renderCropEditor`, the `CROP` case in `_collectConfigFromEditor`, and the `CROP` block in the effective `_attachConfigEventListeners`):

Add the `OVERLAP` label to `RULE_TYPES`:

```js
    OVERLAP: "Overlap",
```

In `_defaultConfig(ruleType)` (the `switch`), add:

```js
    case "OVERLAP":
      return { source: "", others: [] };
```

In `_summarizeRule(rule)` (the `switch`), add:

```js
    case "OVERLAP": {
      const c = rule.config || {};
      const n = (c.others || []).length;
      return `${c.source || "—"} overlaps ${n} structure(s)`;
    }
```

In `_renderRuleEditor(rule)`, add an `OVERLAP` case to the `configHtml` `switch`:

```js
        case "OVERLAP":
          configHtml = this._renderOverlapEditor(rule.config);
          break;
```

Add the renderer method, modeled on `_renderCropEditor` (a source select plus an add/remove list of "other" structures):

```js
    _renderOverlapEditor(config) {
      const othersHtml = (config.others || [])
        .map(
          (name, idx) => `
          <div class="flex items-center space-x-2 rbs-overlap-other">
            ${this._renderStructureSelect("rbs-overlap-other-" + idx, name, true, "rbs-overlap-other-select")}
            <button type="button" class="rbs-remove-overlap text-red-600 hover:text-red-800" title="Remove structure">×</button>
          </div>
        `
        )
        .join("");

      return `
        <div class="space-y-4">
          <div>
            <label class="block text-sm font-medium text-gray-700">Source Structure</label>
            ${this._renderStructureSelect("rbs-overlap-source", config.source)}
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-700">Overlapping Structures</label>
            <div id="rbs-overlap-others" class="space-y-2 mt-1">${othersHtml}</div>
            <button type="button" id="rbs-add-overlap-other" class="mt-2 text-sm text-primary-600 hover:text-primary-800">+ Add structure</button>
          </div>
        </div>
      `;
    }
```

In `_collectConfigFromEditor(rule)` (the `switch`, after the `CROP` case), add:

```js
        case "OVERLAP":
          cfg.source = this._getValue("#rbs-overlap-source");
          cfg.others = [];
          this.container.querySelectorAll(".rbs-overlap-other-select").forEach((select) => {
            if (select.value) cfg.others.push(select.value);
          });
          break;
```

In `_attachConfigEventListeners(ruleType)` (the effective definition), add an `OVERLAP` block mirroring the `CROP` block (add button + remove listeners), plus a small `_attachOverlapRemoveListeners` helper modeled on `_attachBoundaryRemoveListeners`:

```js
      if (ruleType === "OVERLAP") {
        this.container.querySelector("#rbs-add-overlap-other").addEventListener("click", () => {
          const othersDiv = this.container.querySelector("#rbs-overlap-others");
          const div = document.createElement("div");
          div.className = "flex items-center space-x-2 rbs-overlap-other";
          div.innerHTML = `
            ${this._renderStructureSelect("rbs-overlap-other-" + Date.now(), "", true, "rbs-overlap-other-select")}
            <button type="button" class="rbs-remove-overlap text-red-600 hover:text-red-800" title="Remove structure">×</button>
          `;
          othersDiv.appendChild(div);
          this._attachOverlapRemoveListeners();
        });
        this._attachOverlapRemoveListeners();
      }
```

and add the helper (next to `_attachBoundaryRemoveListeners`):

```js
    _attachOverlapRemoveListeners() {
      this.container.querySelectorAll(".rbs-remove-overlap").forEach((btn) => {
        btn.onclick = () => btn.closest(".rbs-overlap-other").remove();
      });
    }
```

- [ ] **Step 10: Add the `_rule_summary.html` display branch for OVERLAP**

Add a `{% if rule.rule_type == "OVERLAP" %}` branch in `templates/rule_based_segmentation/_rule_summary.html` showing the source and the list of others (e.g. `Box ∩ [Box2]`). Mirror the CROP branch layout.

- [ ] **Step 11: Run the OVERLAP tests to confirm they pass**

Run: `venv/bin/python manage.py test rule_based_segmentation.tests.test_spatial_rules.OverlapRuleTests -v 2`
Expected: PASS (2 OVERLAP tests).

- [ ] **Step 12: Run the full test suite to confirm no regression**

Run: `venv/bin/python manage.py test rule_based_segmentation -v 1`
Expected: all tests pass.

- [ ] **Step 13: Commit**

```bash
git add rule_based_segmentation/models.py rule_based_segmentation/utils/validators.py rule_based_segmentation/utils/engine.py rule_based_segmentation/views.py rule_based_segmentation/tests/helpers.py rule_based_segmentation/tests/test_spatial_rules.py static/js/rule_based_pipeline_builder.js templates/rule_based_segmentation/_rule_summary.html rule_based_segmentation/migrations/
git commit -m "feat(rbs): add OVERLAP (A ∩ others) rule type"
```

---

## Task 3: EXPAND_SUBTRACT rule (expand source, subtract another)

**Files:**
- Modify: `rule_based_segmentation/models.py`, `utils/validators.py`, `utils/engine.py`, `views.py`, `tests/helpers.py`, `tests/test_spatial_rules.py`
- Modify: `static/js/rule_based_pipeline_builder.js`, `templates/rule_based_segmentation/_rule_summary.html`
- Create: `rule_based_segmentation/migrations/0007_expandsubtractruleconfig.py` (via `makemigrations`)

**Interfaces:**
- Consumes: `SegmentationEngine._expand_mask_by_variant` (Task 1); `boolean_subtraction`; `create_pipeline_with_rules`.
- Produces: `ExpandSubtractRuleConfig` model; `validate_expand_subtract_rule(rule)`; config JSON shape `{"variant","source","subtract","distance_mm","distance_x_mm","distance_y_mm","distance_z_mm","kernel_type"}`.

- [ ] **Step 1: Add the failing engine test**

First, extend the import block at the top of `rule_based_segmentation/tests/test_spatial_rules.py` to include `boolean_subtraction` (used by this test and Task 4):

```python
from dicom_handler.utils.structure_generation.operations import (
    apply_uniform_margin,
    boolean_subtraction,
)
```

Append to `rule_based_segmentation/tests/test_spatial_rules.py`:

```python
class ExpandSubtractRuleTests(SpatialRulesBase):
    def test_expand_subtract_matches_primitives(self):
        engine = self._run_single_rule(
            [
                {
                    "rule_type": "EXPAND_SUBTRACT",
                    "name": "ES",
                    "config": {
                        "variant": "UNIFORM",
                        "source": "Box",
                        "subtract": "Box2",
                        "distance_mm": 1.0,
                        "kernel_type": "ball",
                    },
                }
            ]
        )
        es = engine.available_masks["ES"]
        box = engine.available_masks["Box"]
        box2 = engine.available_masks["Box2"]
        expected = boolean_subtraction(apply_uniform_margin(box, 1.0, "ball"), box2)
        self.assertTrue(np.array_equal(sitk.GetArrayFromImage(es), sitk.GetArrayFromImage(expected)))
        # The result is a subset of the expanded source.
        expanded = apply_uniform_margin(box, 1.0, "ball")
        self.assertEqual(self._volume(sitk.And(es, sitk.Not(expanded))), 0)
```

> Import `boolean_subtraction` is already present at the top of the test module from Task 1.

- [ ] **Step 2: Run the test to confirm it fails**

Run: `venv/bin/python manage.py test rule_based_segmentation.tests.test_spatial_rules.ExpandSubtractRuleTests -v 2`
Expected: FAIL — `EXPAND_SUBTRACT` is not yet a known rule type.

- [ ] **Step 3: Add `EXPAND_SUBTRACT` choice + config in `models.py`**

Add `("EXPAND_SUBTRACT", "Expand & Subtract")` to `RULE_TYPE_CHOICES` (after `OVERLAP`):

```python
        ("OVERLAP", "Overlap"),
        ("EXPAND_SUBTRACT", "Expand & Subtract"),
```

Add the config model (after `OverlapOther`):

```python
class ExpandSubtractRuleConfig(models.Model):
    """Configuration for EXPAND_SUBTRACT rules: expand(source, d) - subtract."""

    VARIANT_CHOICES = [("UNIFORM", "Uniform"), ("ANISOTROPIC", "Anisotropic")]
    KERNEL_CHOICES = [("ball", "Ball"), ("box", "Box"), ("cross", "Cross")]

    pipeline_rule = models.OneToOneField(
        PipelineRule,
        on_delete=models.CASCADE,
        related_name="expand_subtract_config",
        limit_choices_to={"rule_type": "EXPAND_SUBTRACT"},
    )
    variant = models.CharField(max_length=16, choices=VARIANT_CHOICES, default="UNIFORM")
    source = models.CharField(max_length=256, help_text="Structure to expand")
    subtract = models.CharField(max_length=256, help_text="Structure to subtract after expanding")
    distance_mm = models.FloatField(null=True, blank=True, help_text="Uniform expansion distance (mm) for UNIFORM variant")
    distance_x_mm = models.FloatField(null=True, blank=True, help_text="X distance (mm) for ANISOTROPIC variant")
    distance_y_mm = models.FloatField(null=True, blank=True, help_text="Y distance (mm) for ANISOTROPIC variant")
    distance_z_mm = models.FloatField(null=True, blank=True, help_text="Z distance (mm) for ANISOTROPIC variant")
    kernel_type = models.CharField(max_length=16, choices=KERNEL_CHOICES, default="ball", help_text="Structuring element for UNIFORM variant")

    def __str__(self):
        return f"Expand & Subtract config for {self.pipeline_rule_id}"
```

Add `validate_expand_subtract_rule` to the import block in `models.py` and the `clean()` branch:

```python
        elif self.rule_type == "EXPAND_SUBTRACT":
            validate_expand_subtract_rule(self)
```

- [ ] **Step 4: Add `validate_expand_subtract_rule` to `validators.py`**

```python
def validate_expand_subtract_rule(rule):
    config = getattr(rule, "expand_subtract_config", None)
    if not config:
        raise ValidationError("Expand & Subtract rules require a configuration.")
    if not config.source or not config.source.strip():
        raise ValidationError("Expand & Subtract rules require a source structure.")
    if not config.subtract or not config.subtract.strip():
        raise ValidationError("Expand & Subtract rules require a structure to subtract.")
    if config.variant == "UNIFORM":
        if config.distance_mm is None:
            raise ValidationError("Uniform expansion distance is required.")
    else:
        if config.distance_x_mm is None or config.distance_y_mm is None or config.distance_z_mm is None:
            raise ValidationError("Anisotropic expansion distance (X, Y, Z) is required.")
```

- [ ] **Step 5: Generate and apply the migration**

Run: `venv/bin/python manage.py makemigrations rule_based_segmentation`
Then: `venv/bin/python manage.py migrate`
Expected: a new migration for `ExpandSubtractRuleConfig`; applied.

- [ ] **Step 6: Add engine evaluation for EXPAND_SUBTRACT**

In `rule_based_segmentation/utils/engine.py`:

Add the `EXPAND_SUBTRACT` branch to `_collect_required_structures`:

```python
        elif rule.rule_type == "EXPAND_SUBTRACT":
            config = getattr(rule, "expand_subtract_config", None)
            if config:
                if config.source:
                    required_names.add(config.source)
                if config.subtract:
                    required_names.add(config.subtract)
```

Add the `EXPAND_SUBTRACT` branch to `_evaluate_rule`:

```python
        elif rule_type == "EXPAND_SUBTRACT":
            return self._evaluate_expand_subtract_rule(rule)
```

Add the evaluator method on `SegmentationEngine`:

```python
    def _evaluate_expand_subtract_rule(self, rule) -> sitk.Image:
        """Expand & Subtract: expand(source, distance) - subtract."""
        config = rule.expand_subtract_config
        source_mask = self.available_masks[config.source]
        self._ensure_mask_not_empty(source_mask, config.source)
        expanded = self._expand_mask_by_variant(
            source_mask,
            config.variant,
            uniform_mm=config.distance_mm,
            x_mm=config.distance_x_mm,
            y_mm=config.distance_y_mm,
            z_mm=config.distance_z_mm,
            kernel_type=config.kernel_type,
        )
        return boolean_subtraction(expanded, self.available_masks[config.subtract])
```

- [ ] **Step 7: Wire the builder in `views.py`**

Add `ExpandSubtractRuleConfig` to the `from .models import (...)` block.

Add an `EXPAND_SUBTRACT` branch to `_rule_to_json`:

```python
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
        }
```

Add an `EXPAND_SUBTRACT` branch to `_collect_required_structure_names`:

```python
    elif rule_type == "EXPAND_SUBTRACT":
        if config.get("source"):
            names.add(config["source"])
        if config.get("subtract"):
            names.add(config["subtract"])
```

Add an `EXPAND_SUBTRACT` branch to `_save_rule` and the save function:

```python
    elif rule_type == "EXPAND_SUBTRACT":
        _save_expand_subtract_config(rule, config)
```

```python
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
    )
```

Add an `EXPAND_SUBTRACT` branch to `_duplicate_rule`:

```python
    elif rule.rule_type == "EXPAND_SUBTRACT":
        src = rule.expand_subtract_config
        ExpandSubtractRuleConfig.objects.create(
            pipeline_rule=new_rule,
            variant=src.variant,
            source=src.source,
            subtract=src.subtract,
            distance_mm=src.distance_mm,
            distance_x_mm=src.distance_x_mm,
            distance_y_mm=src.distance_y_mm,
            distance_z_mm=src.distance_z_mm,
            kernel_type=src.kernel_type,
        )
```

Add an `EXPAND_SUBTRACT` branch to `_collect_rule_structure_names`:

```python
    elif rule.rule_type == "EXPAND_SUBTRACT":
        config = getattr(rule, "expand_subtract_config", None)
        if config:
            if config.source:
                names.add(config.source)
            if config.subtract:
                names.add(config.subtract)
```

- [ ] **Step 8: Add the test-helper branch in `helpers.py`**

In `create_pipeline_with_rules`, add the `EXPAND_SUBTRACT` branch:

```python
        elif rule_type == "EXPAND_SUBTRACT":
            _create_expand_subtract_config(rule, raw.get("config", {}))
```

Add the helper (import `ExpandSubtractRuleConfig` from `..models`):

```python
def _create_expand_subtract_config(rule, config):
    return ExpandSubtractRuleConfig.objects.create(
        pipeline_rule=rule,
        variant=config.get("variant", "UNIFORM"),
        source=config.get("source", ""),
        subtract=config.get("subtract", ""),
        distance_mm=config.get("distance_mm"),
        distance_x_mm=config.get("distance_x_mm"),
        distance_y_mm=config.get("distance_y_mm"),
        distance_z_mm=config.get("distance_z_mm"),
        kernel_type=config.get("kernel_type", "ball"),
    )
```

- [ ] **Step 9: Add the JS builder editor for EXPAND_SUBTRACT**

In `static/js/rule_based_pipeline_builder.js`, mirror the MARGIN rule, with a second structure select for `subtract`:

Add the `EXPAND_SUBTRACT` label to `RULE_TYPES`:

```js
    EXPAND_SUBTRACT: "Expand & Subtract",
```

In `_defaultConfig(ruleType)` (the `switch`), add:

```js
    case "EXPAND_SUBTRACT":
      return {
        variant: "UNIFORM",
        source: "",
        subtract: "",
        distance_mm: 5,
        distance_x_mm: 5,
        distance_y_mm: 5,
        distance_z_mm: 5,
        kernel_type: "ball",
      };
```

In `_summarizeRule(rule)` (the `switch`), add:

```js
    case "EXPAND_SUBTRACT": {
      const c = rule.config || {};
      const d = c.variant === "ANISOTROPIC" ? `${c.distance_x_mm}/${c.distance_y_mm}/${c.distance_z_mm} mm` : `${c.distance_mm} mm`;
      return `Expand ${c.source || "—"} by ${d}, subtract ${c.subtract || "—"}`;
    }
```

In `_renderRuleEditor(rule)`, add an `EXPAND_SUBTRACT` case to the `configHtml` `switch`:

```js
        case "EXPAND_SUBTRACT":
          configHtml = this._renderExpandSubtractEditor(rule.config);
          break;
```

Add the renderer method (MARGIN-style layout, plus a `subtract` structure select; ids use the `rbs-es-` prefix):

```js
    _renderExpandSubtractEditor(config) {
      return `
        <div class="space-y-4">
          <div>
            <label class="block text-sm font-medium text-gray-700">Variant</label>
            <select id="rbs-es-variant" class="mt-1 block w-full border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm px-3 py-2">
              <option value="UNIFORM" ${config.variant === "UNIFORM" ? "selected" : ""}>Uniform</option>
              <option value="ANISOTROPIC" ${config.variant === "ANISOTROPIC" ? "selected" : ""}>Anisotropic</option>
            </select>
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-700">Structure to Expand</label>
            ${this._renderStructureSelect("rbs-es-source", config.source)}
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-700">Structure to Subtract</label>
            ${this._renderStructureSelect("rbs-es-subtract", config.subtract, true)}
          </div>
          <div id="rbs-es-uniform" class="${config.variant !== "UNIFORM" ? "hidden" : ""}">
            <label class="block text-sm font-medium text-gray-700">Expansion distance (mm)</label>
            <input type="number" step="any" id="rbs-es-mm" value="${config.distance_mm}" class="mt-1 block w-full border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm px-3 py-2">
            <label class="block text-sm font-medium text-gray-700 mt-2">Kernel</label>
            <select id="rbs-es-kernel" class="mt-1 block w-full border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm px-3 py-2">
              ${MARGIN_KERNELS.map((k) => `<option value="${k.value}" ${config.kernel_type === k.value ? "selected" : ""}>${k.label}</option>`).join("")}
            </select>
          </div>
          <div id="rbs-es-anisotropic" class="${config.variant !== "ANISOTROPIC" ? "hidden" : ""}">
            <label class="block text-sm font-medium text-gray-700">Distance X (mm)</label>
            <input type="number" step="any" id="rbs-es-x" value="${config.distance_x_mm}" class="mt-1 block w-full border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm px-3 py-2">
            <label class="block text-sm font-medium text-gray-700 mt-2">Distance Y (mm)</label>
            <input type="number" step="any" id="rbs-es-y" value="${config.distance_y_mm}" class="mt-1 block w-full border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm px-3 py-2">
            <label class="block text-sm font-medium text-gray-700 mt-2">Distance Z (mm)</label>
            <input type="number" step="any" id="rbs-es-z" value="${config.distance_z_mm}" class="mt-1 block w-full border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm px-3 py-2">
          </div>
        </div>
      `;
    }
```

In `_collectConfigFromEditor(rule)` (the `switch`), add:

```js
        case "EXPAND_SUBTRACT":
          cfg.variant = this.container.querySelector("#rbs-es-variant").value;
          cfg.source = this._getValue("#rbs-es-source");
          cfg.subtract = this._getValue("#rbs-es-subtract");
          cfg.distance_mm = parseFloat(this._getValue("#rbs-es-mm")) || 0;
          cfg.distance_x_mm = parseFloat(this._getValue("#rbs-es-x")) || 0;
          cfg.distance_y_mm = parseFloat(this._getValue("#rbs-es-y")) || 0;
          cfg.distance_z_mm = parseFloat(this._getValue("#rbs-es-z")) || 0;
          cfg.kernel_type = this._getValue("#rbs-es-kernel");
          break;
```

In `_attachConfigEventListeners(ruleType)` (the effective definition), add an `EXPAND_SUBTRACT` block mirroring the `MARGIN` toggle (using `#rbs-es-variant`, `#rbs-es-uniform`, `#rbs-es-anisotropic`):

```js
      if (ruleType === "EXPAND_SUBTRACT") {
        const variant = this.container.querySelector("#rbs-es-variant");
        variant.addEventListener("change", () => {
          const isUniform = variant.value === "UNIFORM";
          this.container.querySelector("#rbs-es-uniform").classList.toggle("hidden", !isUniform);
          this.container.querySelector("#rbs-es-anisotropic").classList.toggle("hidden", isUniform);
        });
      }
```

- [ ] **Step 10: Add the `_rule_summary.html` display branch for EXPAND_SUBTRACT**

Add a `{% if rule.rule_type == "EXPAND_SUBTRACT" %}` branch in `templates/rule_based_segmentation/_rule_summary.html` showing source, subtract, distance, and variant. Mirror the RING branch layout.

- [ ] **Step 11: Run the EXPAND_SUBTRACT test to confirm it passes**

Run: `venv/bin/python manage.py test rule_based_segmentation.tests.test_spatial_rules.ExpandSubtractRuleTests -v 2`
Expected: PASS (1 test).

- [ ] **Step 12: Run the full test suite to confirm no regression**

Run: `venv/bin/python manage.py test rule_based_segmentation -v 1`
Expected: all tests pass.

- [ ] **Step 13: Commit**

```bash
git add rule_based_segmentation/models.py rule_based_segmentation/utils/validators.py rule_based_segmentation/utils/engine.py rule_based_segmentation/views.py rule_based_segmentation/tests/helpers.py rule_based_segmentation/tests/test_spatial_rules.py static/js/rule_based_pipeline_builder.js templates/rule_based_segmentation/_rule_summary.html rule_based_segmentation/migrations/
git commit -m "feat(rbs): add EXPAND_SUBTRACT (expand & subtract) rule type"
```

---

## Task 4: AVOID_MARGIN rule (source − expand(avoid, margin)) *(optional)*

**Files:**
- Modify: `rule_based_segmentation/models.py`, `utils/validators.py`, `utils/engine.py`, `views.py`, `tests/helpers.py`, `tests/test_spatial_rules.py`
- Modify: `static/js/rule_based_pipeline_builder.js`, `templates/rule_based_segmentation/_rule_summary.html`
- Create: `rule_based_segmentation/migrations/0008_avoidmarginruleconfig.py` (via `makemigrations`)

**Interfaces:**
- Consumes: `SegmentationEngine._expand_mask_by_variant` (Task 1); `boolean_subtraction`; `create_pipeline_with_rules`.
- Produces: `AvoidMarginRuleConfig` model; `validate_avoid_margin_rule(rule)`; config JSON shape `{"variant","source","avoid","margin_mm","margin_x_mm","margin_y_mm","margin_z_mm","kernel_type"}`.

- [ ] **Step 1: Add the failing engine test**

Append to `rule_based_segmentation/tests/test_spatial_rules.py`:

```python
class AvoidMarginRuleTests(SpatialRulesBase):
    def test_avoid_margin_matches_primitives(self):
        engine = self._run_single_rule(
            [
                {
                    "rule_type": "AVOID_MARGIN",
                    "name": "AM",
                    "config": {
                        "variant": "UNIFORM",
                        "source": "Box",
                        "avoid": "Box2",
                        "margin_mm": 1.0,
                        "kernel_type": "ball",
                    },
                }
            ]
        )
        am = engine.available_masks["AM"]
        box = engine.available_masks["Box"]
        box2 = engine.available_masks["Box2"]
        expected = boolean_subtraction(box, apply_uniform_margin(box2, 1.0, "ball"))
        self.assertTrue(np.array_equal(sitk.GetArrayFromImage(am), sitk.GetArrayFromImage(expected)))
        # The result is a subset of the source.
        self.assertEqual(self._volume(sitk.And(am, sitk.Not(box))), 0)
```

- [ ] **Step 2: Run the test to confirm it fails**

Run: `venv/bin/python manage.py test rule_based_segmentation.tests.test_spatial_rules.AvoidMarginRuleTests -v 2`
Expected: FAIL — `AVOID_MARGIN` is not yet a known rule type.

- [ ] **Step 3: Add `AVOID_MARGIN` choice + config in `models.py`**

Add `("AVOID_MARGIN", "Avoid with Margin")` to `RULE_TYPE_CHOICES` (after `EXPAND_SUBTRACT`):

```python
        ("EXPAND_SUBTRACT", "Expand & Subtract"),
        ("AVOID_MARGIN", "Avoid with Margin"),
```

Add the config model (after `ExpandSubtractRuleConfig`):

```python
class AvoidMarginRuleConfig(models.Model):
    """Configuration for AVOID_MARGIN rules: source - expand(avoid, margin)."""

    VARIANT_CHOICES = [("UNIFORM", "Uniform"), ("ANISOTROPIC", "Anisotropic")]
    KERNEL_CHOICES = [("ball", "Ball"), ("box", "Box"), ("cross", "Cross")]

    pipeline_rule = models.OneToOneField(
        PipelineRule,
        on_delete=models.CASCADE,
        related_name="avoid_margin_config",
        limit_choices_to={"rule_type": "AVOID_MARGIN"},
    )
    variant = models.CharField(max_length=16, choices=VARIANT_CHOICES, default="UNIFORM")
    source = models.CharField(max_length=256, help_text="Structure to keep")
    avoid = models.CharField(max_length=256, help_text="Structure to avoid")
    margin_mm = models.FloatField(null=True, blank=True, help_text="Uniform avoidance margin (mm) for UNIFORM variant")
    margin_x_mm = models.FloatField(null=True, blank=True, help_text="X margin (mm) for ANISOTROPIC variant")
    margin_y_mm = models.FloatField(null=True, blank=True, help_text="Y margin (mm) for ANISOTROPIC variant")
    margin_z_mm = models.FloatField(null=True, blank=True, help_text="Z margin (mm) for ANISOTROPIC variant")
    kernel_type = models.CharField(max_length=16, choices=KERNEL_CHOICES, default="ball", help_text="Structuring element for UNIFORM variant")

    def __str__(self):
        return f"Avoid with Margin config for {self.pipeline_rule_id}"
```

Add `validate_avoid_margin_rule` to the import block in `models.py` and the `clean()` branch:

```python
        elif self.rule_type == "AVOID_MARGIN":
            validate_avoid_margin_rule(self)
```

- [ ] **Step 4: Add `validate_avoid_margin_rule` to `validators.py`**

```python
def validate_avoid_margin_rule(rule):
    config = getattr(rule, "avoid_margin_config", None)
    if not config:
        raise ValidationError("Avoid with Margin rules require a configuration.")
    if not config.source or not config.source.strip():
        raise ValidationError("Avoid with Margin rules require a source structure.")
    if not config.avoid or not config.avoid.strip():
        raise ValidationError("Avoid with Margin rules require a structure to avoid.")
    if config.variant == "UNIFORM":
        if config.margin_mm is None:
            raise ValidationError("Uniform avoidance margin is required.")
    else:
        if config.margin_x_mm is None or config.margin_y_mm is None or config.margin_z_mm is None:
            raise ValidationError("Anisotropic avoidance margin (X, Y, Z) is required.")
```

- [ ] **Step 5: Generate and apply the migration**

Run: `venv/bin/python manage.py makemigrations rule_based_segmentation`
Then: `venv/bin/python manage.py migrate`
Expected: a new migration for `AvoidMarginRuleConfig`; applied.

- [ ] **Step 6: Add engine evaluation for AVOID_MARGIN**

In `rule_based_segmentation/utils/engine.py`:

Add the `AVOID_MARGIN` branch to `_collect_required_structures`:

```python
        elif rule.rule_type == "AVOID_MARGIN":
            config = getattr(rule, "avoid_margin_config", None)
            if config:
                if config.source:
                    required_names.add(config.source)
                if config.avoid:
                    required_names.add(config.avoid)
```

Add the `AVOID_MARGIN` branch to `_evaluate_rule`:

```python
        elif rule_type == "AVOID_MARGIN":
            return self._evaluate_avoid_margin_rule(rule)
```

Add the evaluator method on `SegmentationEngine`:

```python
    def _evaluate_avoid_margin_rule(self, rule) -> sitk.Image:
        """Avoid with Margin: source - expand(avoid, margin)."""
        config = rule.avoid_margin_config
        source_mask = self.available_masks[config.source]
        self._ensure_mask_not_empty(source_mask, config.source)
        avoid_mask = self.available_masks[config.avoid]
        self._ensure_mask_not_empty(avoid_mask, config.avoid)
        expanded = self._expand_mask_by_variant(
            avoid_mask,
            config.variant,
            uniform_mm=config.margin_mm,
            x_mm=config.margin_x_mm,
            y_mm=config.margin_y_mm,
            z_mm=config.margin_z_mm,
            kernel_type=config.kernel_type,
        )
        return boolean_subtraction(source_mask, expanded)
```

- [ ] **Step 7: Wire the builder in `views.py`**

Add `AvoidMarginRuleConfig` to the `from .models import (...)` block.

Add an `AVOID_MARGIN` branch to `_rule_to_json`:

```python
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
        }
```

Add an `AVOID_MARGIN` branch to `_collect_required_structure_names`:

```python
    elif rule_type == "AVOID_MARGIN":
        if config.get("source"):
            names.add(config["source"])
        if config.get("avoid"):
            names.add(config["avoid"])
```

Add an `AVOID_MARGIN` branch to `_save_rule` and the save function:

```python
    elif rule_type == "AVOID_MARGIN":
        _save_avoid_margin_config(rule, config)
```

```python
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
    )
```

Add an `AVOID_MARGIN` branch to `_duplicate_rule`:

```python
    elif rule.rule_type == "AVOID_MARGIN":
        src = rule.avoid_margin_config
        AvoidMarginRuleConfig.objects.create(
            pipeline_rule=new_rule,
            variant=src.variant,
            source=src.source,
            avoid=src.avoid,
            margin_mm=src.margin_mm,
            margin_x_mm=src.margin_x_mm,
            margin_y_mm=src.margin_y_mm,
            margin_z_mm=src.margin_z_mm,
            kernel_type=src.kernel_type,
        )
```

Add an `AVOID_MARGIN` branch to `_collect_rule_structure_names`:

```python
    elif rule.rule_type == "AVOID_MARGIN":
        config = getattr(rule, "avoid_margin_config", None)
        if config:
            if config.source:
                names.add(config.source)
            if config.avoid:
                names.add(config.avoid)
```

- [ ] **Step 8: Add the test-helper branch in `helpers.py`**

In `create_pipeline_with_rules`, add the `AVOID_MARGIN` branch:

```python
        elif rule_type == "AVOID_MARGIN":
            _create_avoid_margin_config(rule, raw.get("config", {}))
```

Add the helper (import `AvoidMarginRuleConfig` from `..models`):

```python
def _create_avoid_margin_config(rule, config):
    return AvoidMarginRuleConfig.objects.create(
        pipeline_rule=rule,
        variant=config.get("variant", "UNIFORM"),
        source=config.get("source", ""),
        avoid=config.get("avoid", ""),
        margin_mm=config.get("margin_mm"),
        margin_x_mm=config.get("margin_x_mm"),
        margin_y_mm=config.get("margin_y_mm"),
        margin_z_mm=config.get("margin_z_mm"),
        kernel_type=config.get("kernel_type", "ball"),
    )
```

- [ ] **Step 9: Add the JS builder editor for AVOID_MARGIN**

In `static/js/rule_based_pipeline_builder.js`, mirror the MARGIN rule, with a second structure select for `avoid`:

Add the `AVOID_MARGIN` label to `RULE_TYPES`:

```js
    AVOID_MARGIN: "Avoid with Margin",
```

In `_defaultConfig(ruleType)` (the `switch`), add:

```js
    case "AVOID_MARGIN":
      return {
        variant: "UNIFORM",
        source: "",
        avoid: "",
        margin_mm: 5,
        margin_x_mm: 5,
        margin_y_mm: 5,
        margin_z_mm: 5,
        kernel_type: "ball",
      };
```

In `_summarizeRule(rule)` (the `switch`), add:

```js
    case "AVOID_MARGIN": {
      const c = rule.config || {};
      const d = c.variant === "ANISOTROPIC" ? `${c.margin_x_mm}/${c.margin_y_mm}/${c.margin_z_mm} mm` : `${c.margin_mm} mm`;
      return `Avoid ${c.avoid || "—"} by ${d} from ${c.source || "—"}`;
    }
```

In `_renderRuleEditor(rule)`, add an `AVOID_MARGIN` case to the `configHtml` `switch`:

```js
        case "AVOID_MARGIN":
          configHtml = this._renderAvoidMarginEditor(rule.config);
          break;
```

Add the renderer method (MARGIN-style layout, plus an `avoid` structure select; ids use the `rbs-am-` prefix):

```js
    _renderAvoidMarginEditor(config) {
      return `
        <div class="space-y-4">
          <div>
            <label class="block text-sm font-medium text-gray-700">Variant</label>
            <select id="rbs-am-variant" class="mt-1 block w-full border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm px-3 py-2">
              <option value="UNIFORM" ${config.variant === "UNIFORM" ? "selected" : ""}>Uniform</option>
              <option value="ANISOTROPIC" ${config.variant === "ANISOTROPIC" ? "selected" : ""}>Anisotropic</option>
            </select>
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-700">Structure to Keep</label>
            ${this._renderStructureSelect("rbs-am-source", config.source)}
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-700">Structure to Avoid</label>
            ${this._renderStructureSelect("rbs-am-avoid", config.avoid, true)}
          </div>
          <div id="rbs-am-uniform" class="${config.variant !== "UNIFORM" ? "hidden" : ""}">
            <label class="block text-sm font-medium text-gray-700">Avoidance margin (mm)</label>
            <input type="number" step="any" id="rbs-am-mm" value="${config.margin_mm}" class="mt-1 block w-full border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm px-3 py-2">
            <label class="block text-sm font-medium text-gray-700 mt-2">Kernel</label>
            <select id="rbs-am-kernel" class="mt-1 block w-full border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm px-3 py-2">
              ${MARGIN_KERNELS.map((k) => `<option value="${k.value}" ${config.kernel_type === k.value ? "selected" : ""}>${k.label}</option>`).join("")}
            </select>
          </div>
          <div id="rbs-am-anisotropic" class="${config.variant !== "ANISOTROPIC" ? "hidden" : ""}">
            <label class="block text-sm font-medium text-gray-700">Margin X (mm)</label>
            <input type="number" step="any" id="rbs-am-x" value="${config.margin_x_mm}" class="mt-1 block w-full border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm px-3 py-2">
            <label class="block text-sm font-medium text-gray-700 mt-2">Margin Y (mm)</label>
            <input type="number" step="any" id="rbs-am-y" value="${config.margin_y_mm}" class="mt-1 block w-full border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm px-3 py-2">
            <label class="block text-sm font-medium text-gray-700 mt-2">Margin Z (mm)</label>
            <input type="number" step="any" id="rbs-am-z" value="${config.margin_z_mm}" class="mt-1 block w-full border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm px-3 py-2">
          </div>
        </div>
      `;
    }
```

In `_collectConfigFromEditor(rule)` (the `switch`), add:

```js
        case "AVOID_MARGIN":
          cfg.variant = this.container.querySelector("#rbs-am-variant").value;
          cfg.source = this._getValue("#rbs-am-source");
          cfg.avoid = this._getValue("#rbs-am-avoid");
          cfg.margin_mm = parseFloat(this._getValue("#rbs-am-mm")) || 0;
          cfg.margin_x_mm = parseFloat(this._getValue("#rbs-am-x")) || 0;
          cfg.margin_y_mm = parseFloat(this._getValue("#rbs-am-y")) || 0;
          cfg.margin_z_mm = parseFloat(this._getValue("#rbs-am-z")) || 0;
          cfg.kernel_type = this._getValue("#rbs-am-kernel");
          break;
```

In `_attachConfigEventListeners(ruleType)` (the effective definition), add an `AVOID_MARGIN` block mirroring the `MARGIN` toggle (using `#rbs-am-variant`, `#rbs-am-uniform`, `#rbs-am-anisotropic`):

```js
      if (ruleType === "AVOID_MARGIN") {
        const variant = this.container.querySelector("#rbs-am-variant");
        variant.addEventListener("change", () => {
          const isUniform = variant.value === "UNIFORM";
          this.container.querySelector("#rbs-am-uniform").classList.toggle("hidden", !isUniform);
          this.container.querySelector("#rbs-am-anisotropic").classList.toggle("hidden", isUniform);
        });
      }
```

- [ ] **Step 10: Add the `_rule_summary.html` display branch for AVOID_MARGIN**

Add a `{% if rule.rule_type == "AVOID_MARGIN" %}` branch in `templates/rule_based_segmentation/_rule_summary.html` showing source, avoid, margin, and variant. Mirror the RING branch layout.

- [ ] **Step 11: Run the AVOID_MARGIN test to confirm it passes**

Run: `venv/bin/python manage.py test rule_based_segmentation.tests.test_spatial_rules.AvoidMarginRuleTests -v 2`
Expected: PASS (1 test).

- [ ] **Step 12: Run the full test suite to confirm no regression**

Run: `venv/bin/python manage.py test rule_based_segmentation -v 1`
Expected: all tests pass.

- [ ] **Step 13: Commit**

```bash
git add rule_based_segmentation/models.py rule_based_segmentation/utils/validators.py rule_based_segmentation/utils/engine.py rule_based_segmentation/views.py rule_based_segmentation/tests/helpers.py rule_based_segmentation/tests/test_spatial_rules.py static/js/rule_based_pipeline_builder.js templates/rule_based_segmentation/_rule_summary.html rule_based_segmentation/migrations/
git commit -m "feat(rbs): add AVOID_MARGIN (avoid with margin) rule type"
```

---

## Task 5: Final verification — full suite, integration-point grep, and docs sync

**Files:**
- Verify (no new code expected): every integration point for all four rule types is present.

- [ ] **Step 1: Run the entire test suite**

Run: `venv/bin/python manage.py test rule_based_segmentation -v 1`
Expected: all tests pass, including the new `tests/test_spatial_rules.py` (RING, OVERLAP, EXPAND_SUBTRACT, AVOID_MARGIN) and all pre-existing suites.

- [ ] **Step 2: Run Django system checks**

Run: `venv/bin/python manage.py check`
Expected: `System check identified no issues`.

- [ ] **Step 3: Confirm every integration point is covered (grep audit)**

Run: `rg -n "RING|OVERLAP|EXPAND_SUBTRACT|AVOID_MARGIN" rule_based_segmentation static/js/rule_based_pipeline_builder.js templates/rule_based_segmentation`
Expected: each of the four rule types appears in **all** of these files:
- `models.py` (choice + config model + `clean()` branch + import)
- `utils/validators.py`
- `utils/engine.py` (`_collect_required_structures`, `_evaluate_rule`, evaluator)
- `views.py` (`_rule_to_json`, `_collect_required_structure_names`, `_save_rule` + `_save_*_config`, `_duplicate_rule`, `_collect_rule_structure_names`, import)
- `tests/helpers.py` (`create_pipeline_with_rules` branch + `_create_*_config`)
- `static/js/rule_based_pipeline_builder.js` (`RULE_TYPES`, `_defaultConfig`, `_summarizeRule`, `_renderRuleEditor` + renderer, `_collectConfigFromEditor`, `_attachConfigEventListeners`)
- `templates/rule_based_segmentation/_rule_summary.html`
- `tests/test_spatial_rules.py`
- a migration in `rule_based_segmentation/migrations/`

If any rule type is missing from a file, fix it before proceeding.

- [ ] **Step 4: Confirm the migrations are in order and apply cleanly**

Run: `venv/bin/python manage.py showmigrations rule_based_segmentation`
Expected: all migrations (including the new ones) are applied; no missing dependencies.

- [ ] **Step 5: Verify no stray references / typos in the JS (syntax check)**

Run: `node --check static/js/rule_based_pipeline_builder.js` (if `node` is available) or open the builder page and confirm the four new operations appear in the "Operation" dropdown and each renders an editor without a JS error (check the browser console).
Expected: no syntax errors; all four labels present in the dropdown.

- [ ] **Step 6: Final commit (only if Step 3–5 produced fixes)**

If any fixes were made, commit them:

```bash
git add -A
git commit -m "chore(rbs): complete spatial rule operations integration"
```

If no fixes were needed, skip this step (each task already committed).

---

## Rollout / deployment notes

- Migrations are additive (new config models); run `manage.py migrate` on the target. No DB data migration is required — existing pipelines have no rules of these types.
- No Celery, queue, or work-dir changes are needed; these rules flow through the existing chain (`prepare_job → run_rule_step → finalize_job`) unchanged.
- No `settings.py` changes required.
- After deploy, the four operations appear in the pipeline builder's "Operation" dropdown automatically (the dropdown is generated from `RULE_TYPES`).
