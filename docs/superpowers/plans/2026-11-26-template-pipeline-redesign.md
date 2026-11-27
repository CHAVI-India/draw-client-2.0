# Template-Driven Additional Structures — Single-Pipeline Redesign (Phase 5)

> **STATUS: DRAFT — for review. No implementation until approved.**
> Date: 2026-11-26 · Branch: `rbs-integration` · DB: PostgreSQL
> Supersedes Phase 4's "one pipeline per `AdditionalStructures` row" model.

---

## 1. Context & motivation

Phase 4 gave each `AdditionalStructures` row its **own** `SegmentationPipeline` (FK
`pipeline`). Consequences the client rejected:

- **10 additional structures ⇒ 10 pipelines** (should be 1 per template).
- A confusing "Structure Properties" card (the final name) **plus** per-rule names —
  and the last rule's name was silently pinned/overwritten by that card.
- The authoring surface duplicated the RBS builder instead of *being* it.

**Target:** one pipeline per template. Every `output_action = CREATE_NEW` rule in it is
one additional structure. `INTERMEDIATE` rules are working ROIs. A new `EMPTY` rule type
creates a named, zero-voxel ROI. The builder's input-ROI dropdowns are seeded from the
**template** (not a sample RTStruct).

---

## 2. Confirmed decisions (2026-11-26)

| # | Decision |
|---|----------|
| Q1 | **Drop `AdditionalStructures` entirely.** The template's pipeline is the sole source of truth. task2 reads the pipeline directly; the template table lists the pipeline's `CREATE_NEW` rules. |
| Q2 | **One-to-one**: `AutosegmentationTemplate.additional_structures_pipeline → SegmentationPipeline`. **Hidden** from the general RBS "Pipelines" list (template-scoped only). |
| Q3 | **New rule type `EMPTY`** ("Create empty ROI") — name/color/type, `output_action = CREATE_NEW`; engine emits a zero-voxel mask. |
| Q4 | **Reuse `RuleBasedPipelineBuilder`** for the template pipeline: seed structures from the template's base ROIs (no RTStruct step), enable `EMPTY`. Opened from the template detail ("Add/Manage additional structures"). |
| Q5 | **One-off migration** consolidating the current per-row pipelines into one template pipeline. Must be **portable** across other deployed systems (see §9). |
| — | Base ROI names = `AutosegmentationStructure.name` + `StructureProperties.roi_label` (confirmed OK by client). |

---

## 3. Invariants (hard)

- task2 produces **exactly one RTStruct file** (all additional ROIs folded in, single write).
- A template's additional structures are defined **entirely** by `template.additional_structures_pipeline`.
- Standalone RBS pipelines are **unaffected**: still RTStruct-based authoring; template pipelines are excluded from the general list.
- `EMPTY` rules reference no input ROI (valid anywhere; no forward-reference issues).

---

## 4. Current → Target

| Area | Now (Phase 4) | Target |
|------|---------------|--------|
| Authoring | per-row pipeline (FK `AdditionalStructures.pipeline`) | one `template.additional_structures_pipeline`, N `CREATE_NEW` rules |
| Naming | outer "ROI Label" + `pin_final_rule` | each rule's `name` **is** its structure |
| Input ROIs | template base ROIs (already) | same |
| Empty ROI | zero-rule pipeline | `EMPTY` rule type |
| task2 | iterate `AdditionalStructures` rows (synthesis fallback) | run `template.additional_structures_pipeline` once |
| Template table | `AdditionalStructures` rows | pipeline's `CREATE_NEW` rules |
| RBS pipelines list | all pipelines | excludes template-bound ones |

**Files touched by Q1=B (drop table):** `models.py`, `views.py`, `xml_template_views.py`,
`additional_structure_views.py` (delete), `pipeline_builder_views.py` (rework),
`utils/additional_structure_pipeline.py` (delete), `import_services/task2_reidentify_rtstruct.py`,
`rule_based_segmentation/views.py`, `rule_based_segmentation/utils/legacy_synthesis.py` (retire),
templates `template_detail.html` (+ delete `template_detail_pipeline_modal.html`). No admin registration.

---

## 5. Tasks (small chunks)

### Task A1 — Data model: template one-to-one + `EMPTY` rule type

