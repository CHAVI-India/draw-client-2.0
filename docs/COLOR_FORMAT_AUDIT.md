# ROI Color Storage Format — Audit Report

Date: 2026-11-27 · Branch: `rbs-integration`

## Question

> DICOM stores an ROI color as `R\G\B` (e.g. `255\0\0`). Why does the DB store hex
> (`#FF0000`)? Which places write hex, why, and what are the consequences of
> storing in RGB instead?

## TL;DR

The `PipelineRule.output_color` column is **mixed-format**: some rows are hex
(`#FF0000`), some are DICOM `R\G\B` (`255\0\0`), some are `NULL`. That drift causes a
**real, user-visible data-loss bug**: a pipeline built in the UI (saved as hex) has all
its colors read back as **yellow** the next time it is opened, and re-saving persists
the yellow — the colors are lost.

- **Runtime is correct** — the engine's `_parse_color` accepts both hex and `R\G\B`.
- **The UI round-trip is broken** — the read-back helper `_rgb_dicom_to_hex` only
  understands `R\G\B`; given a hex string it falls through to the `#FFFF00` (yellow) default.
- **Recommended canonical format: store `R\G\B` in the DB** (DICOM-native, matches the
  field's documented intent and the rest of the system), converting hex↔RGB at the UI
  boundary, plus a one-off migration for existing hex rows.

---

## 1. The two formats in play

| Format | Example | Where it lives |
|--------|---------|----------------|
| **Hex** | `#FF0000` | What the web UI color picker produces |
| **DICOM RGB** | `255\0\0` | What DICOM `ROIDisplayColor` (0038,0601) holds; the field's documented intent |
| (list) | `[255, 0, 0]` | In-memory, between `_parse_color` and `rt_utils` |

On disk, the DICOM value is always the backslash-joined `R\G\B` string (verified:
writing `ROIDisplayColor=[255,0,0]` produces a byte-identical file to writing
`"255\0\0"`; pydicom reads both back as a 3-part value). So the **on-disk format is
always correct** regardless of what the DB column holds.

---

## 2. Every place a color is written to / read from the DB

### Writers (write to `PipelineRule.output_color` or `StructureProperties.roi_display_color`)

| # | Location | Writes | Format |
|---|----------|--------|--------|
| W1 | `rule_based_segmentation/utils/pipeline_persistence.py:234` (`_save_rule`) | `rule_data.get("output_color") or "255\\255\\0"` | **HEX** (verbatim from UI) or RGB default |
| W2 | Builder JS `static/js/rule_based_pipeline_builder.js:128,635,1466` | native `<input type="color">` value | **HEX** (always; JS defaults `#FFFF00`) |
| W3 | `dicom_handler/migrations/0064_consolidate_template_pipelines.py:119` | `row.roi_display_color or "255\\255\\0"` | **RGB** (legacy field) |
| W4 | `dicom_handler/xml_template_views.py:513` | `xml_struct['dicom_color'] or "255\\255\\0"` | **RGB** (XML validated as DICOM color) |
| W5 | `rule_based_segmentation/utils/legacy_synthesis.py:222` | `additional_structure.roi_display_color` | **RGB** (legacy field) |
| W6 | `rule_based_segmentation/models.py:147` (`PipelineRule.clean()`) | `"255\\255\\0"` when blank | **RGB** (only if `clean()` runs) |

### Readers (DB → execution / UI)

| # | Location | Accepts hex? | Accepts `R\G\B`? |
|---|----------|:---:|:---:|
| R1 | `rule_based_segmentation/utils/engine.py:555,658` (`_parse_color`) | ✅ | ✅ |
| R2 | `rule_based_segmentation/utils/pipeline_persistence.py:451,459` (`_rgb_dicom_to_hex`) | ❌ **→ `#FFFF00`** | ✅ |
| R3 | `dicom_handler/forms.py:517` (legacy form clean) | ❌ | ✅ |
| R4 | `dicom_handler/models.py:235,323` (legacy model clean) | ❌ | ✅ |

### Readers (DICOM file → UI, assume a 3-part value)

| # | Location |
|---|----------|
| F1 | `rule_based_segmentation/views.py:695` — `[int(c) for c in color[:3]]` |
| F2 | `dicom_handler/dicom_viewer_views.py:307` — `color_values[0]/255.0` |
| F3 | `dicom_handler/import_services/task2_reidentify_rtstruct.py:493` — `roi_display_color.split('\\')` |
| F4 | `dicom_handler/views.py:1045` — `roi_display_color.split('\\')` |

**The field's original intent** was RGB: `rule_based_segmentation/migrations/0001_initial.py:49`
help_text = *"DICOM color string e.g. '255\0\0'. Defaults to yellow if blank."*

---

## 3. Why hex ended up in the DB

1. The web UI uses a **native HTML `<input type="color">`** (`rule_based_pipeline_builder.js:580`),
   which is inherently hex — it only accepts/produces 6-digit `#RRGGBB`.
2. The RBS builder (written after the field existed) works in hex end-to-end and stores the
   picker's value **verbatim** (`_save_rule` does no format normalization).
3. The field was designed for RGB (DICOM-native). The engine's `_parse_color` was added to
   **tolerate both** so execution stayed correct despite the drift.
4. The read-back helper `_rgb_dicom_to_hex` was only written for the **RGB → hex** direction
   (to feed the hex UI picker). It was never told to pass hex through — so the round-trip is
   asymmetric and broken for hex.

Net: the writer drifted to hex, the runtime was made format-agnostic, but the reader was not.

---

## 4. Consequences (bugs found)

### Bug 1 — Color loss on re-edit (high severity, data loss)

`_rgb_dicom_to_hex` (R2) splits on `\`; a hex string has no backslashes → 1 part → returns the
`#FFFF00` default. Verified:

```
_rgb_dicom_to_hex("#FF0000") -> "#FFFF00"   # WRONG (should be #FF0000)
_rgb_dicom_to_hex("#C0C0C0") -> "#FFFF00"   # WRONG
_rgb_dicom_to_hex("255\0\0") -> "#FF0000"   # correct
```

Both editors load through this path — the RBS pipeline editor
(`rule_based_segmentation/views.py:99`) and the template additional-structures editor
(`dicom_handler/pipeline_builder_views.py:131`), both via `pipeline_data_from_pipeline` →
`rule_to_json` → `_rgb_dicom_to_hex`.

**Cycle:** build pipeline in UI (colors saved as hex) → close → reopen → all colors render
**yellow** → re-save (even unchanged) → yellow persisted → **the original colors are gone.**

This only affects **hex-stored** rows (UI-built RBS pipelines). **RGB-stored** rows (the
consolidated template pipelines from migration 0064, XML imports, legacy) read back correctly.

### Bug 2 — Inherit-from-source is unreachable via the UI (low severity, latent)

The engine has a fallback: a rule with no color inherits its primary source's color
(`engine.py:579-592`). But the UI **always** assigns a color (JS default `#FFFF00`; and
`_save_rule`'s `or "255\\255\\0"` fills any blank), so a UI-saved rule always has a non-empty
color and the fallback never fires. It is only reachable by creating a rule directly with
`output_color=None` (`PipelineRule.objects.create`) — covered by
`rule_based_segmentation/tests/test_roi_fidelity.py::test_unset_color_inherits_from_source`.
Not a functional bug today (the UI always supplies a color), but the feature is effectively
vestigial for the normal path.

---

## 5. Consequences of normalizing to each format

### Store `R\G\B` (DICOM-native) — **recommended**

Pros:
- Matches the **DICOM native** format → direct write to `ROIDisplayColor`, no parse for output.
- Matches the field's **documented intent** (0001 help_text) and the **rest of the system**
  (`StructureProperties.roi_display_color`, task2, views, forms all assume `R\G\B`).
- The existing read-back `_rgb_dicom_to_hex` (RGB→hex) **already works** for RGB.
- Makes the DB column **self-consistent** (one format), removing the drift.

Cons / work:
- The UI picker is hex → add a **hex↔RGB conversion at the boundary**: the builder JS
  (or `_save_rule`) converts hex→RGB on save; read-back (RGB→hex) already exists.
- A **one-off migration** to convert existing hex rows to RGB.
- Slightly less web-native in the DB (mitigated — `255\0\0` is still readable).

### Store hex (web-native)

Pros:
- Matches the UI; no JS serialization change.

Cons / work:
- Must fix `_rgb_dicom_to_hex` to pass hex through (or rewrite the read-back).
- Must migrate existing RGB rows → hex.
- **Diverges from the DICOM-native format and the field's documented intent**, and keeps the
  column inconsistent with every other color field in the app (`roi_display_color`).

**Net:** normalizing to **`R\G\B`** is lower-cost (the read-back and all legacy readers already
speak RGB) and removes the round-trip bug at the root.

---

## 6. Recommendation

**Canonical format: store `R\G\B` in the DB.** Implement in two steps.

**Step 1 — stop the data loss now (safe, no schema change).**
Make `_rgb_dicom_to_hex` tolerate hex: if the value already looks like hex (`#RGB`/`#RRGGBB`),
normalize it to 6-digit uppercase hex and return it, instead of falling through to yellow. This
alone stops the "colors turn yellow on re-edit" bug for existing hex rows, with no migration.

**Step 2 — normalize the column to `R\G\B` (canonical).**
- Add a `hex_to_rgb_dicom()` helper (inverse of `_rgb_dicom_to_hex`); have `_save_rule`
  normalize `output_color` to `R\G\B` before storing (so the DB is always RGB).
- Add a one-off migration that converts any remaining hex `output_color` values to `R\G\B`.
- Keep `_rgb_dicom_to_hex` as the single RGB→hex read-back for the UI.

**Verification already in place**
- `rule_based_segmentation/tests/test_color_e2e.py` (new): runs the real pipeline over the
  de-identified `tests/dicom_data` set and asserts each generated ROI's **on-disk**
  `ROIDisplayColor` — explicit colors round-trip correctly; documents the builder's
  unset→yellow default.
- `rule_based_segmentation/tests/test_roi_fidelity.py`: explicit + inherited color reach DICOM
  (in-memory), plus the new on-disk assertion.

---

## 7. Implementation status (2026-11-27)

Implemented (branch `rbs-integration`, per the recommendation above):

- **Step 1** — `_rgb_dicom_to_hex` (`pipeline_persistence.py`) now normalizes a hex
  input to 6-digit uppercase hex instead of falling through to `#FFFF00`. This alone
  stops the "colors turn yellow on re-edit" data loss.
- **Step 2** — added `_hex_to_rgb_dicom` (inverse); `_save_rule` now stores the
  **canonical `R\G\B`** (so the DB is always DICOM-native); `_rgb_dicom_to_hex`
  remains the single RGB→hex read-back for the UI.
- **New data migration** `rule_based_segmentation/migrations/0016_normalize_output_color_to_rgb.py`
  converts pre-existing hex rows to `R\G\B` (idempotent, transactional, self-contained,
  and reversible). **No existing migration file was edited.**
- **Migration applied to production:** 57 hex rows → RGB; the column is now 0 hex /
  72 RGB / 42 NULL.
- **Tests:** `rule_based_segmentation/tests/test_color_format.py` (helpers, save
  normalization, round-trip, migration) and the on-disk assertions in
  `test_color_e2e.py` / `test_roi_fidelity.py`. Full RBS + dicom_handler suites green.

---

## Appendix: production data (as of audit)

`PipelineRule.output_color` distinct values show the mix concretely — hex (`#FF0000`, `#C0C0C0`,
`#ffff00`, …), RGB (`255\0\0`, `255\255\0`), and `NULL`. The hex rows come from UI-built
pipelines (W1/W2); the RGB rows from migration 0064 / XML / legacy (W3/W4/W5); the `NULL`s
from rules created without a color via a path that bypassed `_save_rule`.
