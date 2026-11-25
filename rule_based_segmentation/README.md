# Rule-Based Segmentation (RBS)

RBS is the single engine that generates/edits ROI structures. It replaced the
legacy "generated-contour" pipeline
(`dicom_handler.utils.pipeline_executor.ProductionPipelineExecutor`), which is now
**deprecated** (its entry points raise `NotImplementedError`). Both systems share
one operation catalog and one dispatcher, so RBS is a faithful superset.

## What replaced what

| Legacy (generated-contour) | RBS replacement | Notes |
|---|---|---|
| `ProductionPipelineExecutor` | `SegmentationEngine` + `InlineSegmentationRunner` | The engine is unchanged; the inline runner wraps it without the job/work-dir lifecycle. |
| `execute_additional_structure_pipeline(...)` | `synthesize_rules(...)` + `runner.run_rules(...)` | The legacy JSON chain is converted to ordered `PipelineRule`s at run time. |
| `roi_generation_logic` (per `AdditionalStructures`) | Authoring surface unchanged; **synthesized** into RBS rules by `legacy_synthesis.synthesize_rules` | The JSON stays the template's source of truth; no schema migration is required. |
| "add result to RTStruct after every step" | **INTERMEDIATE** output action | All-but-last rules produce an in-memory mask (kept in `available_masks`) that is **never** written to the RTStruct; only the final rule (`CREATE_NEW`) is exported. |
| `execute_operation` dispatcher (`structure_generation/`) | **unchanged** | Still shared and fully supported; RBS calls it for every primitive. |
| Legacy builder views (`pipeline_builder_views`, `additional_structure_views`) | **kept** | They still author `roi_generation_logic`; task2 now consumes that JSON via synthesis instead of running it directly. |

### Key entry points

- **User-driven (job) path** — `rule_based_segmentation` UI: author a
  `SegmentationPipeline` of `PipelineRule`s, then create a `SegmentationJob`
  (`views.create_segmentation_job` → Celery). Each rule has an
  `output_action`: `CREATE_NEW`, `REPLACE_EXISTING`, or `INTERMEDIATE`.
- **Template-driven (inline) path** — task2 reidentification:
  `dicom_handler.import_services.task2_reidentify_rtstruct
  ._add_additional_structures_to_rtstruct` synthesizes each matched template's
  `AdditionalStructures.roi_generation_logic` into rules
  (`rule_based_segmentation.utils.legacy_synthesis.synthesize_rules`) and runs
  them with `rule_based_segmentation.utils.inline_runner.InlineSegmentationRunner`
  in one Celery task + DB transaction.
- **Read-only preview** — `GET rule_based_segmentation/api/template-preview/
  ?template_id=<uuid>` returns the rules task2 would synthesize (no DB is left
  behind).

## The INTERMEDIATE output action

`PipelineRule.OUTPUT_ACTION_CHOICES` gained `INTERMEDIATE`. The engine evaluates
it exactly like `CREATE_NEW` (computes the mask, stores it in `available_masks`
so later rules can reference it by name) **but does not write it to the
RTStruct**. This is the mechanism that stops intermediate structures from being
exported. The run summary reports `intermediate_rois`.

When a rule's `output_color` / `output_roi_type` are blank, the engine inherits
them from the source structure's existing DICOM values (this is what fixes the
"always yellow" symptom: a generated ROI now keeps its configured/declared color
and interpreted type instead of a default).

## Migration notes

- **Schema:** migrations `0012` (INTERMEDIATE), `0013` (cleanup ops:
  `KEEP_N_LARGEST_COMPONENT`, `CLOSE_GAPS`, `REMOVE_PROTRUSIONS` + fields
  `n`, `gap_size_mm`, `protrusion_size_mm`), `0014` (`PipelineRule.name`
  max_length 16 → 54) in `rule_based_segmentation`; `dicom_handler.0060`
  (`StructureProperties.roi_label` 16 → 54) and
  `AdditionalStructures.clean()` limit 16 → 54 (Eclipse Clinical Goal
  convention).
- **Apply to the production DB:** `./venv/bin/python manage.py migrate`.
  (The test DB is created with all migrations automatically.)
- **No data migration is needed.** `AdditionalStructures.roi_generation_logic`
  is unchanged; task2 synthesizes it at run time. Existing rows keep working.