**Changes**
- New migration `dicom_handler` (auto-generated):
  - `AutosegmentationTemplate.additional_structures_pipeline = OneToOneField(
      "rule_based_segmentation.SegmentationPipeline", null=True, blank=True,
      on_delete=SET_NULL, related_name="+")`.
  - `related_name="+"` so the reverse accessor is *implicit* (we only filter by
    `autosegmentationtemplate__isnull` to hide it; no custom name to leak elsewhere).
- `rule_based_segmentation/models.py`: add `("EMPTY", "Create empty ROI")` to
  `PipelineRule.RULE_TYPE_CHOICES`. (Choice-only change; `makemigrations` will confirm —
  Django does not change the column for a `CharField` choices edit.)
- `EMPTY` has **no config** (no `EmptyRuleConfig`): it needs no parameters. The builder
  skips config saving for it; the engine produces an empty mask.

**Test**
- `SegmentationPipeline` can be linked to exactly one template; the reverse lookup
  `SegmentationPipeline.objects.filter(autosegmentationtemplate__isnull=True)` excludes it.
- `PipelineRule(rule_type="EMPTY")` validates.

**Verification** — `./venv/bin/python manage.py makemigrations` (expect only the OneToOne
field) → `migrate`; model import smoke test.

---

### Task A2 — `EMPTY` rule execution (engine + catalog)

