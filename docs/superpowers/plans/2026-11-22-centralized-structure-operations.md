# Centralized Structure Operations — Implementation Plan

**Goal:** Make the same set of structure operations available in BOTH the
Pipeline Builder (`dicom_handler`) and Rule-Based Segmentation
(`rule_based_segmentation`), by centralizing the operations in a single
catalog + execution layer. Preserve the feature-rich operations (e.g.
anisotropic margin, ring, overlap, expand-subtract, avoid-margin, gaussian
smooth, xor, keep-N, close-gaps, remove-protrusions, intensity).

## Background / Current State

Both systems already share a low-level primitive layer:
`dicom_handler/utils/structure_generation/`
- `operations.py`: `apply_uniform_margin`, `apply_anisotropic_margin`,
  `boolean_union/intersection/subtraction/xor`, `crop_to_boundary`,
  `expand_and_crop`, `subtract_with_margin`
- `advanced_operations.py`: `smooth_structure`, `gaussian_smooth`,
  `fill_holes`, `remove_small_components`, `keep_largest_component`,
  `keep_n_largest_components`, `close_gaps`, `remove_protrusions`,
  `convex_hull`, `distance_map`

Two executors compose those primitives:
- `dicom_handler/utils/pipeline_executor.py` →
  `ProductionPipelineExecutor` — runs the pipeline-builder JSON
  (`AdditionalStructures.roi_generation_logic`) during auto-segmentation
  import. Exposes only 10 basic ops.
- `rule_based_segmentation/utils/engine.py` → `SegmentationEngine` — runs the
  9 RBS rule types (richer: anisotropic margin, ring, overlap,
  expand-subtract, avoid-margin, nested boolean, intensity).

Two frontends define the operation list (independently, hardcoded in JS):
- `static/js/pipeline_builder.js` → `this.operationTypes` (10 ops)
- `static/js/rule_based_pipeline_builder.js` → rule types (from
  `PipelineRule.RULE_TYPE_CHOICES`) + per-type config editors

### Bugs / gaps found
1. **Production union/intersection are broken:**
   `ProductionPipelineExecutor._execute_operation` calls
   `boolean_union(input_masks)` / `boolean_intersection(input_masks)` passing
   a **list**, but both primitives take exactly two masks → `TypeError`.
   (Only `subtract` folds correctly.)
2. **Feature-rich ops are missing from the pipeline builder:** anisotropic
   margin, ring, overlap, expand-subtract, avoid-margin, xor,
   gaussian-smooth, keep-N-largest, close-gaps, remove-protrusions.
3. **Two sources of truth** for "which operations exist" (two JS files +
   two executors), so they drift.

## Design

### Canonical operation set (union of both systems)
| id | name | roles | key params |
|---|---|---|---|
| margin_uniform | Margin (uniform) | source | margin_mm (±), kernel_type |
| margin_anisotropic | Margin (anisotropic) | source | margin_x_mm, margin_y_mm, margin_z_mm |
| union | Union | primary, others[] | — |
| intersection | Intersection | primary, others[] | — |
| subtract | Subtract | primary, others[] | margin_mm (optional) |
| xor | Symmetric Difference | primary, others[] | — |
| crop_to_boundary | Crop to Boundary | source, boundaries[] | — |
| ring | Ring / Shell | source | thickness (uniform or xyz), kernel |
| overlap | Overlap | source, others[] | — |
| expand_subtract | Expand & Subtract | source, subtract | distance (uniform or xyz), kernel |
| avoid_margin | Avoid with Margin | source, avoid | margin (uniform or xyz), kernel |
| smooth | Smooth | source | smoothing_mm, iterations |
| gaussian_smooth | Gaussian Smooth | source | sigma_mm, threshold |
| fill_holes | Fill Holes | source | fully_connected |
| remove_small_components | Remove Small Components | source | min_size_mm3 |
| keep_largest | Keep Largest | source | — |
| keep_n_largest | Keep N Largest | source | n |
| close_gaps | Close Gaps | source | gap_size_mm |
| remove_protrusions | Remove Protrusions | source | protrusion_size_mm |
| intensity_range | Intensity Range | seed (optional), boundary (optional), ranges[] | min/max per range |

"roles" = the structured input contract (which structures the op needs and
by what name). Frontends render a structure input per role; the backend maps
roles→masks.

### Layers (new / changed)
1. **`operation_catalog.py`** (new, in structure_generation) — `OperationSpec`
   dataclass + `OPERATIONS` dict + `to_frontend_catalog()` (JSON list).
   Single source of truth for what exists, its roles, and its parameters.
2. **`execution.py`** (new) — `execute_operation(op_id, roles, params,
   image=None) -> sitk.Image`. Maps each op to the shared primitives. Folds
   variadic boolean ops correctly. Intensity op receives the CT `image`.
3. **`engine.py`** (RBS) — each `_evaluate_*_rule` builds `(roles, params)`
   from its config and calls `execute_operation`. Config parsing, output
   naming, color, dedup, and validation unchanged.
4. **`pipeline_executor.py`** — `_execute_operation` maps
   `{type, structures, parameters}` → `(roles, params)` and calls
   `execute_operation`. Fixes the union/intersection bug; gains all feature
   -rich ops. Public signatures unchanged.
5. **API endpoint** (new) — `GET /api/structure-operations/` returns
   `to_frontend_catalog()`.
6. **Frontends** — both `pipeline_builder.js` and
   `rule_based_pipeline_builder.js` fetch the catalog and render from it
   (replacing the hardcoded lists), preserving each builder's orchestration
   semantics (pipeline builder = single output ROI chain; RBS = multiple
   named ROIs).

### Mapping old pipeline-builder op ids → canonical ids (back-compat)
Saved `roi_generation_logic` JSON keeps working:
- `expand` → `margin_uniform` (positive), `contract` → `margin_uniform`
  (negative), `union`/`intersection`/`subtract` → same (now fixed),
  `crop_to_boundary`, `smooth`, `fill_holes`, `remove_small_components`,
  `keep_largest` → same ids. The executor accepts the legacy ids as aliases.

## Phases
- **Phase 1 (foundation):** catalog + execution dispatcher + tests.
- **Phase 2 (RBS):** delegate engine evaluators to the dispatcher (tests stay
  green).
- **Phase 3 (production):** route `ProductionPipelineExecutor` through the
  dispatcher (fixes booleans, adds rich ops) + regression tests.
- **Phase 4 (frontend):** catalog endpoint + drive both JS builders from it +
  CSS + render tests.

## Risks
- **Production auto-segmentation path** (`ProductionPipelineExecutor`) is the
  highest risk. Mitigation: keep signatures, route through the tested
  dispatcher, add regression tests for every op incl. the fixed booleans.
- Frontend rework is the largest surface; mitigated by rendering from the
  catalog (data-driven) and keeping each builder's orchestration model.

## Out of scope
- Changing RBS job/chain mechanics, approval, or output structure-set logic.
- Adding brand-new segmentation algorithms beyond the existing primitives.
