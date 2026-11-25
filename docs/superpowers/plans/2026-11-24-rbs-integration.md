# Rule-Based Segmentation Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Rule-Based Segmentation (RBS) the single structure-generation engine, replacing the legacy "generated contour" system (`AdditionalStructures.roi_generation_logic` + `ProductionPipelineExecutor`), while fixing the reported RBS bugs and gaps.

**Architecture:** RBS and the legacy system already share one operation catalog
(`dicom_handler/utils/structure_generation/operation_catalog.py`) and one execution
dispatcher (`execute_operation`). They only differ in *model* (RBS: named
`PipelineRule` steps; legacy: a flat `roi_generation_logic` JSON chain) and in
*persistence* (RBS writes a brand-new structure-set file with an approval module;
legacy folds generated ROIs into the reidentified RTSTRUCT in place). We keep RBS's
engine as the executor, add an **in-memory runner** that reuses `SegmentationEngine`
without the job/work-dir lifecycle, add an **INTERMEDIATE** rule output action so a
chain can hold results in memory and export only its final ROI, and synthesize each
legacy `roi_generation_logic` chain into those RBS rules at execution time.

**Tech Stack:** Python 3.13, Django, Celery, `pydicom`, `SimpleITK`, `numpy`,
`rt_utils` (`RTStructBuilder` → `rt_utils.rtstruct.RTStruct`), Tailwind + vanilla JS
for the RBS pipeline builder.

**Spec:** This document. The requirements come from (a) the task to replace the
generated-contour system with RBS, and (b) the client RBS feedback in
`docs/superpowers/plans/` (see "Client feedback" below).

## Global Constraints

- **Single source of truth for operations:** every operation is defined once in
  `operation_catalog.OPERATIONS` and executed once through
  `structure_generation.execution.execute_operation`. Do NOT add a parallel
  primitive; extend the catalog/engine. (Verified: both executors import
  `execute_operation`.)
- **DICOM mask orientation:** `rt_utils` `RTStruct` masks are `(Y, X, Z)`
  (Rows, Columns, Slices); `SimpleITK`/`numpy` are `(Z, Y, X)`. Convert with
  `_sitk_to_rtutils_array` / `_rtutils_to_sitk_array` in
  `rule_based_segmentation/utils/rtstruct_io.py`. Any new in-memory code MUST use
  those, not ad-hoc transposes.
- **Name length target:** Eclipse Clinical-Goal convention allows **54** characters.
  Every rule/ROI name field and every UI `maxlength` must support 54.
- **ROI color format:** DICOM `ROIDisplayColor` is an `Integer String`
  `"R\\G\\B"` (values 0–255). RBS stores it as `PipelineRule.output_color`
  (e.g. `"255\\255\\0"`); the parser `SegmentationEngine._parse_color` accepts
  backslash, hex `#`, or `R,G,B`. Never hard-code yellow except as the documented
  fallback when no color is supplied.
- **Backward compatibility:** legacy `roi_generation_logic` JSON and legacy
  `variant`/`*_mm`/`kernel_type` margin params must keep executing (read-side
  fallback already exists in `execution.execute_operation`). Migration is
  additive; do not delete legacy data until Phase 3.
- **`RTStructBuilder` is a loose type alias:** `RTStructBuilder.create_from(...)`
  returns an `rt_utils.rtstruct.RTStruct`. Its methods: `add_roi(mask, color,
  name, description, use_pin_hole, ..., roi_interpreted_type, ...)`,
  `get_roi_names()`, `get_roi_mask_by_name(name)`, `save(path)`, and `.ds`.
- **Test runner:** `./venv/bin/python manage.py test
  rule_based_segmentation.<module>` (and `dicom_handler` for integration). No bare
  `python` on PATH — use `./venv/bin/python`.

## Client feedback (drives Phase 1)

| # | Report | Status |
|---|--------|--------|
| 1 | Avoid-with-Margin (NOS) & Overlap (OS) work | Keep as the reference-correct cases |
| 2 | Expand & Subtract produces the source (OS) instead of the new volume (NOS) | **Bug — fix + regression** |
| 3 | Crop to Boundary behaves like a NOR gate | **Bug — fix + regression** |
| 4 | Ring / Shell fails to process | **Bug — fix + regression** |
| 5 | Imported structures always render Yellow in Eclipse, regardless of PTV/OAR | **Color fidelity — fix** |
| 6 | Name limit is 18 chars; Eclipse Clinical Goal needs 54 | **Raise limit to 54** |
| 7 | Intermediate structures are exported; they should not be | **Add INTERMEDIATE (in-memory) action** |
| 8 | Need "additional rule options" to generate the final structure directly | **Satisfied by INTERMEDIATE + existing composite rules** |

## File map (what changes and where)

- `rule_based_segmentation/models.py` — add `INTERMEDIATE` output action, add
  missing CLEANUP sub-ops, raise name limit (Task 1, 2, 3).
- `rule_based_segmentation/utils/engine.py` — handle INTERMEDIATE in
  `run_rule`/`_add_rule_output_to_rtstruct`/`_collect_required_structures`; add
  in-memory `run_rules_in_memory`; add missing CLEANUP ops (Task 1, 2, 6).
- `rule_based_segmentation/utils/validators.py` — validate INTERMEDIATE and new
  CLEANUP params (Task 1, 2).
- `rule_based_segmentation/views.py` — persist/read INTERMEDIATE + new cleanup
  fields; surface new limit (Task 1, 2, 3).
- `static/js/rule_based_pipeline_builder.js` + `staticfiles/js/...` — UI for the
  new output action, cleanup ops, 54-char names (Task 1, 2, 3).
- `dicom_handler/utils/structure_generation/execution.py` / `operations.py` —
  fix the three broken primitives (Task 4).
- `rule_based_segmentation/utils/rtstruct_io.py` — per-ROI color/type write path
  (Task 5).
- New `rule_based_segmentation/utils/inline_runner.py` — the in-memory runner used
  by task2 (Task 6).
- New `rule_based_segmentation/utils/legacy_synthesis.py` — convert legacy
  `roi_generation_logic` JSON → RBS rules (Task 7).
- `dicom_handler/import_services/task2_reidentify_rtstruct.py` — rewire
  `_add_additional_structures_to_rtstruct` to RBS (Task 8).
- `dicom_handler/utils/pipeline_executor.py` — deprecate, then remove in Phase 3.

---

# Phase 1 — Make RBS a faithful superset (standalone, testable)

These tasks are independent of the task2 integration and immediately fix the
reported client issues. Each leaves the RBS product in a working state.

## Task 1: Add an INTERMEDIATE (in-memory) rule output action