**Changes**
- `rule_based_segmentation/utils/engine.py`:
  - `_evaluate_rule` (≈ line 236): add `if rule.rule_type == "EMPTY": return self._empty_mask()`.
  - `_empty_mask()` builds a zero image matching the input RTStruct's reference geometry
    (shape, spacing, origin, direction, `sitk` pixel type) — reuse the image/RTStruct the
    engine already holds.
  - Ensure the rule-dispatch block (≈ 180–236) and the config-load block (≈ 528–548) have
    no special-casing that would trip on `EMPTY` (they shouldn't; `EMPTY` has no config).
- `dicom_handler/utils/structure_generation/operation_catalog.py`: add an `EMPTY` entry so
  the catalog and any server-side "known rule types" checks include it (label
  "Create empty ROI", no required roles, no params).
- `rule_based_segmentation/utils/pipeline_persistence.py`: `_save_rule` skips config
  persistence for `EMPTY` (no config OneToOne). `referenced_structure_names` must treat an
  `EMPTY` rule as referencing **nothing**.

**Test**
- An `EMPTY` rule produces a zero-voxel mask of the correct geometry and, with
  `output_action = CREATE_NEW`, is added to the RTStruct with the rule's name/color/type.
- An `EMPTY` rule as the first rule (no inputs) is valid and evaluates without error.

**Verification** — `manage.py test rule_based_segmentation.tests.test_engine
rule_based_segmentation.tests.test_operation_execution`.

---

### Task A3 — Authoring: template pipeline editor (reuse the RBS builder)

**Changes**
- Rework `dicom_handler/pipeline_builder_views.py` into a **template pipeline editor**:
  - `template_pipeline_editor(template_id)` (GET): render a single-page form built on
    `RuleBasedPipelineBuilder` with:
    - `availableStructures` = template base ROIs
      (`AutosegmentationStructure.name` + `StructureProperties.roi_label`, deduped).
    - `ruleTypes` = `PipelineRule.RULE_TYPE_CHOICES` (now incl. `EMPTY`).
    - `existingRules` = the template pipeline's rules (via `pipeline_data_from_pipeline`),
      or empty if none.
  - `template_pipeline_save` (POST): persist via the shared `template_pipeline_for(template)`
    helper (Task §8.3) then `pipeline_persistence.save_pipeline_from_dict` (create-or-update)
    with the **fixed convention** (`is_public=False`, `is_active=True`,
    `name = "<template> — additional structures"`); `transaction.atomic()`; server-side
    validation that every referenced input ROI is either a template base ROI or produced by
    an earlier rule. A POST with zero rules = a pipeline with no additional structures (fine).
- **Hide template pipelines from the general list** in `rule_based_segmentation/views.py`
  (the `pipelines/` listing): `SegmentationPipeline.objects.filter(
  autosegmentationtemplate__isnull=True)`.
- `templates/dicom_handler/pipeline_builder.html` → becomes the template editor template
  (drop the "Structure Properties" card + the outer `roi_label` field; the builder is the
  whole page). The builder posts `pipeline_data`.
- `templates/dicom_handler/template_detail.html`: the "Add Structure" button links to
  `template_pipeline_editor(template.id)` (single entry point; no per-row add/edit).
- Delete the dead inline modal + `template_detail_pipeline_modal.html` (Q1=B: no per-row
  authoring left).

**Test**
- GET editor 200 and includes `rule_based_pipeline_builder.js`; base ROIs present;
  `EMPTY` in the rule-type choices.
- POST a valid pipeline_data → `template.additional_structures_pipeline` set, rules saved.
- POST referencing a non-template ROI → rejected.
- General `pipelines/` list excludes the template pipeline.

**Verification** — `manage.py test dicom_handler.tests.test_pipeline_builder_views
rule_based_segmentation.tests.test_views`.

---

### Task A4 — task2: run the template pipeline (single RTStruct)

**Changes**
- `dicom_handler/import_services/task2_reidentify_rtstruct.py`
  `_add_additional_structures_to_rtstruct(...)`:
  - Read `template.additional_structures_pipeline`. If `None` or has no rules → return
    (nothing to add).
  - Run the **whole** pipeline inline via `InlineSegmentationRunner` (existing single-RTStruct
    runner). `CREATE_NEW` rules (incl. `EMPTY`) add ROIs to that one RTStruct; `INTERMEDIATE`
    rules stay in memory.
  - Remove the per-row `synthesize_rules` fallback (no more per-row pipelines; empty ROIs
    are now `EMPTY` rules).
- Keep the **single-RTStruct invariant** (one file, all ROIs folded in, one transaction).

**Test**
- A template pipeline with 3 `CREATE_NEW` rules (one `EMPTY`) → exactly one RTStruct with
  the 3 ROIs (the empty one present, zero voxels), intermediates not exported.
- No pipeline / empty pipeline → RTStruct unchanged, no error.

**Verification** — `manage.py test dicom_handler.tests.test_task2_pipeline_fk
dicom_handler.tests.test_task2_additional_structures` (renamed/updated to the new flow).

---

### Task A5 — Migration: consolidate per-row pipelines → one template pipeline

> This is the portable one-off. See §9 for the portability guarantees.

**Data migration** (`dicom_handler`): for **each** template that has ≥1 `AdditionalStructures`
row (stable order by row.id):
1. Get-or-create the pipeline via `template_pipeline_for(template)` (§8.3 fixed convention,
   `is_active=True`).
2. For each row:
   - **Row has a `pipeline`:** copy its rules into the template pipeline in order.
     - `INTERMEDIATE` rules → copied as `INTERMEDIATE`.
     - the final `CREATE_NEW` rule → copied with `name = row.roi_label`,
       `output_color/type` from the row binding, `output_action = CREATE_NEW`.
   - **Row has no `pipeline`** (empty ROI): create one `EMPTY` rule
     (`name = row.roi_label`, color/type from the row, `CREATE_NEW`).
   - **Name-collision handling:** intermediate names that repeat across rows are renamed
     (append a disambiguating suffix) and every reference to the old name in the merged
     configs is updated (find/replace across operand names, `source`, `boundaries`,
     `others`, etc.). The `CREATE_NEW` names are already unique (enforced per template).
3. Set `template.additional_structures_pipeline` = the merged pipeline.
4. After all templates: delete the old per-row pipelines **only if** they are not linked to
   any template (`filter(autosegmentationtemplate__isnull=True)`) and were used as an
   `AdditionalStructures.pipeline`. Never delete a standalone pipeline.

**Schema migrations** (after the data migration):
- Remove `AdditionalStructures.pipeline`.
- Remove `AdditionalStructures.roi_generation_logic`.
- Remove/drop the `AdditionalStructures` model + table.

**Test**
- Representative fixtures: (a) template with 2 rows having distinct pipelines; (b) a row
  with a NULL pipeline (→ `EMPTY` rule); (c) two rows whose intermediates collide (→
  renamed + refs updated); (d) a template with zero rows (no-op).
- Idempotency: running the data migration twice does not duplicate rules or pipelines.
- Assert the old per-row pipelines are gone and no standalone pipeline is touched.

**Verification** — run on a scratch DB from a real export of this system's 7 rows; inspect
the merged pipeline; confirm the count of `CREATE_NEW` rules == number of prior
additional structures.

---

### Task A6 — Remove `AdditionalStructures` + dependents

**Delete**
- `dicom_handler/additional_structure_views.py`.
- `dicom_handler/utils/additional_structure_pipeline.py` (replaced by Task A3 logic).
- `rule_based_segmentation/utils/legacy_synthesis.py` (no per-row synthesis left).
- `templates/dicom_handler/template_detail_pipeline_modal.html` (orphaned).
- The add/edit/delete + full-page-builder URLs (replaced by `template_pipeline_editor` /
  `template_pipeline_save`).

**Rework**
- `dicom_handler/views.py` (template detail, ≈1061): the "Additional Structures" table is
  now `template.additional_structures_pipeline.rules.filter(output_action="CREATE_NEW")`
  (name/type/color per rule). No `AdditionalStructures` query.
- `dicom_handler/xml_template_views.py` (Step 4 "save as AdditionalStructures"): rework to
  append **`EMPTY` rules** (one per unmapped XML structure, §8.2) to
  `template.additional_structures_pipeline` via `template_pipeline_for(template)`, instead of
  creating `AdditionalStructures` rows. (XML-imported additional structures are empty
  placeholders; mapped XML ROIs stay base ROIs.)
- `rule_based_segmentation/views.py` (template-preview, ≈861): drop the
  `AdditionalStructures` reference; available inputs come from the template base ROIs.
- `dicom_handler/models.py`: the model is gone (Task A5 drops it).

**Test**
- Template detail renders the table from the pipeline (no 500, correct rows).
- XML import adds rules to the template pipeline (not rows).
- No remaining `AdditionalStructures` import anywhere (`grep` clean).

**Verification** — `manage.py test dicom_handler` + `rule_based_segmentation`.

---

### Task A7 — Acceptance (aggregate)

- Full RBS suite + dicom_handler suite green (fresh DB).
- Manual: create a template with base ROIs → open the editor → add a `MARGIN` rule (base
  ROI), an `EMPTY` rule, and an intermediate → save → task2 produces one RTStruct with the
  expected ROIs.
- The general RBS "Pipelines" list does not show the template pipeline.

---

## 6. Order of work

A1 (model) → A2 (EMPTY engine) → A3 (editor) → A4 (task2) → **A5 (data migration first,
then schema drop)** → A6 (remove dependents) → A7 (acceptance).

A5's data migration must run **before** A6 removes the model (it reads the rows). The
schema-drop migrations at the end of A5 remove the field, then drop the table.

---

## 7. Explicit non-goals

- No change to standalone RBS pipeline authoring (still RTStruct-based).
- No change to the RBS *engine's* multi-`CREATE_NEW`-rule support (it already exists — task2
  just points it at the template pipeline).
