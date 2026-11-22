# Rule-Based Output Structure Set (new file + preserved approval) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the rule-based pipeline from overwriting the input RTStructure Set file. Instead, `finalize_job` produces a **new** RTStructure Set DICOM file (new SOP/Series UIDs) that contains the original structures **and** the new ones, registered as a **new** `RTStructureSetFile` with **per-ROI approval** — original ROIs inherit the input file's approval (status/date/reviewer), new and replaced ROIs are `UNAPPROVED`. The new file's file-level DICOM approval is `UNAPPROVED`.

**Architecture:** The DICOM **Approval Module** (RT Structure Set IOD) is *file-level*: `(300E,0002)` Approval Status, `(300E,0004)` Review Date, `(300E,0005)` Review Time, `(300E,0008)` Reviewer Name — one set per RTSTRUCT file, not per ROI. So per-ROI approval lives in the app's DB (`RTStructureSetVOI`, which gains approval fields). `finalize_job` is reworked to: (1) save the engine's RTStruct (already original+new ROIs) to a **new** path instead of the input path; (2) set the new file's file-level `300E,0002 = UNAPPROVED` and clear the review date/time/reviewer; (3) create a new `RTStructureSetFile` record; (4) create `RTStructureSetVOI` rows for every ROI with per-ROI approval (original → inherited from input's `300E`; created/replaced → `UNAPPROVED`); (5) still C-STORE the new file to the destination node. The input file and its `RTStructureSetFile` record are left **untouched**.

**Tech Stack:** Python 3.13 (venv at `venv/`), Django 6.0.10, pydicom 3.0.2, rt-utils 2.5.0. Dev DB is Postgres via `.env`.

## Global Constraints