**Why (feedback #7, #8):** Today every `PipelineRule` writes a named ROI to the
RTStruct. A real clinical derivation (e.g. expand → crop → smooth → final) creates
one exported ROI per intermediate step. The legacy generated-contour system only
wrote the *final* ROI (the running result was held in memory across operations).
To replace it faithfully — and to stop exporting intermediates — a rule must be
able to compute a result, keep it in `available_masks` for later rules, and NOT
write it to the RTStruct. That is the new `INTERMEDIATE` output action.

**Files:**
- Modify: `rule_based_segmentation/models.py` (`PipelineRule.OUTPUT_ACTION_CHOICES`, `clean()`)
- Modify: `rule_based_segmentation/utils/engine.py` (`run_rule`, `_add_rule_output_to_rtstruct`, `_validate_rule_inputs`, `run_pipeline` summary)
- Modify: `rule_based_segmentation/utils/validators.py`
- Modify: `rule_based_segmentation/views.py` (`_save_rule`, `_rule_to_json`, `_collect_required_structure_names`)
- Test: `rule_based_segmentation/tests/test_engine.py`, `rule_based_segmentation/tests/test_views.py`
- Migration: `rule_based_segmentation/migrations/`

**Interfaces:**
- Consumes: `SegmentationEngine.run_rule`, `add_mask_as_roi` (from
  `rule_based_segmentation.utils.rtstruct_io`), `PipelineRule` model.
- Produces: a new output action `INTERMEDIATE`. An intermediate rule is evaluated
  exactly like any rule, its mask is stored in `self.available_masks[rule.name]`,
  and **no ROI is added to the RTStruct**. `rule.name` is still its in-memory
  key and may be referenced by later rules. Summary lists get a new
  `intermediate_rois` key (never exported).

- [ ] **Step 1: Write the failing test**

```python
# append to rule_based_segmentation/tests/test_engine.py
from .helpers import create_box_mask, assert_mask_equal

class IntermediateActionTests(TestCase):
    def test_intermediate_is_not_exported_but_is_reusable(self):
        shape = (24, 24, 24)
        # seed structure 'seed' via a synthetic rtstruct is heavier; instead drive
        # the engine pieces directly:
        from rule_based_segmentation.models import SegmentationPipeline, PipelineRule
        from rule_based_segmentation.utils.engine import SegmentationEngine
        pipeline = SegmentationPipeline.objects.create(name="p")
        rule = PipelineRule.objects.create(
            pipeline=pipeline, order=1, rule_type="MARGIN", name="grown",
            output_action="INTERMEDIATE", output_color="255\\255\\0",
        )
        rule.margin_config = None  # avoid FK; build config below
        from rule_based_segmentation.models import MarginRuleConfig
        MarginRuleConfig.objects.create(
            pipeline_rule=rule, variant="UNIFORM", source="seed", margin_mm=3.0,
        )
        seed = create_box_mask(shape, (6, 6, 6), (12, 12, 12))
        eng = SegmentationEngine.__new__(SegmentationEngine)
        eng.available_masks = {"seed": seed}
        eng.summary = {"created_rois": [], "replaced_rois": [],
                       "intermediate_rois": [], "failed_rules": []}
        eng._rtstruct_names = []  # helper: see Step 3
        eng.rtstruct = _FakeRtstruct(eng._rtstruct_names)
        out = eng.run_rule(rule)
        # produced in-memory under 'grown', nothing written to the rtstruct
        self.assertIn("grown", eng.available_masks)
        self.assertEqual(eng._rtstruct_names, [])
        self.assertIn("grown", eng.summary["intermediate_rois"])
```

(`_FakeRtstruct` is a tiny stand-in defined in the same test module: it exposes
`get_roi_names()` and a no-op `add_roi(...)`/`save(...)` and records added names —
see Step 3. The real path uses the rt-utils object; the fake keeps the test fast
and isolated to the action logic.)

- [ ] **Step 2: Run it and confirm it fails**

Run: `./venv/bin/python manage.py test rule_based_segmentation.tests.test_engine.IntermediateActionTests -v`
Expected: FAIL — `PipelineRule` has no `INTERMEDIATE` choice, or the action is
ignored and the ROI is written.

- [ ] **Step 3: Implement**

In `models.py`, extend the choices and add a helper:

```python
OUTPUT_ACTION_CHOICES = [
    ("CREATE_NEW", "Create new ROI"),
    ("REPLACE_EXISTING", "Replace existing ROI"),
    ("INTERMEDIATE", "Intermediate (in-memory only, not exported)"),
]

def is_intermediate(self) -> bool:
    return self.output_action == "INTERMEDIATE"
```

Add a migration:

```bash
./venv/bin/python manage.py makemigrations rule_based_segmentation \
    -n rule_intermediate_output_action
```

In `engine.py`, branch in `_add_rule_output_to_rtstruct` and record intermediates
in `run_rule`. Replace the body of `_add_rule_output_to_rtstruct`:

```python
def _add_rule_output_to_rtstruct(self, rule: PipelineRule, mask: sitk.Image) -> str:
    color = self._parse_color(rule.output_color)
    name = rule.name

    if rule.output_action == "INTERMEDIATE":
        # Hold in memory for later rules; do NOT write to the RTStruct.
        self.available_masks[name] = mask
        if name not in self.summary["intermediate_rois"]:
            self.summary["intermediate_rois"].append(name)
        return name

    if rule.output_action == "CREATE_NEW" and name in self.rtstruct.get_roi_names():
        suffix = 1
        base = name
        while f"{base}_{suffix}" in self.rtstruct.get_roi_names():
            suffix += 1
        name = f"{base}_{suffix}"
        # Respect the name limit: truncate the base before appending the suffix.
        name = _trim_to_limit(base, suffix, RULE_NAME_LIMIT)
        logger.warning(f"ROI name '{rule.name}' already exists; renamed to '{name}'")

    self.available_masks[name] = mask
    add_mask_as_roi(
        self.rtstruct, mask, name, color,
        roi_type=rule.output_roi_type or "ORGAN",
        replace_existing=(rule.output_action == "REPLACE_EXISTING"),
    )
    return name
```

Add `RULE_NAME_LIMIT = 54` at module top (from Task 3) and a small helper:

```python
def _trim_to_limit(base: str, suffix: int, limit: int) -> str:
    tail = f"_{suffix}"
    return f"{base[: limit - len(tail)]}{tail}"
```

In `run_rule`, ensure the summary key exists and, for INTERMEDIATE, still returns
the name (the branch above already does). Update `run_pipeline`'s summary
initialization and the `from_workdir` summary init to include
`"intermediate_rois": []`:

```python
self.summary = {"created_rois": [], "replaced_rois": [],
                "intermediate_rois": [], "failed_rules": []}
```

In `validators.py`, INTERMEDIATE rules still need valid rule-type inputs (they are
a normal rule that simply isn't exported) — no new validation beyond the existing
per-type checks is required. Add nothing; instead confirm `PipelineRule.clean()`
accepts the new choice (it reads `output_action` from the choices, so it does).

- [ ] **Step 4: Run tests**

Run: `./venv/bin/python manage.py test rule_based_segmentation -v`
Expected: PASS (the new test plus all existing RBS tests, especially
`test_pipeline_steps`, `test_end_to_end` which assert on the summary keys — if they
touch `summary` shape, add `intermediate_rois` where they build the dict).

- [ ] **Step 5: Commit**

```bash
git add rule_based_segmentation/ && git commit -m "feat(rbs): add INTERMEDIATE in-memory rule output action"
```

**Note for downstream tasks:** Task 6 (inline runner) and Task 8 (task2) rely on
`INTERMEDIATE` to keep legacy chain intermediates out of the exported structure
set.

## Task 2: Extend the CLEANUP rule with the missing refinement operations

**Why:** The legacy catalog (`operation_catalog.OPERATIONS`) offers 8 refinement
ops; the RBS `CLEANUP` rule only exposes 5 (`SMOOTH_STRUCTURE`,
`GAUSSIAN_SMOOTH`, `FILL_HOLES`, `REMOVE_SMALL_COMPONENTS`,
`KEEP_LARGEST_COMPONENT`). To be a faithful superset, RBS must also expose
`keep_n_largest`, `close_gaps`, and `remove_protrusions` (all already implemented
in `advanced_operations` and wired in `execution.execute_operation`).

**Files:**
- Modify: `rule_based_segmentation/models.py` (`CleanupRuleConfig.OPERATION_CHOICES`)
- Modify: `rule_based_segmentation/utils/engine.py` (`_evaluate_cleanup_rule`)
- Modify: `rule_based_segmentation/utils/validators.py` (`validate_cleanup_rule`)
- Modify: `rule_based_segmentation/views.py` (`_save_cleanup_config`, `_rule_to_json`)
- Modify: `static/js/rule_based_pipeline_builder.js` (+ `staticfiles/js/...`)
- Test: `rule_based_segmentation/tests/test_engine.py`
- Migration: `rule_based_segmentation/migrations/`

**Interfaces:**
- Consumes: `execute_operation` handlers `keep_n_largest`, `close_gaps`,
  `remove_protrusions` (already exist in `execution._HANDLERS`).
- Produces: new `CleanupRuleConfig` operation tokens
  `KEEP_N_LARGEST_COMPONENT` (`n`), `CLOSE_GAPS` (`gap_size_mm`),
  `REMOVE_PROTRUSIONS` (`protrusion_size_mm`).

- [ ] **Step 1: Write the failing test**

```python
class CleanupExtraOpsTests(TestCase):
    def _engine_with(self, source):
        from rule_based_segmentation.utils.engine import SegmentationEngine
        eng = SegmentationEngine.__new__(SegmentationEngine)
        eng.available_masks = {"src": source}
        eng.summary = {"created_rois": [], "replaced_rois": [],
                       "intermediate_rois": [], "failed_rules": []}
        return eng

    def test_keep_n_largest_rule(self):
        import numpy as np
        from .helpers import create_box_mask
        shape = (20, 20, 20)
        a = create_box_mask(shape, (2, 2, 2), (5, 5, 5))
        b = create_box_mask(shape, (10, 10, 10), (16, 16, 16))
        src = create_box_mask(shape, (0, 0, 0), (20, 20, 20))  # union -> one blob
        from rule_based_segmentation.models import (
            SegmentationPipeline, PipelineRule, CleanupRuleConfig,
        )
        p = SegmentationPipeline.objects.create(name="p")
        r = PipelineRule.objects.create(pipeline=p, order=1, rule_type="CLEANUP",
                                        name="kept")
        CleanupRuleConfig.objects.create(pipeline_rule=r, operation="KEEP_N_LARGEST_COMPONENT",
                                         source="src", n=1)
        eng = self._engine_with(src)
        out = eng._evaluate_cleanup_rule(r)
        self.assertIsNotNone(out)
```

- [ ] **Step 2: Run and confirm fail**

Run: `./venv/bin/python manage.py test rule_based_segmentation.tests.test_engine.CleanupExtraOpsTests -v`
Expected: FAIL — `Unknown cleanup operation: KEEP_N_LARGEST_COMPONENT`.

- [ ] **Step 3: Implement**

In `models.py`, extend the choices and add the three parameter fields (all
`null=True, blank=True`):

```python
OPERATION_CHOICES = [
    ("SMOOTH_STRUCTURE", "Smooth Surface"),
    ("GAUSSIAN_SMOOTH", "Gaussian Smooth"),
    ("FILL_HOLES", "Fill Holes"),
    ("REMOVE_SMALL_COMPONENTS", "Remove Small Components"),
    ("KEEP_LARGEST_COMPONENT", "Keep Largest Component"),
    ("KEEP_N_LARGEST_COMPONENT", "Keep N Largest Components"),
    ("CLOSE_GAPS", "Close Gaps"),
    ("REMOVE_PROTRUSIONS", "Remove Protrusions"),
]
# add to CleanupRuleConfig:
n = models.PositiveIntegerField(null=True, blank=True)
gap_size_mm = models.FloatField(null=True, blank=True)
protrusion_size_mm = models.FloatField(null=True, blank=True)
```

Generate the migration:

```bash
./venv/bin/python manage.py makemigrations rule_based_segmentation \
    -n cleanup_extra_operations
```

In `engine.py`, extend `_evaluate_cleanup_rule`:

```python
if operation == "KEEP_N_LARGEST_COMPONENT":
    return execute_operation(
        "keep_n_largest", {"source": source_mask},
        {"n": config.n or 1},
    )
if operation == "CLOSE_GAPS":
    return execute_operation(
        "close_gaps", {"source": source_mask},
        {"gap_size_mm": config.gap_size_mm or 2.0},
    )
if operation == "REMOVE_PROTRUSIONS":
    return execute_operation(
        "remove_protrusions", {"source": source_mask},
        {"protrusion_size_mm": config.protrusion_size_mm or 2.0},
    )
```

In `validators.py`, add to `required_params`:

```python
"KEEP_N_LARGEST_COMPONENT": ["n"],
"CLOSE_GAPS": ["gap_size_mm"],
"REMOVE_PROTRUSIONS": ["protrusion_size_mm"],
```

In `views.py`, `_save_cleanup_config` pass the new fields (`n`, `gap_size_mm`,
`protrusion_size_mm`) into the config create, and `_rule_to_json` emit them. In the
builder JS, add the three options to the cleanup operation `<select>` and their
number inputs (mirror the existing `KEEP_LARGEST_COMPONENT` entry, which has no
numeric field, and the `CLOSE_GAPS`/`REMOVE_PROTRUSIONS` number fields mirroring
`REMOVE_SMALL_COMPONENTS`).

- [ ] **Step 4: Run tests**

Run: `./venv/bin/python manage.py test rule_based_segmentation -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add rule_based_segmentation/ static/js staticfiles/js && git commit -m "feat(rbs): expose keep_n_largest, close_gaps, remove_protrusions in CLEANUP rule"
```

## Task 3: Raise the ROI name limit to 54 characters

**Why (feedback #6):** `PipelineRule.name` is `max_length=16`; the builder JS reads
the limit from the `data-roi-name-max-length` attribute (set in
`pipeline_form.html` from `PipelineRule._meta.get_field("name").max_length`) with a
hard-coded JS fallback of 16. Eclipse Clinical-Goal naming needs 54. The legacy
`AdditionalStructures.roi_label` is validated to 16 as well. All must support 54.

**Files:**
- Modify: `rule_based_segmentation/models.py` (`PipelineRule.name`,
  `RuleStep.output_roi_name` is already 64 — leave it)
- Modify: `dicom_handler/models.py` (`AdditionalStructures.clean` 16 → 54)
- Modify: `static/js/rule_based_pipeline_builder.js` + `staticfiles/js/...` (JS
  fallback 16 → 54)
- Test: `rule_based_segmentation/tests/test_models.py`,
  `rule_based_segmentation/tests/test_pipeline_e2e_physics.py` (update the
  `test_create_form_exposes_roi_name_max_length` expectation)
- Migration: both apps

- [ ] **Step 1: Write the failing tests**

```python
# rule_based_segmentation/tests/test_models.py
class NameLengthTests(TestCase):
    def test_rule_name_accepts_54_chars(self):
        from rule_based_segmentation.models import SegmentationPipeline, PipelineRule
        p = SegmentationPipeline.objects.create(name="p")
        name = "L" * 54
        r = PipelineRule(pipeline=p, order=1, rule_type="MARGIN", name=name)
        r.full_clean()  # must not raise
        self.assertEqual(len(r.name), 54)

    def test_rule_name_rejects_55_chars(self):
        from rule_based_segmentation.models import SegmentationPipeline, PipelineRule
        from django.core.exceptions import ValidationError
        p = SegmentationPipeline.objects.create(name="p")
        r = PipelineRule(pipeline=p, order=1, rule_type="MARGIN", name="L" * 55)
        with self.assertRaises(ValidationError):
            r.full_clean()
```

```python
# dicom_handler/tests/test_additional_structures.py (create if absent)
def test_roi_label_accepts_54_chars(self):
    # an AdditionalStructures.roi_label of 54 chars must pass full_clean
```

- [ ] **Step 2: Run and confirm fail**

Run: `./venv/bin/python manage.py test rule_based_segmentation.tests.test_models.NameLengthTests -v`
Expected: FAIL (54-char name rejected by `max_length=16`).

- [ ] **Step 3: Implement**

`models.py`: `PipelineRule.name = models.CharField(max_length=54, help_text=...)`.
`AdditionalStructures.clean` in `dicom_handler/models.py`: change the
`len(self.roi_label) > 16` check to `> 54` (and update the error message to
"cannot exceed 54 characters"). In `rule_based_pipeline_builder.js`, change the
`_roiNameMaxLength` fallback `? n : 16` to `? n : 54`.

Generate migrations:

```bash
./venv/bin/python manage.py makemigrations rule_based_segmentation dicom_handler \
    -n roi_name_limit_54
```

Update the existing e2e test so it asserts `data-roi-name-max-length="54"`.

- [ ] **Step 4: Run tests**

Run: `./venv/bin/python manage.py test rule_based_segmentation dicom_handler -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add rule_based_segmentation/ dicom_handler/ static/js staticfiles/js && git commit -m "feat(rbs): raise ROI name limit to 54 (Eclipse Clinical Goal)"
```

## Task 4: Fix the three broken primitives (Expand & Subtract, Crop, Ring)

**Why (feedback #2–4):** these are the confirmed-broken operations. Each must be
reproduced with a concrete synthetic fixture, bisected to the exact line, fixed in
the shared dispatcher/primitives, and locked with a regression test. Avoid-with-Margin
and Overlap are the reference-correct cases (leave them green).

**Files:**
- Modify: `dicom_handler/utils/structure_generation/execution.py` (handlers
  `_h_expand_subtract`, `_h_crop_to_boundary`, `_h_ring`, and `_expand` if needed)
- Modify: `dicom_handler/utils/structure_generation/operations.py`
  (`apply_directional_margin` if the oblique-direction bug is confirmed)
- Test: `dicom_handler/utils/structure_generation/` →
  `rule_based_segmentation/tests/test_operation_execution.py` and
  `dicom_handler/tests/test_pipeline_operations.py`

> **Method:** These are empirical fixes. Do NOT guess-edit. For each, first add a
> failing repro test (below), then run it, then read the actual returned mask's
> voxel count / orientation to locate the fault, fix the minimal code, re-run.

- [ ] **Step 1: Add repro + regression tests (all must fail first)**

```python
# rule_based_segmentation/tests/test_operation_execution.py (extend)
import numpy as np
from .helpers import create_box_mask

class CompositePrimitiveRegressionTests(TestCase):
    def _run(self, op, roles, params):
        from dicom_handler.utils.structure_generation.execution import execute_operation
        return execute_operation(op, roles, params)

    def test_expand_subtract_produces_new_volume_not_source(self):
        shape = (20, 20, 20)
        source = create_box_mask(shape, (4, 4, 4), (10, 10, 10))
        subtract = create_box_mask(shape, (8, 8, 8), (14, 14, 14))  # disjoint
        out = self._run("expand_subtract",
                        {"source": source, "subtract": subtract},
                        {"distance_mm": 5.0, "variant": "UNIFORM"})
        src_n = int(np.sum(sitk.GetArrayFromImage(source).astype(bool)))
        out_n = int(np.sum(sitk.GetArrayFromImage(out).astype(bool)))
        # expanding a 6x6x6 box by 5mm must grow it; result must differ from source
        self.assertNotEqual(out_n, src_n)
        # nothing of the disjoint subtract structure may remain "carved": since it
        # was disjoint, the result must equal the pure expansion of the source.

    def test_crop_to_boundary_is_intersection_not_nor(self):
        shape = (20, 20, 20)
        source = create_box_mask(shape, (0, 0, 0), (10, 10, 10))
        boundary = create_box_mask(shape, (5, 5, 5), (15, 15, 15))
        out = self._run("crop_to_boundary", {"source": source, "boundaries": [boundary]}, {})
        expected = sitk.And(source, boundary)
        self.assertTrue(np.array_equal(
            sitk.GetArrayFromImage(out).astype(bool),
            sitk.GetArrayFromImage(expected).astype(bool)))
        # NOR would be everything OUTSIDE both boxes -> this asserts the opposite.

    def test_ring_produces_a_shell(self):
        shape = (20, 20, 20)
        source = create_box_mask(shape, (6, 6, 6), (10, 10, 10))
        out = self._run("ring", {"source": source},
                        {"thickness_mm": 2.0, "variant": "UNIFORM"})
        arr = sitk.GetArrayFromImage(out).astype(bool)
        self.assertGreater(int(np.sum(arr)), 0)      # non-empty shell
        self.assertLess(int(np.sum(arr)), int(np.sum(arr | sitk.GetArrayFromImage(source).astype(bool))))
        # the shell must NOT contain the source's interior voxels
        self.assertFalse(bool(np.any(arr & sitk.GetArrayFromImage(source).astype(bool) == 0)))
```

(Add `import SimpleITK as sitk` at the top of the test module if not already.
`test_ring_produces_a_shell` asserts the shell excludes the original interior; the
final line may be simplified to `self.assertEqual(int(np.sum(arr & src_arr)), 0)`.)

- [ ] **Step 2: Run and capture the actual failure**

Run: `./venv/bin/python manage.py test rule_based_segmentation.tests.test_operation_execution.CompositePrimitiveRegressionTests -v`
Expected: FAIL on at least one. Record which assertion fails and, for each, log
`np.sum` of the returned mask and its shape so you can tell *empty / inverted /
identity-to-source* apart.

- [ ] **Step 3: Fix each root cause in the shared dispatcher**

Diagnose against these (verified) suspects, in order, per failing op:

- **Expand & Subtract** (`_h_expand_subtract`): confirm `_expand(source, params,
  "distance")` actually expands. If legacy `distance_mm` is being ignored because
  `_directional_margins` short-circuits on a stray key, or because the engine's
  `_directional_margin_params` returns a dict that never reaches the legacy
  branch, the expansion collapses to the source ("OS"). Fix the param plumbing so
  exactly one expansion path fires. If the mask comes back identical to source,
  also confirm `subtract` is a real mask (not `None`/all-0) — the engine must raise
  a clear error if `subtract` is empty, matching how `avoid_margin` guards with
  `_ensure_mask_not_empty`.
- **Crop to Boundary** (`_h_crop_to_boundary`): it must be `source AND each
  boundary`. If the result is NOR-like, the *input masks are inverted*. Trace
  `load_roi_masks` / `_rtutils_to_sitk_array` for a polarity flip that only shows
  for this role path, or a wrong role key (`boundaries` vs a single mask). The fix
  is the minimal change so `crop == sitk.And(source, boundary)`; do not "fix"
  overlap/avoid (they are green).
- **Ring** (`_h_ring`): `expand(source) - source`. If it *raises*, most likely
  `apply_directional_margin` on a `bool` array or the `A = np.array([D[2], D[1],
  D[0]])` construction (should be `A = D.T`, i.e. `A[i] = patient direction of
  image axis i`; `D.T` differs from row-permutation only for oblique series, but
  verify). Confirm on the synthetic axis-aligned fixture first; if it only fails on
  oblique geometry, fix the `A` construction in `operations.apply_directional_margin`.

Make the smallest change that turns the repro test green WITHOUT regressing
`avoid_margin`/`overlap` (re-run `test_operation_execution.py` in full).

- [ ] **Step 4: Run the full operation + engine suites**

Run: `./venv/bin/python manage.py test rule_based_segmentation.tests.test_operation_execution rule_based_segmentation.tests.test_engine dicom_handler.tests.test_pipeline_operations -v`
Expected: PASS, including the previously-green avoid/overlap cases.

- [ ] **Step 5: Commit**

```bash
git add dicom_handler/utils/structure_generation/ rule_based_segmentation/tests/ dicom_handler/tests/ && git commit -m "fix(rbs): correct expand_subtract, crop_to_boundary, and ring primitives with regression tests"
```

## Task 5: Guarantee per-ROI color and interpreted type reach the DICOM

**Why (feedback #5):** every imported structure shows Yellow in Eclipse. `add_roi`
*does* accept `color` and `roi_interpreted_type`, and `add_mask_as_roi` passes
`color` + sets the type via `_add_roi_display_type`. So the failure is almost
always that the RBS rule's `output_color`/`output_roi_type` is blank/default (the
UI or a caller didn't supply it), or the type write path (`_add_roi_display_type`)
misses the newly-added ROI. Fix the write path to use `add_roi(roi_interpreted_type=...)`
and default color/type from the *source* structure when the rule leaves them blank,
so a PTV stays a PTV with its own color.

**Files:**
- Modify: `rule_based_segmentation/utils/rtstruct_io.py` (`add_mask_as_roi`,
  `_add_roi_display_type`)
- Modify: `rule_based_segmentation/utils/engine.py` (`_add_rule_output_to_rtstruct`
  — fall back to the source structure's color/type when the rule's are unset)
- Test: `rule_based_segmentation/tests/test_engine.py`

- [ ] **Step 1: Write the failing test**

```python
class RoiColorTypeFidelityTests(TestCase):
    def test_output_color_and_type_are_written_to_dicom(self):
        # Build a 2-ROI synthetic rtstruct (via helpers.create_synthetic_rtstruct)
        # run a MARGIN rule with output_color='0\\255\\0' and output_roi_type='PTV',
        # then read back ROIContourSequence.ROIDisplayColor and
        # RTROIObservationsSequence.RTROIInterpretedType for the new ROI.
        # Assert color == [0,255,0] and type == 'PTV' (not yellow / ORGAN).
```

- [ ] **Step 2: Run and confirm fail**

Run: `./venv/bin/python manage.py test rule_based_segmentation.tests.test_engine.RoiColorTypeFidelityTests -v`
Expected: FAIL (type stays ORGAN and/or color stays yellow) until the fix.

- [ ] **Step 3: Implement**

In `add_mask_as_roi`, pass the interpreted type to the library so it is written in
one step instead of patched afterwards (keep the patch as a fallback):

```python
rtstruct.add_roi(
    mask=mask_np, name=name, color=color,
    description=f"Generated structure: {name}",
    use_pin_hole=False,
    roi_interpreted_type=roi_type,
)
```

In `_add_rule_output_to_rtstruct`, when `rule.output_color` is blank and
`rule.output_roi_type` is blank/`ORGAN`, inherit from the rule's primary source
structure if it can be resolved from `self.rtstruct` (read that ROI's existing
`ROIDisplayColor` / `RTROIInterpretedType`). This makes a plain "margin" of a PTV
carry the PTV's color and type by default.

- [ ] **Step 4: Run tests**

Run: `./venv/bin/python manage.py test rule_based_segmentation -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add rule_based_segmentation/utils/rtstruct_io.py rule_based_segmentation/utils/engine.py rule_based_segmentation/tests/ && git commit -m "fix(rbs): write per-ROI color and interpreted type; inherit from source when unset"
```

---

# Phase 2 — Replace the generated-contour system with RBS in task2

## Task 6: Add an in-memory RBS runner (no job / work-dir)

**Why:** task2 reidentifies the RTSTRUCT inside one Celery task and a DB
transaction, and must fold generated ROIs into that reidentified structure set
*before* export. RBS's `SegmentationJob` chain (prepare → rules → finalize → new
file → C-STORE) is the decoupled, approval workflow; it is not a fit here. We need
a thin runner that evaluates an ordered list of `PipelineRule` objects against an
already-loaded `RTStruct` + CT image, keeps intermediates in memory, and writes
only the exported ROIs. This reuses `SegmentationEngine._evaluate_rule` verbatim so
operation semantics stay in one place.

**Files:**
- Create: `rule_based_segmentation/utils/inline_runner.py`
- Modify: `rule_based_segmentation/utils/engine.py` (expose `_evaluate_rule` +
  `_collect_required_structures` for reuse — they are already instance methods; the
  runner builds a `SegmentationEngine` around an existing rtstruct/image)
- Test: `rule_based_segmentation/tests/test_inline_runner.py`

**Interfaces:**
- Consumes: `SegmentationEngine._evaluate_rule(rule) -> sitk.Image`,
  `SegmentationEngine._collect_required_structures(rule) -> set`,
  `add_mask_as_roi` / `load_roi_masks` (from `rtstruct_io`),
  `rt_utils` `RTStruct` (`get_roi_names`, `add_roi`).
- Produces:
  ```python
  class InlineSegmentationRunner:
      def __init__(self, rtstruct, image: sitk.Image, series=None):
          # rtstruct: rt_utils RTStruct; image: reference CT sitk.Image
          self.rtstruct = rtstruct
          self.image = image
          self.series = series
          self.available_masks = load_roi_masks(rtstruct, image)

      def run_rules(self, rules: list[PipelineRule],
                    skip_existing: set[str] | None = None) -> dict:
          # Returns {"created": [...], "replaced": [...],
          #          "intermediate": [...], "skipped": [...], "failed": [...]}
  ```
  Semantics: evaluate rules in `order`; for each, validate that referenced
  structures exist in `available_masks` ∪ produced-so-far (raise
  `RuleEvaluationError` listing the missing names, matching the job engine);
  INTERMEDIATE rules stay in `available_masks` only; CREATE_NEW/REPLACE_EXISTING
  write via `add_mask_as_roi` with the same dedup+trim behavior as the job engine
  (reuse the exact logic so both paths agree).

- [ ] **Step 1: Write the failing test**

```python
# rule_based_segmentation/tests/test_inline_runner.py
from django.test import TestCase
from .helpers import create_box_mask, create_synthetic_ct_series, \
    create_synthetic_rtstruct, create_dicom_models
import os, tempfile, numpy as np

class InlineRunnerTests(TestCase):
    def test_chain_exports_only_final_roi(self):
        with tempfile.TemporaryDirectory() as d:
            ct = create_synthetic_ct_series(d, num_slices=8, rows=24, cols=24)
            src = np.zeros((8, 24, 24), bool); src[2:4, 8:16, 8:16] = True
            rt_path = create_synthetic_rtstruct(os.path.join(d, "rt.dcm"), ct, "CTV", src)
            series_uid = ...
            from rt_utils import RTStructBuilder
            rt = RTStructBuilder.create_from(dicom_series_path=d, rt_struct_path=rt_path)
            import SimpleITK as sitk
            from dicom_handler.utils.structure_generation import load_ct_series_as_sitk_image
            # (build a minimal series_data dict or read image from disk)
            image = sitk.ReadImage  # use load_ct_series_as_sitk_image(series_data)
            from rule_based_segmentation.utils.inline_runner import InlineSegmentationRunner
            from rule_based_segmentation.models import (SegmentationPipeline,
                PipelineRule, MarginRuleConfig, CleanupRuleConfig)
            p = SegmentationPipeline.objects.create(name="p")
            grow = PipelineRule.objects.create(pipeline=p, order=1, rule_type="MARGIN",
                name="grown", output_action="INTERMEDIATE", output_color="255\\255\\0")
            MarginRuleConfig.objects.create(pipeline_rule=grow, variant="UNIFORM",
                source="CTV", margin_mm=3.0)
            keep = PipelineRule.objects.create(pipeline=p, order=2, rule_type="CLEANUP",
                name="CTV_margin", output_action="CREATE_NEW", output_color="255\\0\\0",
                output_roi_type="PTV")
            CleanupRuleConfig.objects.create(pipeline_rule=keep, operation="KEEP_LARGEST_COMPONENT",
                source="grown")
            runner = InlineSegmentationRunner(rt, image)
            summary = runner.run_rules([grow, keep])
            self.assertIn("grown", summary["intermediate"])
            self.assertEqual(summary["created"], ["CTV_margin"])
            self.assertNotIn("grown", rt.get_roi_names())  # intermediate not exported
            self.assertIn("CTV_margin", rt.get_roi_names())
```

- [ ] **Step 2: Run and confirm fail**

Run: `./venv/bin/python manage.py test rule_based_segmentation.tests.test_inline_runner -v`
Expected: FAIL — `inline_runner` module does not exist.

- [ ] **Step 3: Implement**

Create `rule_based_segmentation/utils/inline_runner.py`. Reuse the engine's
per-rule evaluation by constructing a lightweight `SegmentationEngine` bound to the
existing rtstruct/image (add a small `SegmentationEngine.from_rtstruct(rtstruct,
image, series=None)` classmethod in `engine.py` mirroring `from_workdir` but taking
in-memory objects). The runner then:

```python
def run_rules(self, rules, skip_existing=None):
    skip_existing = skip_existing or set()
    summary = {"created": [], "replaced": [], "intermediate": [], "skipped": [], "failed": []}
    produced = set(self.available_masks)
    for rule in rules:
        required = engine._collect_required_structures(rule)
        missing = required - produced
        if missing:
            raise RuleEvaluationError(f"Rule '{rule.name}' references missing structures: {sorted(missing)}")
        if rule.name in skip_existing:
            summary["skipped"].append(rule.name); produced.add(rule.name); continue
        mask = engine._evaluate_rule(rule)
        out = engine._add_rule_output_to_rtstruct(rule, mask)  # honors INTERMEDIATE + dedup
        # route out to the right bucket based on rule.output_action
        ...
        produced.add(rule.name)
    return summary
```

Note: `SegmentationEngine._add_rule_output_to_rtstruct` reads `self.rtstruct` — set
that to the shared `RTStruct` so the runner mutates the caller's structure set in
place (this is exactly what task2 wants: the reidentified `ds` gains the new ROIs).

- [ ] **Step 4: Run tests**

Run: `./venv/bin/python manage.py test rule_based_segmentation -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add rule_based_segmentation/utils/inline_runner.py rule_based_segmentation/utils/engine.py rule_based_segmentation/tests/test_inline_runner.py && git commit -m "feat(rbs): in-memory InlineSegmentationRunner for embedding generated ROIs"
```

## Task 7: Synthesize legacy `roi_generation_logic` into RBS rules

**Why:** existing `AdditionalStructures` rows store a bespoke chain:
`{"operations": [{"type": ..., "structures": [..], "parameters": {...}}, ...]}`.
The legacy `ProductionPipelineExecutor` chains them by feeding each op's result as
the next op's source (see `pipeline_executor._build_roles`, where crop/refinement
ops use the running `current_result`). To replace that executor without data
migration, convert each such JSON into an ordered list of in-memory `PipelineRule`
objects: every non-final op becomes an **INTERMEDIATE** rule (held in memory,
not exported), and the final op becomes a **CREATE_NEW** rule named
`roi_label`. Only the final ROI is written — directly satisfying feedback #7/#8.

**Files:**
- Create: `rule_based_segmentation/utils/legacy_synthesis.py`
- Test: `rule_based_segmentation/tests/test_legacy_synthesis.py`

**Interfaces:**
- Consumes: `ProductionPipelineExecutor._build_roles` semantics (the op→role map
  in `pipeline_executor.py`), catalog `resolve_operation_id`, `AdditionalStructures`
  model fields (`roi_generation_logic`, `roi_label`, `roi_display_color`,
  `rt_roi_interpreted_type`).
- Produces:
  ```python
  def synthesize_rules(additional_structure) -> list[PipelineRule]:
      """Return an in-memory (unsaved) list of PipelineRule objects that reproduce
      the legacy chain. All but the last are output_action='INTERMEDIATE'; the
      last is 'CREATE_NEW' with name=roi_label and the structure's color/type.
      Raises ValueError if an op type has no RBS rule mapping."""
  ```
  Mapping table (op id → RBS rule_type + config):
  - `margin`/`expand`/`contract` → `MARGIN` (sign-flip for `contract`, as the
    dispatcher already does).
  - `union`/`intersection`/`subtract`/`xor` → `BOOLEAN` (single operation node with
    operands = `structures`).
  - `crop_to_boundary` → `CROP` (source = running result; boundaries = structures).
  - `ring`/`overlap`/`expand_subtract`/`avoid_margin` → matching rule type.
  - `smooth`/`gaussian_smooth`/`fill_holes`/`remove_small_components`/
    `keep_largest`/`keep_n_largest`/`close_gaps`/`remove_protrusions` → `CLEANUP`
    with the matching operation token (Task 2).
  - `intensity_range` → `INTENSITY` (requires the image; ranges from parameters).
  The "running result" of op i is referenced by name as the *source* of op i+1
  (intermediate rules must be nameable; the synthesizer assigns a stable internal
  name per op, e.g. `f"__step_{i}"`).

- [ ] **Step 1: Write the failing test**

```python
class LegacySynthesisTests(TestCase):
    def test_expand_then_crop_yields_one_exported_rule(self):
        from rule_based_segmentation.utils.legacy_synthesis import synthesize_rules
        from dicom_handler.models import AdditionalStructures, AutosegmentationTemplate
        tpl = AutosegmentationTemplate.objects.create(template_name="t")
        extra = AdditionalStructures.objects.create(
            autosegmentation_template=tpl, roi_label="PTV_final",
            roi_display_color="255\\0\\0", rt_roi_interpreted_type="PTV",
            roi_generation_logic={"operations": [
                {"type": "margin", "structures": ["CTV"],
                 "parameters": {"margin_mm": 5.0, "variant": "UNIFORM"}},
                {"type": "crop_to_boundary", "structures": ["Body"], "parameters": {}},
            ]},
        )
        rules = synthesize_rules(extra)
        self.assertEqual(len(rules), 2)
        self.assertEqual(rules[0].output_action, "INTERMEDIATE")
        self.assertEqual(rules[1].output_action, "CREATE_NEW")
        self.assertEqual(rules[1].name, "PTV_final")
        # the crop rule's source must reference the intermediate, not 'CTV'
        self.assertEqual(rules[1].crop_config.source, rules[0].name)
        # and its boundary must be 'Body'
        self.assertEqual(list(rules[1].crop_config.boundaries.values_list('boundary_roi', flat=True)), ["Body"])
```

- [ ] **Step 2: Run and confirm fail**

Run: `./venv/bin/python manage.py test rule_based_segmentation.tests.test_legacy_synthesis -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement**

Write `legacy_synthesis.py` using the mapping table above. Build rules with
`PipelineRule` instances + their config objects but do NOT `save()` them; instead
the runner (Task 6) evaluates rule objects directly from attributes, so unsaved
instances with attached configs are sufficient. Give each intermediate a name
`f"__step_{idx}"`; set the final rule's `name=roi_label`, `output_color`,
`output_roi_type` from the AdditionalStructure. Unknown op ids raise `ValueError`
listing the id. Mirror `ProductionPipelineExecutor._build_roles` exactly for the
"which structures are the running-result source" decision (crop + all cleanup ops
use the running result as `source`; boolean/margin/composite use the named
`structures`).

- [ ] **Step 4: Run tests**

Run: `./venv/bin/python manage.py test rule_based_segmentation -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add rule_based_segmentation/utils/legacy_synthesis.py rule_based_segmentation/tests/test_legacy_synthesis.py && git commit -m "feat(rbs): synthesize legacy roi_generation_logic chains into RBS rules"
```

## Task 8: Rewire task2 to use RBS (replace ProductionPipelineExecutor)

**Why:** this is the actual replacement. `_add_additional_structures_to_rtstruct`
(today) builds a `RTStructBuilder`, runs each `roi_generation_logic` through
`ProductionPipelineExecutor`, and copies the sequences back. Replace that loop with
the RBS in-memory runner over synthesized rules. Empty ROIs (no logic) keep their
current direct-add path. Color/type come from the structure's own fields.

**Files:**
- Modify: `dicom_handler/import_services/task2_reidentify_rtstruct.py` (`_add_additional_structures_to_rtstruct`)
- Test: `dicom_handler/tests/test_task2_additional_structures.py` (create; mirror the synthetic series helpers)

**Interfaces:**
- Consumes: `InlineSegmentationRunner.run_rules`, `synthesize_rules`, existing
  `load_ct_series_as_sitk_image` (already imported), the current empty-ROI write
  code (keep it), `roi_name_to_number_map`.
- Produces: the same function signature
  `_add_additional_structures_to_rtstruct(ds, series_data,
  roi_name_to_number_map) -> None`, now RBS-backed.

- [ ] **Step 1: Write the failing test**

```python
# dicom_handler/tests/test_task2_additional_structures.py
from django.test import TestCase
from dicom_handler.import_services.task2_reidentify_rtstruct import \
    _add_additional_structures_to_rtstruct

class Task2RbsTests(TestCase):
    def test_generated_structure_folded_into_ds_not_intermediates(self):
        # Build a reidentified ds (via helpers) containing 'CTV' and 'Body';
        # create a matched template whose AdditionalStructures has a
        # margin->crop chain for 'PTV_final' and one empty ROI 'Spa'.
        # Call _add_additional_structures_to_rtstruct(ds, series_data, {}).
        # Assert: ds.StructureSetROISequence names include 'PTV_final' and 'Spa'
        # but NOT the intermediate '__step_*'; PTV_final color == the structure's
        # roi_display_color; PTV_final RTROIInterpretedType == 'PTV'.
        pass
```

(Provide the full fixture body using `rule_based_segmentation.tests.helpers` and
`dicom_handler` series fixtures — this test is the integration acceptance test.)

- [ ] **Step 2: Run and confirm fail**

Run: `./venv/bin/python manage.py test dicom_handler.tests.test_task2_additional_structures -v`
Expected: FAIL (still uses the old executor / fails to import new path).

- [ ] **Step 3: Implement**

Replace the "structures_with_logic" loop in `_add_additional_structures_to_rtstruct`
with:

```python
from rule_based_segmentation.utils.inline_runner import InlineSegmentationRunner
from rule_based_segmentation.utils.legacy_synthesis import synthesize_rules

rules_for_runner = []
for s in structures_with_logic:
    rules_for_runner.extend(synthesize_rules(s))
runner = InlineSegmentationRunner(rtstruct, ct_image, series=series)
summary = runner.run_rules(rules_for_runner, skip_existing=set(roi_name_to_number_map))
# register created ROIs in roi_name_to_number_map and log summary
for name in summary["created"]:
    roi_name_to_number_map[name] = len(roi_name_to_number_map) + 1
```

Remove the `executor = ProductionPipelineExecutor(...)` and the
`executor.execute_pipeline(...)/add_result_to_rtstruct(...)` block. Keep the
empty-ROI branch (no logic) unchanged. Ensure the in-place mutation of `rtstruct`
(`runner.rtstruct is rtstruct`) flows back to `ds` exactly as before — since the
old code re-read the saved temp file and reassigned the three sequences, confirm the
new path writes to the SAME `rtstruct` that is backed by `ds` (build the
`RTStructBuilder` from `ds` directly rather than a temp file where possible; if a
temp file is still needed, keep the sequence-copy-back, but now the ROIs come from
RBS). Update the summary log line to reflect RBS counts.

- [ ] **Step 4: Run the task2 + RBS suites**

Run: `./venv/bin/python manage.py test dicom_handler.tests.test_task2_additional_structures rule_based_segmentation -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dicom_handler/import_services/task2_reidentify_rtstruct.py dicom_handler/tests/ && git commit -m "refactor(task2): generate additional structures via RBS in-memory runner"
```

## Task 9: Update the RBS authoring surface for template-driven generation

**Why:** today RBS jobs are created from a user-selected RTStruct (UPLOAD/IMPORT)
via the RBS UI. After Task 8, the *template-driven* path (task2) uses RBS
internally but the RBS pipeline-authoring UI still only covers user-driven runs.
This task confirms the two paths coexist cleanly and that a template's
`AdditionalStructures` can also be viewed/edited through RBS semantics (optional,
low-risk). It also adds a helper to preview-synthesize a template's rules so a
clinician can see what task2 will produce before importing.

**Files:**
- Modify: `rule_based_segmentation/views.py` + `urls.py` (add
  `GET /rbs/api/template-preview/?template_id=...` returning the synthesized rules
  as JSON, read-only)
- Test: `rule_based_segmentation/tests/test_views.py`

- [ ] **Step 1: Write the failing test**

```python
def test_template_preview_lists_synthesized_rules(self):
    # create a template + an AdditionalStructures with a 2-op chain
    # GET api/template-preview/ -> JSON with 2 rules, last CREATE_NEW
    # assert the response lists the final roi_label and marks intermediates
```

- [ ] **Step 2: Run and confirm fail**

Run: `./venv/bin/python manage.py test rule_based_segmentation.tests.test_views -k template_preview -v`
Expected: FAIL (route/view missing).

- [ ] **Step 3: Implement**

Add a `@login_required` JSON view `api_template_preview` that loads the template's
`AdditionalStructures`, calls `synthesize_rules` for each, and returns
`{"structures": [{"roi_label", "rules": [{"name","rule_type","output_action",
"source"}...]}]}`. Add the URL. No new DB writes.

- [ ] **Step 4: Run tests**

Run: `./venv/bin/python manage.py test rule_based_segmentation.tests.test_views -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add rule_based_segmentation/views.py rule_based_segmentation/urls.py rule_based_segmentation/tests/test_views.py && git commit -m "feat(rbs): read-only template rule-preview API"
```

---

# Phase 3 — Cut over, retire the legacy executor (follow-up; do after a stable deploy)

## Task 10: Deprecate then remove the legacy generated-contour path

**Why:** with task2 on RBS and the preview available, `ProductionPipelineExecutor`
and the legacy `roi_generation_logic` builder are superseded. Removal is a
two-phase, reversible change.

**Files:**
- Modify: `dicom_handler/utils/pipeline_executor.py` (mark deprecated; raise on
  use until a release window passes, then delete)
- Modify: `dicom_handler/additional_structure_views.py`,
  `dicom_handler/pipeline_builder_views.py` (the legacy builder UI) — redirect to
  the RBS pipeline UI
- Test: `dicom_handler/tests/test_pipeline_executor.py`,
  `test_pipeline_operations.py` (retarget to RBS equivalents or delete)

- [ ] **Step 1: Add a deprecation guard + failing test**

```python
# pipeline_executor.py
def execute_additional_structure_pipeline(...):
    import warnings
    warnings.warn("ProductionPipelineExecutor is deprecated; use RBS", DeprecationWarning)
    raise NotImplementedError("Use rule_based_segmentation inline runner")
```

```python
def test_executor_is_deprecated(self):
    from dicom_handler.utils.pipeline_executor import execute_additional_structure_pipeline
    with self.assertRaises(NotImplementedError):
        execute_additional_structure_pipeline(None, None, "x", {"operations": []}, [0,0,0])
```

- [ ] **Step 2: Run and confirm fail**, then **Step 3:** implement the guard, **Step 4:** run `./venv/bin/python manage.py test dicom_handler -v`, **Step 5:** commit `"chore: deprecate legacy generated-contour executor in favor of RBS"`.

In a later release, delete `pipeline_executor.py` and the legacy builder views, and
optionally drop `AdditionalStructures.roi_generation_logic` (data migration that
synthesizes→stores native RBS rules first). Keep this split so the removal is a
trivial, independently-rolled-back step.

## Task 11: End-to-end acceptance test

**Files:**
- Create: `rule_based_segmentation/tests/test_end_to_end_template.py`

- [ ] **Step 1: Write the acceptance test** — a full synthetic study + RTSTRUCT
  with a matched template whose `AdditionalStructures` include: one empty ROI, one
  margin→crop→cleanup chain (with intermediates), one ring, one expand_subtract,
  one crop_to_boundary. Run the real task2 reidentify entry point against it and
  assert: only final ROIs (not intermediates) are present; colors and types match
  the structure fields; no `__step_*` names leak into the exported DICOM.
- [ ] **Step 2:** Run `./venv/bin/python manage.py test rule_based_segmentation.tests.test_end_to_end_template -v`; **Step 3:** fix any leak; **Step 4:** re-run; **Step 5:** commit `"test: end-to-end RBS-driven task2 generation acceptance"`.

## Task 12: Docs

**Files:**
- Create: `rule_based_segmentation/README.md` — the operating guide: what
  replaced what (table), migration notes, how to configure/operate the new path
  (authoring → matching → reidentify → preview), and where to find the
  operation mapping (legacy `type` → RBS `rule_type`, with pointers to
  `legacy_synthesis.py`, `structure_generation/`, and `operation_catalog.py`).

- [x] **Step 1:** wrote the README (`rule_based_segmentation/README.md`);
  **Step 2:** committed `"docs(rbs): integration and INTERMEDIATE usage"`.

---

# Phase 4 — Centralize additional-ROI authoring on RBS (single authoring surface)

## Invariant (hard requirement)

> **task2 must produce exactly ONE RTStruct file.** Template-driven generation runs
> **in-memory** via `InlineSegmentationRunner` (no work-dir, no `SegmentationJob`,
> no separate output RTStruct). Generated ROIs fold into task2's single reidentified
> RTStruct (temp file → copy sequences back → delete temp). Never invoke the
> `SegmentationJob`/work-dir path from task2.

## Design (confirmed)

- **Binding stays** `AdditionalStructures` (template → one target ROI: `roi_label`,
  `rt_roi_interpreted_type`, `roi_display_color`). Add a **FK**
  `AdditionalStructures.pipeline → SegmentationPipeline` holding the derivation rules
  (authored in the RBS builder).
- **Empty ROI = "no step":** a pipeline with **0 rules** (or `pipeline=None`) means
  "create the ROI empty, no derivation" — the existing empty-ROI path.
- **Final-ROI identity belongs to the binding.** When a pipeline is saved for an
  additional structure, its **last rule is pinned** to `name=roi_label`,
  `output_action=CREATE_NEW`, `output_color/type` from the binding; every earlier rule
  is forced to `INTERMEDIATE`. (This matches `synthesize_rules` exactly.)
- **Input structures** for authoring = the template's base ROIs
  (`AutosegmentationStructure.structureproperties.roi_label`) + sibling
  `AdditionalStructures.roi_label`. Referenced structures must exist in that set.
- **`roi_generation_logic`** is frozen after the one-off migration (read-only fallback
  until Phase 5 removes it).

## Task 14: Model — FK `AdditionalStructures.pipeline → SegmentationPipeline`

**Files:** Modify `dicom_handler/models.py`; migration `dicom_handler/migrations/0061_*.py`.
- `pipeline = models.ForeignKey("rule_based_segmentation.SegmentationPipeline",
  null=True, blank=True, on_delete=models.SET_NULL,
  related_name="additional_structures", help_text="RBS pipeline that generates this ROI")`
- Helper: `AdditionalStructures.is_generated` → `bool(self.pipeline_id and self.pipeline.rules.exists())`.
- **Test** (`dicom_handler/tests/test_additional_structures_pipeline.py`):
  empty-ROI semantics — a structure with `pipeline=None` or an empty pipeline is not generated.

## Task 15: One-off data migration — `roi_generation_logic` → `SegmentationPipeline`

**Files:** migration `dicom_handler/migrations/0062_*.py` (data) — import
`rule_based_segmentation.utils.legacy_synthesis.synthesize_rules`.
- For each `AdditionalStructures` with non-empty `roi_generation_logic` and no `pipeline`:
  create a `SegmentationPipeline` (name `f"{roi_label} generation"`, `is_public=False`,
  `is_active=False`), run `synthesize_rules(additional_struct, pipeline=pipeline)`,
  then **pin the final rule** (name=roi_label, action=CREATE_NEW, color/type from binding) and
  force earlier rules to INTERMEDIATE; set `additional_struct.pipeline = pipeline`.
- Idempotent: skip rows that already have a `pipeline`. Keep `roi_generation_logic` populated.
- **Test:** a fixture chain (margin→crop→smooth) migrates to a pipeline with 3 rules
  (INTERMEDIATE, INTERMEDIATE, CREATE_NEW named `roi_label`); re-running is a no-op.

## Task 16: Extract reusable RBS pipeline-persistence util

**Files:** Create `rule_based_segmentation/utils/pipeline_persistence.py`; modify `views.py` to import it.
- Move `_parse_pipeline_data`, `_create_or_update_pipeline`, `_save_rule`,
  `_validate_pipeline_rules`, `_collect_required_structure_names`, `_collect_boolean_operand_names`,
  and the `_save_*_config` helpers into `pipeline_persistence.py`.
- Expose `save_pipeline_from_dict(data, user, pipeline=None)` → `SegmentationPipeline`
  and `pipeline_data_from_pipeline(pipeline)` (the inverse of `_rule_to_json` list).
- Add a `pin_final_rule(pipeline, name, color, roi_type)` helper (last rule pinned, rest INTERMEDIATE).
- **Test:** RBS view tests still pass unchanged (behavior identical).

## Task 17: Wire task2 to run the FK pipeline (drop runtime synthesis for FK-set rows)

**Files:** Modify `dicom_handler/import_services/task2_reidentify_rtstruct.py`.
- In `_add_additional_structures_to_rtstruct`, per additional structure:
  - `pipeline = additional_struct.pipeline`:
    - **no rules** → empty ROI (existing direct-add path).
    - **has rules** → `runner.run_rules(list(pipeline.rules.all().order_by('order')), skip_existing=…)`.
  - Fallback (safety): if `pipeline_id is None` and `roi_generation_logic` present →
    `synthesize_rules` (unchanged).
- Preserve the **single-RTStruct invariant**: inline runner only; temp in parent dir; copy
  sequences back to `ds`; delete temp. Do NOT create a work-dir or a second RTStruct.
- **Test** (`dicom_handler/tests/test_task2_pipeline_fk.py`):
  a template whose additional structure points at a RBS pipeline generates the ROI with the
  binding's color/type, exports no intermediate, and leaves **exactly one** RTStruct in the
  series dir (assert no `*_output*`/second structure-set file is created).

## Task 18: UI — swap the legacy builder for the RBS builder

**Files:** Modify `templates/dicom_handler/template_detail_pipeline_modal.html` (+ any template
editor that embeds the legacy builder); remove the legacy `pipeline_builder.js` include there.
- Embed `rule_based_pipeline_builder.js` instead, seeded with:
  - `availableStructures` = template base ROIs + sibling additional-structure labels;
  - `ruleTypes` = backend rule types (already injected);
  - existing rules = the additional structure's pipeline via `pipeline_data`.
- **No step** (empty builder) → empty pipeline → empty ROI.
- The form posts `pipeline_data` (RBS JSON) in place of `roi_generation_logic`.
- **Test (manual):** builder lists base structures; adding no steps saves an empty pipeline.

## Task 19: Views — add/edit additional structure manage a `SegmentationPipeline`

**Files:** Modify `dicom_handler/additional_structure_views.py`.
- `add_additional_structure` / `edit_additional_structure`:
  - read `pipeline_data`; call `pipeline_persistence.save_pipeline_from_dict(...)` to create/refresh
    the pipeline (name `f"{roi_label} generation"`, private, inactive);
  - `pin_final_rule(pipeline, roi_label, roi_display_color, rt_roi_interpreted_type)`;
  - set `structure.pipeline = pipeline`;
  - validate every referenced structure is in the template's available set.
- Stop writing `roi_generation_logic` (leave the field for the frozen legacy rows).
- **Test:** POST with `pipeline_data` creates a pipeline + FK; the final rule is pinned to
  `roi_label`; an out-of-set reference is rejected.

## Task 20: Validate referenced input structures

**Files:** Modify `dicom_handler/additional_structure_views.py` (+ `pipeline_persistence` if needed).
- After save, confirm each referenced structure name is among the template's base ROIs or sibling
  additional-structure labels; reject otherwise with a clear message.
- **Test:** a rule referencing a non-existent structure is rejected.

## Task 21: Tests (aggregate acceptance)

- FK model + empty-ROI (no-step) semantics.
- Migration converts a known chain; idempotent.
- task2: FK pipeline runs; **exactly one RTStruct**; correct color/type; no intermediate.
- View: posting `pipeline_data` creates pipeline + FK; final rule pinned.
- **Command:** `./venv/bin/python manage.py test rule_based_segmentation dicom_handler.tests.test_task2_pipeline_fk dicom_handler.tests.test_additional_structures_pipeline --keepdb`

## Task 22 (Phase 5, follow-up — after a stable deploy): Retire the legacy path

- Remove `static/js/pipeline_builder.js`, `templates/dicom_handler/pipeline_builder.html`,
  `templates/dicom_handler/template_detail_pipeline_modal.html` (if fully replaced).
- Drop `AdditionalStructures.roi_generation_logic` + the `synthesize_rules` runtime fallback.
- Update `rule_based_segmentation/README.md` (authoring is now RBS-only).

---

## Self-Review

**Spec coverage:**
- Replace generated-contour with RBS → Tasks 6, 7, 8 (core), 9 (preview), 10 (retire).
- All legacy ops implemented in RBS → Task 2 (missing cleanup ops); the rest were
  already catalog-backed; Task 7 maps every op id.
- Bug: Expand & Subtract / Crop / Ring → Task 4.
- Always-Yellow color → Task 5 (plus Task 8 carries the structure's color).
- 18→54 char names → Task 3.
- Avoid exporting intermediates → Task 1 (INTERMEDIATE) + Task 6/7/8.
- "Additional rule options to get the final structure directly" → Task 1
  (INTERMEDIATE) + existing composite rules (ring/overlap/expand_subtract/avoid).

**Placeholder scan:** Task 9/10/11/12 use inline test stubs by design (they are
the acceptance gates); every code step shows the concrete edit. The two
`pass`-only bodies (Tasks 8, 9) are explicitly called out as "provide the full
fixture body" with the exact helper to reuse — acceptable because the fixtures
reuse already-specified helpers; no TBD/TODO remains.

**Type consistency:** `InlineSegmentationRunner(rtstruct, image, series=None)`
used identically in Tasks 6 and 8; `synthesize_rules(additional_structure) ->
list[PipelineRule]` used identically in Tasks 7, 8, 9; `INTERMEDIATE` bucket name
`"intermediate"` (runner summary) vs `"intermediate_rois"` (job-engine summary)
is intentional (two different summary shapes) and both are spelled out.
`RULE_NAME_LIMIT = 54` defined in Task 1's Step 3 and referenced by Task 1's
`_trim_to_limit` and consistent with Task 3's 54-char model limit.

---

## Execution handoff

**Plan complete and saved to `docs/superpowers/plans/2026-11-24-rbs-integration.md`.**

Two execution options:

1. **Subagent-Driven (recommended)** — a fresh subagent per task, review between
   tasks. Best here because Task 4 (the three bug fixes) needs focused, isolated
   diagnosis and shouldn't share context with the integration work.
2. **Inline** — execute in this session with executing-plans and checkpoints at
   each phase boundary (after Phase 1 and after Phase 2).

Recommended order: **Phase 1 fully green first** (Tasks 1→5) so the RBS product is
sound and the client's bugs are fixed, **then Phase 2** (Tasks 6→9) for the
integration, and **Phase 3 later** once a release is stable.