- No rename/merge of *base* (autosegmented) ROIs — only additional structures move.

---

## 8. Decisions (confirmed 2026-11-26)

1. **Intermediate name-collision** (A5): **auto-suffix + rewrite references** (find/replace
   the old name across all merged configs so dependent rules keep resolving).
2. **XML import (A6):** unmapped XML structures all become **`EMPTY` rules** (they were
   historically empty placeholders) — not derived `CREATE_NEW` rules.
3. **Fixed convention** (A3/A5): a single helper `template_pipeline_for(template)` is the one
   place that returns-or-creates the pipeline, always with:
   - `name = f"{template.template_name} — additional structures"`
   - `is_public = False`, `is_active = True`
   The pipeline is identified **structurally** by the OneToOne link; the general list is
   hidden via `filter(autosegmentationtemplate__isnull=True)` (name/flags are cosmetic).
4. **Entry point (A3):** single **"Manage additional structures"** button → the pipeline
   editor (replaces "Add Structure"). No per-row add/edit.

---

## 9. Migration portability (your Q5 question)

**Will the migration work on other installed systems?** Yes, with these guarantees:

- **State-agnostic:** it keys off the DB, not this system's data. It handles all three real
  states a deployed system can be in:
  - *Post-Phase-4* (rows have `pipeline`): consolidate directly.
  - *Upgraded from pre-Phase-4* (rows have `roi_generation_logic`, `pipeline` NULL):
    Phase-4 migration 0062 already ran earlier in the migration chain (Django runs pending
    migrations in order) and set the `pipeline`; if any row is still NULL, the migration
    synthesizes from `roi_generation_logic` on the fly, or falls back to an `EMPTY` rule.
  - *Fresh / no additional structures:* zero rows → the loop is a no-op; schema migrations
    still add the field + drop the table cleanly.