- Test command: `venv/bin/python manage.py test rule_based_segmentation.<module> -v 2`.
- One commit per task. Conventional messages.
- The input RTStruct file must remain byte-identical after a job (no more in-place overwrite; the `prepare_job` timestamped backup is no longer required and is removed).
- The input `RTStructureSetFile` / `RTStructureFileImport` records must NOT be re-pointed to new UIDs (they keep the original file's UIDs).
- New file UIDs: new SOPInstanceUID + SeriesInstanceUID; StudyInstanceUID + ReferencedFrameOfReferenceSequence preserved (existing `regenerate_instance_uids` already does this).
- New file must be importable into a TPS (valid RTSTRUCT; new UIDs avoid the "already exists" rejection).
- Per-ROI approval is stored in `RTStructureSetVOI` (DB), not in the DICOM file (DICOM only carries file-level approval).
- Do NOT touch the mask axis conventions in `utils/rtstruct_io.py` or the Celery chain arg-contract in `tasks.py`.

## Design notes

### DICOM Approval Module (file-level)
RT Structure Set IOD, Approval Module (PS3.3 C.8.8 / module "Approval"):
- `(300E,0002)` **Approval Status** — CS: `APPROVED` / `UNAPPROVED` / `REJECTED`
- `(300E,0004)` **Review Date** — DA (type 2)
- `(300E,0005)` **Review Time** — TM (type 2)
- `(300E,0008)` **Reviewer Name** — PN (type 2)

These are SOP-instance (file) attributes. An RTSTRUCT with `APPROVED` status carries the review date/time and the reviewer. This is the "approval ... from the original RTSTRUCT file" the user reads.

### Per-ROI approval (app DB)
`RTStructureSetVOI` (one row per ROI in a `RTStructureSetFile`) gains:
- `approval_status` — CharField, choices `APPROVED`/`UNAPPROVED`/`REJECTED`, default `UNAPPROVED`
- `review_date` — DateField, null/blank
- `review_time` — TimeField, null/blank
- `reviewer_name` — CharField, null/blank

### Output structure set semantics
For each ROI in the output RTStruct (original + new):
- If the ROI was **created** by a rule (`output_action=CREATE_NEW`) or **replaced** (`output_action=REPLACE_EXISTING`) → `UNAPPROVED` (a modified structure must be re-reviewed).
- Otherwise (an original ROI untouched by any rule) → inherit the **input file's** `300E` approval (status/date/time/reviewer).

The set of created/replaced ROI names comes from the job's `RuleStep` rows (`output_roi_name` + `rule__output_action`), already computed in `finalize_job`'s summary (`created_rois`, `replaced_rois`).

### New file location + naming
- Same directory as the input file (keeps original + output together).
- Deterministic, job-unique name: `<input_stem>__rbs_<job_id[:8]>.dcm` (idempotent under redelivery).
- New `RTStructureSetFile` record: same study/patient/series UIDs as input, new SOP/Series UIDs, `structure_set_label` = `<original label> (RBS)` (or original label if empty), `structure_set_date` = today, `rtstructure_file_path` = new path, `working_directory` = input's dir.

### File-level approval of the new file
- `(300E,0002)` = `UNAPPROVED` (the file now contains unapproved new content; the whole set is not re-reviewed).
- `(300E,0004/0005/0008)` cleared (no file-level review recorded).

### What changes in `finalize_job`
- `save_rtstruct(engine.rtstruct, rtstruct_path)` → `save_rtstruct(engine.rtstruct, new_path)` (new file).
- Set file-level `300E` to UNAPPROVED on `engine.rtstruct.ds` before saving.
- Remove `_sync_record_uids` (input record no longer re-pointed) and the in-place-marking part of `_mark_rtstruct_as_rule_based`; instead create the new `RTStructureSetFile` + `RTStructureSetVOI` rows (per-ROI approval).
- `job.output_file_path` = new path.
- Keep `_push_output_to_destination` (C-STORE the new file).
- `prepare_job`: drop the `_backup_rtstruct` call + `job.backup_file_path` (input is never modified now).

## Task 1: `RTStructureSetVOI` approval fields + migration + approval-reader util

**Files:**
- Modify: `spatial_overlap/models.py`
- Modify: `rule_based_segmentation/utils/rtstruct_io.py` (add `read_approval_info`)
- Create: `spatial_overlap/migrations/00XX_...py` (via `makemigrations`)

**Interfaces:**
- Produces: `RTStructureSetVOI.approval_status/review_date/review_time/reviewer_name`; `read_approval_info(path) -> dict{status, review_date, review_time, reviewer_name}` (all `None`/`""` when absent).

- [ ] **Step 1: Add the four approval fields to `RTStructureSetVOI`** in `spatial_overlap/models.py`:

```python
    APPROVAL_STATUS_CHOICES = [
        ("APPROVED", "Approved"),
        ("UNAPPROVED", "Unapproved"),
        ("REJECTED", "Rejected"),
    ]

    approval_status = models.CharField(
        max_length=16,
        choices=APPROVAL_STATUS_CHOICES,
        default="UNAPPROVED",
        verbose_name="ROI Approval Status",
    )
    review_date = models.DateField(null=True, blank=True, verbose_name="Review Date")
    review_time = models.TimeField(null=True, blank=True, verbose_name="Review Time")
    reviewer_name = models.CharField(
        max_length=255, null=True, blank=True, verbose_name="Reviewer Name"
    )
```

(add these fields inside the `RTStructureSetVOI` class, after `roi_number`.)

- [ ] **Step 2: Migrate** — `venv/bin/python manage.py makemigrations spatial_overlap` then `venv/bin/python manage.py migrate`.

- [ ] **Step 3: Add `read_approval_info` to `rtstruct_io.py`**:

```python
def read_approval_info(rtstruct_path: str) -> Dict[str, Optional[str]]:
    """Read the file-level DICOM Approval Module from an RTStruct.

    Returns a dict with keys: status, review_date, review_time, reviewer_name.
    Values are None when the corresponding (300E,xxxx) attribute is absent.
    """
    ds = pydicom.dcmread(rtstruct_path, stop_before_pixels=True, force=True)

    status = getattr(ds, "ApprovalStatus", None)  # (300E,0002)
    review_date = getattr(ds, "ReviewDate", None)  # (300E,0004)
    review_time = getattr(ds, "ReviewTime", None)  # (300E,0005)
    reviewer_name = getattr(ds, "ReviewerName", None)  # (300E,0008)

    def _clean(v):
        if v is None:
            return None
        s = str(v).strip()
        return s or None

    return {
        "status": _clean(status),
        "review_date": _clean(review_date),
        "review_time": _clean(review_time),
        "reviewer_name": _clean(reviewer_name),
    }
```

- [ ] **Step 4: Verify** — `venv/bin/python manage.py check` clean; import `read_approval_info` in a shell and confirm it returns `None`-ish for a file without 300E tags.

- [ ] **Step 5: Commit** — `git commit -m "feat(rbs): add per-ROI approval fields + 300E approval reader"`

## Task 2: Output structure set builder util

**Files:**
- Create: `rule_based_segmentation/utils/structure_set_output.py`
- Modify: `rule_based_segmentation/utils/rtstruct_io.py` (optional: helper to set file-level approval)

**Interfaces:**
- Consumes: `read_approval_info`, `regenerate_instance_uids`, `save_rtstruct`, `RTStructureSetFile`, `RTStructureSetVOI`, pydicom.
- Produces: `build_output_structure_set(rtstruct_builder, input_path, job, created_rois, replaced_rois) -> dict` returning `{"new_path": ..., "sop_instance_uid": ..., "series_instance_uid": ..., "record_id": ..., "new_rois": [...], "preserved_rois": [...]}`.

- [ ] **Step 1: Write the module** `structure_set_output.py`:

```python
"""Build the rule-based OUTPUT structure set: a new RTSTRUCT file (new UIDs)
containing original + new ROIs, registered as a new RTStructureSetFile with
per-ROI approval (original ROIs inherit the input file's 300E approval; new and
replaced ROIs are UNAPPROVED). The input file is never modified.
"""
import os
import logging
from datetime import date, datetime, time
from typing import Dict, List

import pydicom
from pydicom.dataset import Dataset

from spatial_overlap.models import RTStructureSetFile, RTStructureSetVOI
from .rtstruct_io import read_approval_info

logger = logging.getLogger(__name__)


def _new_output_path(input_path: str, job_id: str) -> str:
    d = os.path.dirname(input_path) or "."
    stem = os.path.splitext(os.path.basename(input_path))[0]
    return os.path.join(d, f"{stem}__rbs_{str(job_id)[:8]}.dcm")


def _set_file_approval_unapproved(ds: Dataset) -> None:
    ds.ApprovalStatus = "UNAPPROVED"  # (300E,0002)
    for attr in ("ReviewDate", "ReviewTime", "ReviewerName"):  # (300E,0004/0005/0008)
        if attr in ds:
            delattr(ds, attr)


def _parse_date(v):
    if not v:
        return None
    try:
        return datetime.strptime(str(v), "%Y%m%d").date()
    except ValueError:
        return None


def _parse_time(v):
    if not v:
        return None
    try:
        return datetime.strptime(str(v), "%H%M%S").time()
    except ValueError:
        return None


def build_output_structure_set(
    rtstruct_builder,
    input_path: str,
    job,
    created_rois: List[str],
    replaced_rois: List[str],
) -> dict:
    """Save rtstruct_builder to a NEW file and register it as a new structure set.

    `rtstruct_builder` must already have new SOP/Series UIDs assigned (call
    `regenerate_instance_uids` first) and contain all ROIs (original + new).
    """
    ds = rtstruct_builder.ds
    sop_uid = str(ds.SOPInstanceUID)
    series_uid = str(ds.SeriesInstanceUID)
    study_uid = str(getattr(ds, "StudyInstanceUID", ""))
    patient_name = str(getattr(ds, "PatientName", ""))
    patient_id = str(getattr(ds, "PatientID", ""))
    original_label = str(getattr(ds, "StructureSetLabel", "") or "")

    # File-level approval of the NEW file: UNAPPROVED (it contains new content).
    _set_file_approval_unapproved(ds)

    new_path = _new_output_path(input_path, job.id)
    rtstruct_builder.save(new_path)

    # Input file's per-ROI approval is inherited by untouched original ROIs.
    approval = read_approval_info(input_path)
    inherited_status = approval["status"] or "UNAPPROVED"
    inherited_date = _parse_date(approval["review_date"])
    inherited_time = _parse_time(approval["review_time"])
    inherited_reviewer = approval["reviewer_name"]

    label = f"{original_label} (RBS)" if original_label else "RBS output"
    record = RTStructureSetFile.objects.create(
        patient_name=patient_name,
        patient_id=patient_id,
        study_instance_uid=study_uid,
        series_instance_uid=series_uid,
        sop_instance_uid=sop_uid,
        structure_set_label=label,
        referenced_series_instance_uid=_referenced_series_uid(ds),
        structure_set_date=date.today(),
        rtstructure_file_path=new_path,
        working_directory=os.path.dirname(new_path) or None,
    )

    created = set(created_rois)
    replaced = set(replaced_rois)
    new_rois, preserved_rois = [], []
    for roi in ds.StructureSetROISequence:
        name = str(getattr(roi, "ROIName", ""))
        if not name:
            continue
        description = str(getattr(roi, "ROIDescription", "") or "")
        number = int(getattr(roi, "ROINumber", 0))
        if name in created or name in replaced:
            voi = RTStructureSetVOI.objects.create(
                rtstructure_set_file=record,
                roi_name=name,
                roi_description=description,
                roi_number=number,
                approval_status="UNAPPROVED",
            )
            new_rois.append(name)
        else:
            voi = RTStructureSetVOI.objects.create(
                rtstructure_set_file=record,
                roi_name=name,
                roi_description=description,
                roi_number=number,
                approval_status=inherited_status,
                review_date=inherited_date,
                review_time=inherited_time,
                reviewer_name=inherited_reviewer,
            )
            preserved_rois.append(name)

    logger.info(
        f"Output structure set {record.id}: {len(new_rois)} new, {len(preserved_rois)} preserved -> {new_path}"
    )
    return {
        "new_path": new_path,
        "sop_instance_uid": sop_uid,
        "series_instance_uid": series_uid,
        "record_id": record.id,
        "new_rois": new_rois,
        "preserved_rois": preserved_rois,
    }


def _referenced_series_uid(ds) -> str:
    for ref_frame in getattr(ds, "ReferencedFrameOfReferenceSequence", []) or []:
        for ref_study in getattr(ref_frame, "RTReferencedStudySequence", []) or []:
            for ref_series in getattr(ref_study, "RTReferencedSeriesSequence", []) or []:
                uid = getattr(ref_series, "SeriesInstanceUID", None)
                if uid:
                    return str(uid)
    return ""
```

- [ ] **Step 2: Unit-test `build_output_structure_set`** — create a synthetic input RTStruct (via existing test helpers) with a `300E` approval block, add a new ROI, call `regenerate_instance_uids` + `build_output_structure_set`, and assert: new file exists at a different path; input file unchanged; new `RTStructureSetFile` record created; original ROI VOI has inherited approval; new ROI VOI is `UNAPPROVED`; new file's `300E,0002 == UNAPPROVED`.

- [ ] **Step 3: Run + commit** — `git commit -m "feat(rbs): build output structure set with per-ROI approval"`

## Task 3: Rework `finalize_job` / `prepare_job` to emit the new structure set

**Files:**
- Modify: `rule_based_segmentation/utils/job_service.py`

**Interfaces:**
- Consumes: `build_output_structure_set`, `regenerate_instance_uids`, `save_rtstruct`.
- Produces: `job.output_file_path` = new file; new `RTStructureSetFile` record; input file untouched.

- [ ] **Step 1: Update `prepare_job`** — remove the `_backup_rtstruct` call and `job.backup_file_path` assignment (input is never modified now). Keep everything else.

- [ ] **Step 2: Rework `finalize_job`** — replace the save + record-sync block:

```python
    engine = SegmentationEngine.from_workdir(wd.root)
    new_sop_uid, new_series_uid = regenerate_instance_uids(engine.rtstruct)
    # (do NOT save over the input path anymore)
```

Compute `created_rois` / `replaced_rois` (as now), then:

```python
    from .structure_set_output import build_output_structure_set
    output = build_output_structure_set(
        engine.rtstruct,
        rtstruct_path,          # input path (only used to locate dir + read 300E)
        job,
        created_rois,
        replaced_rois,
    )
```

- [ ] **Step 3: Set `job.output_file_path = output["new_path"]`** and add `output["record_id"]`, `output["new_rois"]`, `output["preserved_rois"]` to `job.result_summary`.

- [ ] **Step 4: Remove `_sync_record_uids`** (input record no longer re-pointed) and the in-place marking in `_mark_rtstruct_as_rule_based` that re-writes the input record's UIDs / status. (For IMPORT inputs, keep a lightweight status mark on the `RTStructureFileImport` if desired, but do NOT change its file path/UIDs.) Keep `_push_output_to_destination` but push `output["new_path"]`.

- [ ] **Step 5: Idempotency** — if `job.status == "SUCCESS"` already, early-return (existing guard). Ensure re-running finalize on the same job does not duplicate the `RTStructureSetFile` record (guard: if a record with the output SOP UID already exists, reuse it).

- [ ] **Step 6: Test** — extend `tests/test_tasks.py` / `test_pipeline_steps.py` to assert: after `finalize_job`, the input file bytes are unchanged, a new file exists, a new `RTStructureSetFile` record exists with per-ROI approval, and the input `RTStructureSetFile` record is unchanged.

- [ ] **Step 7: Run full rule_based_segmentation suite** (fast modules first) + **commit** — `git commit -m "feat(rbs): finalize writes a new structure set; input file untouched"`

## Task 4: (Optional) Surface per-ROI approval in the structure set UI

**Files:**
- Modify: `spatial_overlap/views.py` (`list_rtstructs` context) + `templates/spatial_overlap/list_rtstructs.html` (or the structure set detail template).

- [ ] **Step 1:** Show `approval_status` (and reviewer/date) per ROI in the structure set list/detail.
- [ ] **Step 2:** Test + commit.

## Task 5: Final verification

- [ ] Full suite: `venv/bin/python manage.py test rule_based_segmentation spatial_overlap -v 1` (expect all green; include the physics e2e if feasible).
- [ ] `manage.py check` clean.
- [ ] Confirm no code path still writes to the input `rtstruct_path` via `save_rtstruct`.
- [ ] Confirm the new file is a valid RTSTRUCT (re-read with pydicom; `300E,0002 == UNAPPROVED`; all ROIs present).

## Rollout / deployment notes
- Run `manage.py migrate` (new `spatial_overlap` migration for the VOI approval fields).
- No Celery/queue changes; `finalize_job` is reworked in place.
- The input structure set and its DB record are preserved; the pipeline now adds a sibling output structure set.
- Existing structure sets (no approval fields) default to `UNAPPROVED` on their VOIs (safe default); backfilling historical approval is a separate, optional migration.

## Implementation status (complete 2026-11-22)
All tasks implemented and verified:

- **Task 1** (`16b4dad`) — `RTStructureSetVOI.approval_status/review_date/review_time/reviewer_name` + migration `spatial_overlap/0007_...`; `read_approval_info()` in `rtstruct_io.py`.
- **Task 2** (`5a891ca`) — `structure_set_output.build_output_structure_set()` + `tests/test_structure_set_output.py` (4 tests).
- **Task 3** (`3121db4`) — `finalize_job` emits a new structure set (new file, new `RTStructureSetFile` record, per-ROI approval, input untouched, pushes the new file); `prepare_job` no longer backs up the input; `_sync_record_uids` removed; `_mark_rtstruct_as_rule_based` reduced to a status-only mark. Tests updated in `test_pipeline_steps.py` and `test_pipeline_e2e_physics.py`. Added an idempotency guard: if a crashed prior finalize already wrote the output file, redelivery reloads it (stable UIDs) instead of creating a duplicate record.
- **Task 4** (`90d31ba`) — per-ROI approval badge (Approved/Unapproved/Rejected) + reviewer/date in `rtstruct_detail.html`.
- **Task 5** — full suite green: 109 fast tests + 15 physics e2e tests (124 total); `manage.py check` clean; no pending migrations; `save_rtstruct` is no longer called from the job flow (input never overwritten).

### Notes / follow-ups
- The new file's DICOM label is `<original> (RBS)` (or `RBS output` when the original label is empty) and is idempotent under redelivery.
- The legacy `SegmentationEngine.run()` still writes in place (`engine.py:135`) but is unused by the chain flow (only engine unit tests call it).
- Output file name is deterministic per job: `<input_stem>__rbs_<job_id[:8]>.dcm` in the input file's directory.