- **Backward compatibility:** legacy `roi_generation_logic` JSON and legacy
  margin params still execute (read-side fallback in
  `legacy_synthesis._signed_margin_kwargs` / `_attach_config`).
- **Deprecated, not deleted:** `ProductionPipelineExecutor` and
  `execute_additional_structure_pipeline` warn + raise
  `NotImplementedError`. Full module deletion is deferred to a later release.

## How to configure / operate the new path

1. **Author the template.** In the template editor, define `AdditionalStructures`
   (each with a `roi_label`, an interpreted type, a display color, and an
   optional `roi_generation_logic` chain). An empty `roi_generation_logic` means
   "add this ROI directly (no derivation)".
2. **Match the series to a template.** task2 finds matched templates for the
   imported series (`DICOMSeries.matched_templates`).
3. **Reidentify.** task2 reidentifies the RTStruct, then for each matched
   template's structures: empty ROIs are added directly; each non-empty chain is
   synthesized into RBS rules and run inline. Intermediates stay in memory; only
   the final ROI (named after `roi_label`, carrying the structure's color and
   interpreted type) is exported.
4. **Preview (optional).** Before importing, `GET
   /rule_based_segmentation/api/template-preview/?template_id=<uuid>` lists the
   rules (name / rule_type / output_action / source) that would be generated.

## Where to find the operation mapping

Legacy `roi_generation_logic` op `type` → RBS `rule_type` / config:

| Legacy `type` | RBS rule | Source wiring |
|---|---|---|
| `margin`, `expand` | `MARGIN` | explicit `structures[0]` |
| `contract` | `MARGIN` (sign-flipped) | explicit `structures[0]` |
| `crop_to_boundary` | `CROP` | running result (previous rule) |
| `ring` | `RING` | explicit `structures[0]` |
| `overlap` | `OVERLAP` | explicit `structures[0]` + others |
| `expand_subtract` | `EXPAND_SUBTRACT` | `structures[0]`, `structures[1]` |
| `avoid_margin` | `AVOID_MARGIN` | `structures[0]`, `structures[1]` |
| `union`, `boolean_or` | `BOOLEAN` (OR) | explicit operands |
| `intersection`, `boolean_and` | `BOOLEAN` (AND) | explicit operands |
| `subtract` | `BOOLEAN` (SUBTRACT) | explicit operands |
| `xor` | `BOOLEAN` (XOR) | explicit operands |
| `smooth`, `gaussian_smooth`, `fill_holes`, `remove_small_components`, `keep_largest`, `keep_n_largest`, `close_gaps`, `remove_protrusions` | `CLEANUP` | running result (previous rule) |
| `intensity_range` | `INTENSITY` | seed/boundary from `structures` + ranges |

The authoritative source of this mapping is
`rule_based_segmentation/utils/legacy_synthesis.py`
(`synthesize_rules` / `_attach_config` / `_CLEANUP_OPS` / `_BOOLEAN_OPS`).
The primitive implementations live in `dicom_handler/utils/structure_generation/`
(`operations.py`, `advanced_operations.py`, dispatched by `execution.py`), and the
catalog (op ids, roles, params) is `dicom_handler/utils/structure_generation/
operation_catalog.py`.

A running-result op (`crop_to_boundary`, any cleanup) cannot be the first op in a
chain — synthesis raises `LegacySynthesisError` if it has no predecessor.

## Tests

- `rule_based_segmentation/tests/test_engine.py` — INTERMEDIATE semantics, cleanup ops.
- `rule_based_segmentation/tests/test_inline_runner.py` — inline run, no work dir.
- `rule_based_segmentation/tests/test_legacy_synthesis.py` — JSON → rules.
- `rule_based_segmentation/tests/test_roi_fidelity.py` — color/type inheritance.
- `rule_based_segmentation/tests/test_end_to_end_template.py` — full task2
  acceptance (empty + multi-op + ring + expand_subtract + contract).
- `dicom_handler/tests/test_task2_additional_structures.py` — real task2 function.
- `dicom_handler/tests/test_executor_deprecated.py` — legacy executor is deprecated.

Run: `./venv/bin/python manage.py test rule_based_segmentation dicom_handler --keepdb`