- **Idempotent:** a second run detects the template pipeline already set and skips
  re-copying (guarded by "if `template.additional_structures_pipeline` already has rules
  matching these rows, skip").
- **Defensive / non-destructive:** runs in a transaction; skips (with a log line) any row
  it cannot reconcile rather than crashing the whole migration; **never deletes a pipeline
  that is linked to a template or is a standalone (public/active) pipeline**.
- **Deploy-ordering:** the code that reads `template.additional_structures_pipeline`
  (task2, views) ships **with** the migration in the same release, so a system never runs
  old code against a dropped table.

---

## 10. Risks & rollback

- **Drop-table is the big one.** Mitigation: A5's data migration consolidates everything
  *before* the schema drop; keep a pre-migration `pg_dump` (or `AdditionalStructures` +
  their `pipeline` JSON) in the release notes as a manual rollback path. The schema drop is
  the last step, so a failed data migration can be reverted without touching the table.
- **Intermediate name collisions** can silently change semantics if mis-rewritten — hence
  the explicit find/replace + a test that asserts references resolve (Task A5 test (c)).
- **Editor reuse:** `RuleBasedPipelineBuilder` was just refactored (inline editor,
  delegation) — those fixes already apply here since it's the same shared JS.

---

## 11. Implementation status (A1–A7, 2026-11-26)

All seven tasks implemented, tested, and committed on `rbs-integration`:

| Task | Commit | Note |
|------|--------|------|
| A1 data model | `7addac3` | OneToOne `AutosegmentationTemplate.additional_structures_pipeline` (0063) + `EMPTY` choice (RBS 0015). |
| A2 EMPTY execution | `8f240db` | `SegmentationEngine._empty_mask()`; zero-voxel ROI, no input, no config. |
| A3 template editor | `b5ce733` | `template_pipeline.py` helper, `template_pipeline_view/save` + URL, `template_pipeline_editor.html`, RBS list hides template pipelines, EMPTY in builder JS. |
| A4 task2 | `26f4fbc` | task2 runs each matched template's `additional_structures_pipeline` (single-RTStruct, per-pipeline isolation). |
| A5 consolidation | `0544637` | migration 0064 merges per-row pipelines → one per template (EMPTY rule for no-logic rows; name-collision auto-suffix + reference rewrite). Applied to production: 7 templates, 0 collisions. |
| A6 drop dependents | `27c1747` | All **live** dependents removed (task2 fallback, RBS preview, XML import, template table/modal, per-row views/util/templates/URLs). |
| A7 acceptance | (this) | Full suites green; production verified. |

### Decision: the `AdditionalStructures` model + `legacy_synthesis.py` are KEPT (deprecated)

A6 removed every **live** consumer of `AdditionalStructures` (task2, the RBS preview,
the XML import, the template table + modal, the per-row views/util/URLs/templates). The
model itself and `legacy_synthesis.py` are **kept, unused** on purpose, because the
historical migration chain (0061/0062/0064) imports the **live** `AdditionalStructures`
class at runtime; `DeleteModel`-ing it would break a **fresh-database** `manage.py migrate`
(from 0001) at migration 0062/0064. This preserves the "portable across other deployed
systems" guarantee.

**Future cleanup (optional, out of scope for this phase):** guard the 0062/0064 imports
(`try/except ImportError` → no-op, since a fresh DB has no legacy rows to consolidate),
add a `0065` migration (`RemoveField(AdditionalStructures.pipeline)` + `DeleteModel`),
remove `legacy_synthesis.py` + the model, and drop `test_consolidate_migration` /
`test_migration_pipeline` / `test_legacy_synthesis`. The 7 production `AdditionalStructures`
rows + their per-row pipelines remain as an inert, unused fallback until then.

### Verification
- `dicom_handler` full suite: 42 tests OK (3 skipped).
- `rule_based_segmentation`: all 19 test modules green (views/models/engine/inline-runner/
  operation-execution/empty-rule/end-to-end(+template)/legacy-synthesis, plus the fast
  engine/job/task modules). The slow `test_pipeline_e2e_physics` run separately.
- Production DB: migrations 0063/0064 applied; 7 templates each carry one
  `is_public=False, is_active=True` pipeline (3 rules: 2 `INTERMEDIATE` + final
  `CREATE_NEW`), colors/types preserved through the JSON round-trip.
