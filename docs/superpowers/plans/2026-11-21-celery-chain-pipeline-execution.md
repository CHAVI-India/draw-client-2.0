# Celery-Chain Pipeline Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single monolithic `run_segmentation_job` Celery task with a sequential Celery chain — `prepare_job → run_rule_step(order 1..N) → finalize_job` — so each rule is an independent, re-entrant task that persists its result to a per-job work directory, with per-step progress, failure localization, and retry-from-failed-step.

**Architecture:** Intermediate state (today held only in the engine's in-memory `available_masks` dict and mutated `RTStruct` dataset) is persisted to a per-job work directory: a copied image-series dir (for rt-utils), a NIfTI cache of the reference image, and `working.dcm` — the RTStruct with all *completed* rules applied, updated via crash-safe commit-by-rename plus a per-step JSON manifest. Each chain step reloads this state, does one rule, and commits. Celery chain contract (CRITICAL): the previous task's return value is PREPENDED as the next task's first positional arg (`canvas.Signature._merge`), so ONLY the chain head (`prepare_job`) carries `job_id` explicitly — every non-head signature (`run_rule_step.s(order)`, `finalize_job.s()`) must NOT store `job_id` again, or the injected value overflows the function's positional parameters (`TypeError: takes N positional arguments but N+1 were given`). Every step returns `job_id` (str) to feed the next task.

**Tech Stack:** Python 3.13 (venv at `venv/`), Django 6.0.10, Celery 5.6.3 (`task_acks_late=True` already set in `draw_client/celery.py`), celery-chain via `celery.chain`, rt-utils 2.5.0, SimpleITK, pydicom 3.0.2, django-celery-beat 2.9.0.

**Spec:** Design agreed in the 2026-11-21 code-review conversation; captured in "Design notes" below.

## Global Constraints

- Test command (no broker needed — tests call service functions and task wrappers in-process, and build chain signatures without dispatching):
  `venv/bin/python manage.py test rule_based_segmentation.tests.<module> -v 2`
- `SegmentationEngine.run_pipeline` must keep its current external behavior — the existing suites `tests/test_engine.py`, `tests/test_end_to_end.py`, `tests/test_pipeline_e2e_physics.py` must pass with **all assertions unchanged** (Task 5 Step 3 re-points the physics suite's execution driver from the removed `run_job` to the new chain-step functions; no test logic or assertions are modified).
- Do NOT touch the mask axis conventions in `utils/rtstruct_io.py` (`transpose(2, 1, 0)` calls) — a known separate issue, out of scope for this plan.
- When logging file paths, use `mask_sensitive_data` from `dicom_handler.utils.log_masking` (existing pattern).
- A pipeline is immutable while one of its jobs runs (pre-existing assumption; rule edits mid-run are out of scope).
- One commit per task. Conventional-style messages (`feat:` / `refactor:` / `test:` / `chore:`).
- New DB models require `makemigrations` + `migrate` (dev DB on this machine is Postgres via `.env`; the test runner builds its own schema, so only `makemigrations` matters for CI, but run `migrate` for the dev DB).
- Celery 5.6 quirk: `chain(...)` returns a signature whose constituent tasks live in `.tasks` (iterating the chain object yields signature field names, NOT the tasks). Tests must use `c.tasks`.

## Design notes (crash semantics)

Commit protocol per rule step (in `JobWorkdir.commit_rule_output`):
1. save updated RTStruct to `working.tmp.dcm`
2. atomically write `step-{order}.json` (`{"output_name": <chosen ROI name>}`)
3. `os.replace(working.tmp.dcm → working.dcm)`

Redelivery (worker killed; `acks_late`) at each point:
- before (1): nothing visible → step redoes evaluation; rename-suffix logic in `engine._add_rule_output_to_rtstruct` is deterministic on the pre-commit state, so it re-derives the same output name.
- between (1) and (3): manifest exists but `working.dcm` is pre-commit → `rule_already_committed()` is False → re-evaluate + re-commit, same name.
- after (3), before step `SUCCESS` in DB: `rule_already_committed()` is True → step marks SUCCESS without re-adding (no duplicate ROI).

Failure semantics: a rule step that raises marks its `RuleStep` FAILED and the job FAILED, then re-raises so the chain stops (later steps are never enqueued). `finalize_job` is idempotent (skips if job already SUCCESS). `reap_stuck_jobs` (beat, every 5 min) is the safety net for lost messages / hard-timeout kills.

---

## File map

| File | Action | Responsibility |
|---|---|---|
| `rule_based_segmentation/models.py` | Modify | Add `RuleStep` model (per-rule execution record) |
| `rule_based_segmentation/migrations/0004_rulestep.py` | Create (makemigrations) | Migration for `RuleStep` |
| `rule_based_segmentation/admin.py` | Modify | Register `RuleStep` |
| `rule_based_segmentation/utils/job_workdir.py` | Create | Per-job work dir: paths, image cache, commit-by-rename protocol, manifests |
| `rule_based_segmentation/utils/rtstruct_io.py` | Modify | `load_rtstruct_and_image(..., instances_dir=None)`; public `copy_instances_to_directory` |
| `rule_based_segmentation/utils/engine.py` | Modify | `SegmentationEngine.from_workdir()` classmethod; `run_rule(rule)` single-rule method; `run_pipeline` loop refactored onto `run_rule` (behavior unchanged) |
| `rule_based_segmentation/utils/job_service.py` | Modify | `prepare_job`, `execute_rule_step`, `finalize_job`, `resume_job` service functions; `create_segmentation_job` enqueues the chain; remove legacy `run_job` |
| `rule_based_segmentation/tasks.py` | Rewrite | Thin chain wrappers `prepare_job` / `run_rule_step` / `finalize_job` / `reap_stuck_jobs`, `build_job_chain`, `resume_job`; remove `run_segmentation_job` |
| `rule_based_segmentation/views.py` | Modify | `job_status` returns per-step progress; new `job_retry` POST view; `select_series_for_upload` resumes via `resume_job` |
| `rule_based_segmentation/urls.py` | Modify | `jobs/<uuid:job_id>/retry/` |
| `templates/rule_based_segmentation/job_status.html` | Modify | Steps list, step-based progress bar, retry button |
| `draw_client/settings.py` | Modify | Beat schedule entry for `reap_stuck_jobs` |
| `rule_based_segmentation/tests/test_models.py` | Modify | `RuleStep` model tests |
| `rule_based_segmentation/tests/test_job_workdir.py` | Create | Work dir + commit protocol tests |
| `rule_based_segmentation/tests/test_end_to_end.py` | Modify | `run_rule` / `from_workdir` / `instances_dir` tests (new class) |
| `rule_based_segmentation/tests/test_pipeline_steps.py` | Create | `prepare_job` / `execute_rule_step` / `finalize_job` tests on synthetic DICOM |
| `rule_based_segmentation/tests/test_tasks.py` | Rewrite | Chain shape, wrappers, `resume_job`, `reap_stuck_jobs` |
| `rule_based_segmentation/tests/test_views.py` | Modify | `job_status` steps payload, `job_retry` view |

---

### Task 1: `RuleStep` model + migration + admin

**Files:**
- Modify: `rule_based_segmentation/models.py` (append after `SegmentationJob`)
- Modify: `rule_based_segmentation/admin.py`
- Test: `rule_based_segmentation/tests/test_models.py`

**Interfaces:**
- Produces: `RuleStep` model — fields `job` (FK `SegmentationJob`, `related_name="steps"`), `rule` (FK `PipelineRule`), `order` (PositiveIntegerField), `status` (CharField, default `"PENDING"`, choices PENDING/RUNNING/SUCCESS/FAILED), `output_roi_name` (CharField 64, null), `error` (TextField, null), `started_at`/`completed_at` (DateTimeField, null), `created_at` (auto_now_add). Unique `(job, order)`. Later tasks rely on `job.steps`, `step.status`, `step.output_roi_name`, `step.rule.name`.

- [ ] **Step 1: Write the failing test**

Append to `rule_based_segmentation/tests/test_models.py` (add `RuleStep` and `IntegrityError` to the imports at the top: extend the existing `from ..models import (...)` block and add `from django.db import IntegrityError, transaction`):

```python
class RuleStepTests(TestCase):
    def test_step_defaults_and_unique_per_job_order(self):
        pipeline = SegmentationPipeline.objects.create(name="P")
        rule = PipelineRule.objects.create(
            pipeline=pipeline, order=1, rule_type="MARGIN", name="R"
        )
        job = SegmentationJob.objects.create(pipeline=pipeline, input_type="UPLOAD")

        step = RuleStep.objects.create(job=job, rule=rule, order=1)
        self.assertEqual(step.status, "PENDING")
        self.assertIsNone(step.output_roi_name)
        self.assertIsNone(step.started_at)

        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                RuleStep.objects.create(job=job, rule=rule, order=1)

        # Same job + order is unique, but a different order is fine.
        second = RuleStep.objects.create(job=job, rule=rule, order=2)
        self.assertEqual(second.order, 2)
        self.assertEqual(job.steps.count(), 2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python manage.py test rule_based_segmentation.tests.test_models -v 2`
Expected: FAIL with `ImportError: cannot import name 'RuleStep' from 'rule_based_segmentation.models'`

- [ ] **Step 3: Add the model**

Append to `rule_based_segmentation/models.py` (after the `SegmentationJob` class):

```python
class RuleStep(models.Model):
    """Execution record for one pipeline rule within a job (one chain step)."""

    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("RUNNING", "Running"),
        ("SUCCESS", "Success"),
        ("FAILED", "Failed"),
    ]

    job = models.ForeignKey(
        SegmentationJob,
        on_delete=models.CASCADE,
        related_name="steps",
    )
    rule = models.ForeignKey(
        PipelineRule,
        on_delete=models.CASCADE,
    )
    order = models.PositiveIntegerField()
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default="PENDING",
    )
    output_roi_name = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        help_text="ROI name actually written (may carry a dedup suffix).",
    )
    error = models.TextField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["job", "order"]
        constraints = [
            models.UniqueConstraint(
                fields=["job", "order"],
                name="uniq_rulestep_job_order",
            ),
        ]

    def __str__(self):
        return f"Job {self.job_id} step {self.order} ({self.status})"
```

- [ ] **Step 4: Create migration and migrate**

Run:
```bash
venv/bin/python manage.py makemigrations rule_based_segmentation
venv/bin/python manage.py migrate
```
Expected: creates `rule_based_segmentation/migrations/0004_rulestep.py`. Inspect it: it must contain only the `RuleStep` model (no unrelated drift).

- [ ] **Step 5: Register in admin**

In `rule_based_segmentation/admin.py`, add `RuleStep` to the import block and append:

```python
@admin.register(RuleStep)
class RuleStepAdmin(admin.ModelAdmin):
    list_display = ("job", "order", "rule", "status", "output_roi_name", "started_at", "completed_at")
    list_filter = ("status",)
    search_fields = ("job__id", "rule__name")
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `venv/bin/python manage.py test rule_based_segmentation.tests.test_models -v 2`
Expected: PASS (all tests in the module, including pre-existing ones)

- [ ] **Step 7: Commit**

```bash
git add rule_based_segmentation/models.py rule_based_segmentation/migrations/0004_rulestep.py rule_based_segmentation/admin.py rule_based_segmentation/tests/test_models.py
git commit -m "feat(rbs): add RuleStep model for per-rule job execution tracking"
```

---

### Task 2: `JobWorkdir` — per-job work directory and commit protocol

**Files:**
- Create: `rule_based_segmentation/utils/job_workdir.py`
- Test: `rule_based_segmentation/tests/test_job_workdir.py`

**Interfaces:**
- Produces:
  - `get_job_workdir_base() -> str` — `{SystemConfiguration.folder_configuration or cwd}/rule_based_segmentation/job_work`
  - `class JobWorkdir(job_id, base_dir: Optional[str] = None)` with attrs `root`, `images_dir`, `image_cache_path`, `working_path`, `working_tmp_path` and methods:
    - `create() -> None` (makes `root` + `images_dir`)
    - `exists() -> bool`
    - `cleanup() -> None` (rmtree root)
    - `save_image_cache(image: sitk.Image) -> None` / `load_image_cache() -> sitk.Image`
    - `copy_instances(instances: List[DICOMInstance]) -> None` (delegates to `rtstruct_io.copy_instances_to_directory` — that public name is created in Task 3; until Task 3 lands, this method must be present but only *called* in Task 4+, so implement it now with a lazy import)
    - `write_initial_working(rtstruct) -> None` (saves the pristine RTStruct to `working.dcm`)
    - `step_manifest_path(order: int) -> str`
    - `read_step_manifest(order: int) -> Optional[Dict[str, str]]`
    - `commit_rule_output(rtstruct, order: int, output_name: str) -> None` (the 3-step commit protocol from Design notes)
    - `rule_already_committed(rtstruct, order: int) -> bool`

- [ ] **Step 1: Write the failing tests**

Create `rule_based_segmentation/tests/test_job_workdir.py`:

```python
"""Tests for the per-job work directory and commit protocol."""

import json
import os
import shutil
import tempfile

import numpy as np
import SimpleITK as sitk
from django.test import SimpleTestCase

from ..utils.job_workdir import JobWorkdir


class _FakeRTStruct:
    """Mimics the rt_utils RTStruct surface JobWorkdir uses (save + get_roi_names)."""

    def __init__(self, roi_names=()):
        self._names = list(roi_names)

    def get_roi_names(self):
        return list(self._names)

    def save(self, path):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"names": self._names}, fh)


def _read_saved_names(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)["names"]


class JobWorkdirTests(SimpleTestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="rbs_wd_test_")
        self.wd = JobWorkdir("11111111-1111-1111-1111-111111111111", base_dir=self.base)

    def tearDown(self):
        shutil.rmtree(self.base, ignore_errors=True)

    def test_create_makes_images_dir(self):
        self.assertFalse(os.path.isdir(self.wd.images_dir))
        self.wd.create()
        self.assertTrue(os.path.isdir(self.wd.images_dir))
        self.assertTrue(self.wd.exists())

    def test_image_cache_roundtrip(self):
        image = sitk.Image((64, 64, 10), sitk.sitkInt16)
        image.SetOrigin((1.0, 2.0, 3.0))
        image.SetSpacing((0.5, 0.5, 2.0))
        self.wd.create()
        self.wd.save_image_cache(image)
        loaded = self.wd.load_image_cache()
        self.assertEqual(loaded.GetSize(), image.GetSize())
        self.assertEqual(loaded.GetOrigin(), image.GetOrigin())
        self.assertEqual(loaded.GetSpacing(), image.GetSpacing())
        self.assertTrue(
            np.array_equal(
                sitk.GetArrayFromImage(loaded), sitk.GetArrayFromImage(image)
            )
        )

    def test_commit_writes_working_and_manifest(self):
        self.wd.create()
        rtstruct = _FakeRTStruct(["Box", "PTV"])
        self.wd.commit_rule_output(rtstruct, order=1, output_name="PTV")
        self.assertEqual(_read_saved_names(self.wd.working_path), ["Box", "PTV"])
        with open(self.wd.step_manifest_path(1), "r", encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), {"output_name": "PTV"})
        # tmp file consumed by the rename
        self.assertFalse(os.path.exists(self.wd.working_tmp_path))

    def test_rule_already_committed(self):
        self.wd.create()
        self.wd.commit_rule_output(_FakeRTStruct(["Box", "PTV"]), 1, "PTV")
        self.assertTrue(self.wd.rule_already_committed(_FakeRTStruct(["Box", "PTV"]), 1))
        # manifest name absent from the RTStruct -> not committed
        self.assertFalse(self.wd.rule_already_committed(_FakeRTStruct(["Box"]), 1))
        # no manifest for this order -> not committed
        self.assertFalse(self.wd.rule_already_committed(_FakeRTStruct(["Box"]), 2))

    def test_cleanup_removes_root(self):
        self.wd.create()
        self.wd.cleanup()
        self.assertFalse(self.wd.exists())
        # cleanup is idempotent
        self.wd.cleanup()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/python manage.py test rule_based_segmentation.tests.test_job_workdir -v 2`
Expected: FAIL with `ModuleNotFoundError: No module named 'rule_based_segmentation.utils.job_workdir'`

- [ ] **Step 3: Implement `job_workdir.py`**

Create `rule_based_segmentation/utils/job_workdir.py`:

```python
"""Per-job working directory for chain-based pipeline execution.

Layout (under ``get_job_workdir_base()``):

    {job_id}/
        images/            copied DICOM instances (for rt-utils)
        image.nii.gz       SimpleITK cache of the reference image series
        working.dcm        RTStruct with all completed rules applied
        working.tmp.dcm    scratch file for commit-by-rename
        step-{order}.json  commit manifest: {"output_name": "<ROI name>"}

Commit protocol (crash-safe, see plan design notes):
    1. save updated RTStruct to working.tmp.dcm
    2. atomically write step-{order}.json (records the chosen ROI name)
    3. os.replace(working.tmp.dcm -> working.dcm)
"""

import json
import os
import shutil
from typing import Dict, List, Optional

import SimpleITK as sitk

from dicom_handler.models import DICOMInstance, SystemConfiguration


def get_job_workdir_base() -> str:
    """Base directory for job work dirs (mirrors the RTStruct upload dir layout)."""
    config = SystemConfiguration.load()
    base_dir = config.folder_configuration or os.getcwd()
    return os.path.join(base_dir, "rule_based_segmentation", "job_work")


class JobWorkdir:
    def __init__(self, job_id, base_dir: Optional[str] = None):
        self.job_id = str(job_id)
        self.root = os.path.join(base_dir or get_job_workdir_base(), self.job_id)
        self.images_dir = os.path.join(self.root, "images")
        self.image_cache_path = os.path.join(self.root, "image.nii.gz")
        self.working_path = os.path.join(self.root, "working.dcm")
        self.working_tmp_path = os.path.join(self.root, "working.tmp.dcm")

    # -- lifecycle ----------------------------------------------------------

    def create(self) -> None:
        os.makedirs(self.images_dir, exist_ok=True)

    def exists(self) -> bool:
        return os.path.isdir(self.root)

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    # -- image cache --------------------------------------------------------

    def save_image_cache(self, image: sitk.Image) -> None:
        sitk.WriteImage(image, self.image_cache_path, compressionLevel=3)

    def load_image_cache(self) -> sitk.Image:
        return sitk.ReadImage(self.image_cache_path)

    def copy_instances(self, instances: List[DICOMInstance]) -> None:
        from .rtstruct_io import copy_instances_to_directory

        copy_instances_to_directory(instances, self.images_dir)

    # -- working RTStruct ----------------------------------------------------

    def write_initial_working(self, rtstruct) -> None:
        """Persist the pristine RTStruct as the starting working file."""
        rtstruct.save(self.working_path)

    def step_manifest_path(self, order: int) -> str:
        return os.path.join(self.root, f"step-{order}.json")

    def read_step_manifest(self, order: int) -> Optional[Dict[str, str]]:
        path = self.step_manifest_path(order)
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)

    def commit_rule_output(self, rtstruct, order: int, output_name: str) -> None:
        """Atomically append a rule's output to the working RTStruct.

        See module docstring for the protocol. A redelivered step therefore
        either sees a complete commit (manifest name present in working.dcm)
        or a pre-commit state where the deterministic rename logic re-derives
        the same output name.
        """
        rtstruct.save(self.working_tmp_path)
        manifest_path = self.step_manifest_path(order)
        tmp_manifest = manifest_path + ".tmp"
        with open(tmp_manifest, "w", encoding="utf-8") as fh:
            json.dump({"output_name": output_name}, fh)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_manifest, manifest_path)
        os.replace(self.working_tmp_path, self.working_path)

    def rule_already_committed(self, rtstruct, order: int) -> bool:
        """True if this step's commit already applied to working.dcm."""
        manifest = self.read_step_manifest(order)
        if not manifest:
            return False
        return manifest.get("output_name") in rtstruct.get_roi_names()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/python manage.py test rule_based_segmentation.tests.test_job_workdir -v 2`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add rule_based_segmentation/utils/job_workdir.py rule_based_segmentation/tests/test_job_workdir.py
git commit -m "feat(rbs): add per-job work directory with crash-safe rule commit protocol"
```

---

### Task 3: Engine per-rule interface + persistent instances dir

**Files:**
- Modify: `rule_based_segmentation/utils/rtstruct_io.py`
- Modify: `rule_based_segmentation/utils/engine.py`
- Test: `rule_based_segmentation/tests/test_end_to_end.py` (new class, appended)

**Interfaces:**
- Produces:
  - `copy_instances_to_directory(instances: List[DICOMInstance], target_directory: str) -> None` (public rename of `_copy_instances_to_directory`)
  - `load_rtstruct_and_image(rtstruct_path: str, series_instance_uid: str, instances_dir: Optional[str] = None) -> Tuple[RTStructBuilder, sitk.Image, DICOMSeries]` — with `instances_dir` set, instances are copied *there* (not a temp dir) and the dir is kept after the call (caller owns it); cleanup on failure only when the dir was internally created
  - `SegmentationEngine.from_workdir(workdir_root: str) -> SegmentationEngine` — loads `working.dcm` (via rt-utils against `workdir_root/images`) + `image.nii.gz` cache; `self.series is None`; `self.available_masks` preloaded
  - `SegmentationEngine.run_rule(rule: PipelineRule) -> str` — evaluates one rule, appends its output to the in-memory RTStruct, stores the mask in `available_masks[rule.name]`; returns the (possibly suffixed) output ROI name. Does **not** save.
- Consumes: nothing new from earlier tasks.

- [ ] **Step 1: Write the failing tests**

Append to `rule_based_segmentation/tests/test_end_to_end.py` (the file already imports `os`, `shutil`, `tempfile`, `np`, `sitk`, `load_rtstruct_and_image`, `create_synthetic_ct_series`, `create_dicom_models`, `create_synthetic_rtstruct`, `create_pipeline_with_rules`; add `from ..utils.engine import SegmentationEngine` is already present — verify and reuse):

```python
class EngineStepTests(TestCase):
    """Per-rule engine interface used by the Celery chain (Task 3)."""

    def setUp(self):
        # Mirrors EndToEndSegmentationTests.setUp (kept separate so the base
        # suite's tests are not re-run under this class).
        self.temp_dir = tempfile.mkdtemp(prefix="rbs_step_")
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
        self.series = create_dicom_models(
            self.ct_files, self.series_uid, self.study_uid
        )
        self.mask_array = np.zeros((10, 64, 64), dtype=bool)
        self.mask_array[3:7, 28:36, 28:36] = True
        self.rtstruct_path = os.path.join(self.temp_dir, "test_rtstruct.dcm")
        create_synthetic_rtstruct(
            self.rtstruct_path,
            self.ct_files,
            roi_name="Box",
            mask_array=self.mask_array,
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _engine(self):
        return SegmentationEngine(self.rtstruct_path, self.series_uid)

    def test_run_rule_single_rule_matches_run_pipeline(self):
        pipeline = create_pipeline_with_rules(
            rules_data=[
                {
                    "rule_type": "MARGIN",
                    "name": "BoxExpanded",
                    "config": {
                        "variant": "UNIFORM",
                        "source": "Box",
                        "margin_mm": 2.0,
                        "kernel_type": "ball",
                    },
                }
            ]
        )
        stepped = self._engine()
        output_name = stepped.run_rule(pipeline.rules.first())
        self.assertEqual(output_name, "BoxExpanded")
        self.assertIn("BoxExpanded", stepped.rtstruct.get_roi_names())

        monolithic = self._engine()
        summary = monolithic.run_pipeline(pipeline)
        self.assertEqual(summary["created_rois"], ["BoxExpanded"])
        self.assertTrue(
            np.array_equal(
                sitk.GetArrayFromImage(stepped.available_masks["BoxExpanded"]),
                sitk.GetArrayFromImage(monolithic.available_masks["BoxExpanded"]),
            )
        )

    def test_run_rule_missing_structure_raises(self):
        from ..utils.expression_evaluator import RuleEvaluationError

        pipeline = create_pipeline_with_rules(
            rules_data=[
                {
                    "rule_type": "MARGIN",
                    "name": "Bad",
                    "config": {
                        "variant": "UNIFORM",
                        "source": "NoSuchStructure",
                        "margin_mm": 2.0,
                        "kernel_type": "ball",
                    },
                }
            ]
        )
        engine = self._engine()
        with self.assertRaises(RuleEvaluationError):
            engine.run_rule(pipeline.rules.first())

    def test_load_with_instances_dir_persists_copy(self):
        inst_dir = os.path.join(self.temp_dir, "inst")
        rtstruct, image, series = load_rtstruct_and_image(
            self.rtstruct_path, self.series_uid, instances_dir=inst_dir
        )
        self.assertTrue(os.path.isdir(inst_dir))
        self.assertEqual(len(os.listdir(inst_dir)), 10)
        self.assertIn("Box", rtstruct.get_roi_names())
        self.assertEqual(series.series_instance_uid, self.series_uid)

    def test_from_workdir_roundtrip(self):
        from ..utils.job_workdir import JobWorkdir

        base = os.path.join(self.temp_dir, "work")
        wd = JobWorkdir("22222222-2222-2222-2222-222222222222", base_dir=base)
        wd.create()
        # Build the work dir contents the way prepare_job will (Task 4).
        rtstruct, image, _series = load_rtstruct_and_image(
            self.rtstruct_path, self.series_uid, instances_dir=wd.images_dir
        )
        wd.save_image_cache(image)
        wd.write_initial_working(rtstruct)

        restored = SegmentationEngine.from_workdir(wd.root)
        self.assertIsNone(restored.series)
        self.assertIn("Box", restored.rtstruct.get_roi_names())
        self.assertEqual(
            restored.image.GetSize(), image.GetSize()
        )
        # masks loaded from the persisted state
        self.assertIn("Box", restored.available_masks)
        self.assertEqual(
            np.sum(sitk.GetArrayFromImage(restored.available_masks["Box"])),
            np.sum(self.mask_array),
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/python manage.py test rule_based_segmentation.tests.test_end_to_end.EngineStepTests -v 2`
Expected: FAIL — `AttributeError: ... has no attribute 'run_rule'` (and `from_workdir` / `instances_dir` failures)

- [ ] **Step 3: Refactor `rtstruct_io.py`**

In `rule_based_segmentation/utils/rtstruct_io.py`:

a) Rename `_copy_instances_to_directory` to `copy_instances_to_directory` (public; update the internal call site in `load_rtstruct_and_image`).

b) Replace `load_rtstruct_and_image` with:

```python
def load_rtstruct_and_image(
    rtstruct_path: str,
    series_instance_uid: str,
    instances_dir: Optional[str] = None,
) -> Tuple[RTStructBuilder, sitk.Image, DICOMSeries]:
    """
    Load an RTStruct and its referenced image series.

    Args:
        rtstruct_path: Path to the RTStruct DICOM file.
        series_instance_uid: Series Instance UID of the referenced CT/MR/PT series.
        instances_dir: If provided, DICOM instances are copied into this
            directory (created if missing) and left in place for the caller;
            otherwise a temporary directory is created and removed on failure.

    Returns:
        Tuple of (RTStructBuilder, SimpleITK image, DICOMSeries).

    Raises:
        ValueError: If the series is not found or has no instances.
        RuntimeError: If loading fails.
    """
    try:
        series = DICOMSeries.objects.get(series_instance_uid=series_instance_uid)
    except DICOMSeries.DoesNotExist:
        raise ValueError(f"DICOMSeries with UID {series_instance_uid} not found")

    instances = list(DICOMInstance.objects.filter(series_instance_uid=series))
    if not instances:
        raise ValueError(f"No DICOM instances found for series {series_instance_uid}")

    owns_dir = instances_dir is None
    work_dir = instances_dir or tempfile.mkdtemp(prefix="rbs_rtstruct_work_")
    try:
        if instances_dir:
            os.makedirs(instances_dir, exist_ok=True)
        # Copy only when the destination does not already hold all
        # instances. A prepared job work dir is re-loaded on every rule
        # step; re-copying hundreds of files each time would dominate
        # runtime. A partially populated dir (crash mid-copy) is
        # re-copied, since copy2 overwrites by name.
        if len(os.listdir(work_dir)) < len(instances):
            copy_instances_to_directory(instances, work_dir)

        rtstruct = RTStructBuilder.create_from(
            dicom_series_path=work_dir,
            rt_struct_path=rtstruct_path,
        )

        image = load_ct_series_as_sitk_image({"instances": instances, "series": series})

        logger.info(
            f"Loaded RTStruct {mask_sensitive_data(rtstruct_path, 'file_path')} with {len(instances)} image instances"
        )
        return rtstruct, image, series
    except Exception as e:
        if owns_dir and os.path.exists(work_dir):
            shutil.rmtree(work_dir, ignore_errors=True)
        logger.error(f"Failed to load RTStruct {mask_sensitive_data(rtstruct_path, 'file_path')}: {e}")
        raise RuntimeError(f"Failed to load RTStruct: {e}") from e
```

- [ ] **Step 4: Refactor `engine.py`**

In `rule_based_segmentation/utils/engine.py`:

a) Add `import os` to the imports.

b) Add `from_workdir` as a classmethod right after `__init__`:

```python
    @classmethod
    def from_workdir(cls, workdir_root: str) -> "SegmentationEngine":
        """
        Load engine state from a job work dir (see utils/job_workdir.py).

        Loads working.dcm (all previously completed rules applied) against the
        persisted instance copies in <workdir_root>/images, and the reference
        image from the NifTI cache. self.series is None — no rule evaluation
        path requires the DICOMSeries object.
        """
        images_dir = os.path.join(workdir_root, "images")
        working_path = os.path.join(workdir_root, "working.dcm")
        rtstruct = RTStructBuilder.create_from(
            dicom_series_path=images_dir,
            rt_struct_path=working_path,
        )
        image = sitk.ReadImage(os.path.join(workdir_root, "image.nii.gz"))
        engine = cls.__new__(cls)
        engine.rtstruct_path = working_path
        engine.rtstruct = rtstruct
        engine.image = image
        engine.series = None
        engine.available_masks = load_roi_masks(rtstruct, image)
        engine.summary = {
            "created_rois": [],
            "replaced_rois": [],
            "failed_rules": [],
        }
        return engine
```

c) Add `run_rule` after `_evaluate_cleanup_rule` (or anywhere among the rule methods):

```python
    def run_rule(self, rule: PipelineRule) -> str:
        """
        Evaluate a single rule and append its output to the in-memory RTStruct.

        Returns the (possibly dedup-suffixed) output ROI name. Does not save
        the RTStruct — persistence is the caller's job (see JobWorkdir).
        """
        self._validate_rule_inputs([rule])
        mask = self._evaluate_rule(rule)
        self.available_masks[rule.name] = mask
        return self._add_rule_output_to_rtstruct(rule, mask)
```

d) Refactor the `run_pipeline` loop body to call `run_rule` — replace the existing try-block:

```python
            try:
                output_name = self.run_rule(rule)
                if rule.output_action == "REPLACE_EXISTING":
                    self.summary["replaced_rois"].append(output_name)
                else:
                    self.summary["created_rois"].append(output_name)
            except Exception as e:
                logger.error(f"Rule {rule.order} ({rule.name}) failed: {e}")
                self.summary["failed_rules"].append(
                    {"order": rule.order, "name": rule.name, "error": str(e)}
                )
                raise
```

(Keep everything else in `run_pipeline` — `_validate_rule_inputs`, progress callback, `regenerate_instance_uids`, `save_rtstruct` — unchanged.)

- [ ] **Step 5: Run new tests + the full engine/e2e suites**

Run:
```bash
venv/bin/python manage.py test rule_based_segmentation.tests.test_end_to_end -v 2
venv/bin/python manage.py test rule_based_segmentation.tests.test_engine -v 2
venv/bin/python manage.py test rule_based_segmentation.tests.test_pipeline_e2e_physics -v 2
```
Expected: PASS — all pre-existing tests unmodified and green, plus the 4 new `EngineStepTests`.

- [ ] **Step 6: Commit**

```bash
git add rule_based_segmentation/utils/rtstruct_io.py rule_based_segmentation/utils/engine.py rule_based_segmentation/tests/test_end_to_end.py
git commit -m "refactor(rbs): add per-rule engine interface and persistent instances dir for chain execution"
```

---

### Task 4: Chain-step service functions in `job_service.py`

**Files:**
- Modify: `rule_based_segmentation/utils/job_service.py`

**Interfaces:**
- Consumes: `JobWorkdir`, `get_job_workdir_base` (Task 2), `load_rtstruct_and_image(..., instances_dir=...)`, `SegmentationEngine.from_workdir`, `SegmentationEngine.run_rule` (Task 3), `RuleStep` (Task 1), existing `get_rtstruct_path_and_series_uid`, `_backup_rtstruct`, `_sync_record_uids`, `_push_output_to_destination`, `_mark_rtstruct_as_rule_based`, `regenerate_instance_uids`, `save_rtstruct`.
- Produces (plain functions, no Celery — tested in-process):
  - `prepare_job(job: SegmentationJob) -> None` — resolves inputs, marks job `STARTED`, creates work dir + backup + instance copies + image cache + initial `working.dcm`, creates one PENDING `RuleStep` per rule. Every failure path marks the job `FAILED` (with `error_message`, `completed_at`) before re-raising.
  - `execute_rule_step(job: SegmentationJob, order: int) -> None` — claims the step (RUNNING) in a short transaction; no-op if the step is already `SUCCESS` (duplicate delivery); skips evaluation if the commit already applied (`rule_already_committed`); evaluates one rule; commits via `JobWorkdir.commit_rule_output`; on success marks step `SUCCESS` + `output_roi_name`; on failure marks step `FAILED`, job `FAILED`, and re-raises.
  - `finalize_job(job: SegmentationJob) -> dict` — idempotent (returns existing summary if job already `SUCCESS`); reloads the working state, regenerates instance UIDs, saves over the input RTStruct (in-place, same as legacy `run_job`), writes `result_summary` (built from step records), marks job `SUCCESS`, syncs record UIDs, marks the RTStruct rule-based, pushes to the destination node if configured, removes the work dir, returns the summary.
  - `resume_job(job: SegmentationJob) -> None` — re-enqueues the remaining chain steps (defined in `tasks.py` — this function lives in `tasks.py`, see Task 5; listed here for completeness of the state machine).
- Legacy `run_job(job)` is **removed** in Task 5 (after `tasks.py` no longer imports it).

- [ ] **Step 1: Write the failing tests**

Create `rule_based_segmentation/tests/test_pipeline_steps.py`:

```python
"""Tests for the chain-step service functions (prepare/execute/finalize)."""

import os
import shutil
import tempfile
from unittest import mock

import numpy as np
from django.test import TestCase
from django.utils import timezone

from spatial_overlap.models import RTStructureSetFile
from rt_utils import RTStructBuilder

from ..models import RuleStep, SegmentationJob
from ..utils import job_service
from ..utils.expression_evaluator import RuleEvaluationError
from ..utils.job_workdir import JobWorkdir
from ..utils.job_service import MissingImageSeriesError
from .helpers import (
    create_dicom_models,
    create_pipeline_with_rules,
    create_synthetic_ct_series,
    create_synthetic_rtstruct,
)

RULES = [
    {
        "rule_type": "MARGIN",
        "name": "PTV",
        "config": {
            "variant": "UNIFORM",
            "source": "Box",
            "margin_mm": 2.0,
            "kernel_type": "ball",
        },
    },
    {
        "rule_type": "BOOLEAN",
        "name": "Union",
        "config": {
            "operation": "UNION",
            "operands": [{"name": "Box"}, {"name": "PTV"}],
        },
    },
]


class StepTestBase(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="rbs_steps_")
        self.base_dir = os.path.join(self.temp_dir, "work")
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
        self.series = create_dicom_models(
            self.ct_files, self.series_uid, self.study_uid
        )
        self.mask_array = np.zeros((10, 64, 64), dtype=bool)
        self.mask_array[3:7, 28:36, 28:36] = True
        self.rtstruct_path = os.path.join(self.temp_dir, "test_rtstruct.dcm")
        create_synthetic_rtstruct(
            self.rtstruct_path,
            self.ct_files,
            roi_name="Box",
            mask_array=self.mask_array,
        )
        self.rt_record = RTStructureSetFile.objects.create(
            patient_name="Test^Patient",
            patient_id="TESTPATIENT",
            study_instance_uid=self.study_uid,
            series_instance_uid=self.series_uid,
            sop_instance_uid="9.9.9.1",
            structure_set_label="Test",
            referenced_series_instance_uid=self.series_uid,
            rtstructure_file_path=self.rtstruct_path,
            working_directory=self.temp_dir,
        )
        self.pipeline = create_pipeline_with_rules(
            name="Step Pipeline", rules_data=RULES
        )
        self._base_patch = mock.patch(
            "rule_based_segmentation.utils.job_service.get_job_workdir_base",
            return_value=self.base_dir,
        )
        self._base_patch.start()

    def tearDown(self):
        self._base_patch.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def make_job(self, pipeline=None):
        return SegmentationJob.objects.create(
            pipeline=pipeline or self.pipeline,
            input_type="UPLOAD",
            input_upload=self.rt_record,
            status="PENDING",
        )

    def wd(self, job):
        return JobWorkdir(job.id, base_dir=self.base_dir)

    def _working_rtstruct(self, job):
        wd = self.wd(job)
        return RTStructBuilder.create_from(
            dicom_series_path=wd.images_dir, rt_struct_path=wd.working_path
        )


class PrepareJobTests(StepTestBase):
    def test_prepare_creates_workdir_caches_and_steps(self):
        job = self.make_job()
        job_service.prepare_job(job)
        job.refresh_from_db()

        self.assertEqual(job.status, "STARTED")
        self.assertIsNotNone(job.started_at)
        self.assertEqual(job.dicom_series_id, self.series.id)
        self.assertTrue(os.path.exists(job.backup_file_path))

        wd = self.wd(job)
        self.assertEqual(len(os.listdir(wd.images_dir)), 10)
        self.assertTrue(os.path.exists(wd.image_cache_path))
        self.assertTrue(os.path.exists(wd.working_path))
        self.assertEqual(
            set(RuleStep.objects.filter(job=job).values_list("order", flat=True)),
            {1, 2},
        )
        self.assertTrue(all(s.status == "PENDING" for s in job.steps.all()))

    def test_prepare_missing_series_marks_job_failed(self):
        self.rt_record.referenced_series_instance_uid = "0.0.0.missing"
        self.rt_record.save()
        job = self.make_job()
        with self.assertRaises(MissingImageSeriesError):
            job_service.prepare_job(job)
        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")
        self.assertIn("not available", job.error_message)
        self.assertIsNotNone(job.completed_at)

    def test_prepare_missing_file_marks_job_failed(self):
        os.remove(self.rtstruct_path)
        job = self.make_job()
        with self.assertRaises(ValueError):
            job_service.prepare_job(job)
        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")
        self.assertIn("not found", job.error_message)


class ExecuteRuleStepTests(StepTestBase):
    def _prepared_job(self):
        job = self.make_job()
        job_service.prepare_job(job)
        return job

    def test_execute_two_steps_in_order(self):
        job = self._prepared_job()
        job_service.execute_rule_step(job, 1)
        job_service.execute_rule_step(job, 2)

        rtstruct = self._working_rtstruct(job)
        names = rtstruct.get_roi_names()
        self.assertIn("PTV", names)
        self.assertIn("Union", names)

        step1 = RuleStep.objects.get(job=job, order=1)
        self.assertEqual(step1.status, "SUCCESS")
        self.assertEqual(step1.output_roi_name, "PTV")
        self.assertIsNotNone(step1.started_at)
        self.assertIsNotNone(step1.completed_at)
        self.assertEqual(
            RuleStep.objects.filter(job=job, status="SUCCESS").count(), 2
        )

    def test_duplicate_delivery_is_noop(self):
        job = self._prepared_job()
        job_service.execute_rule_step(job, 1)
        job_service.execute_rule_step(job, 1)  # redelivery

        rtstruct = self._working_rtstruct(job)
        self.assertEqual(rtstruct.get_roi_names().count("PTV"), 1)
        step = RuleStep.objects.get(job=job, order=1)
        self.assertEqual(step.status, "SUCCESS")

    def test_failed_rule_marks_step_and_job_failed(self):
        bad_pipeline = create_pipeline_with_rules(
            name="Bad",
            rules_data=[
                {
                    "rule_type": "MARGIN",
                    "name": "Bad",
                    "config": {
                        "variant": "UNIFORM",
                        "source": "NoSuchStructure",
                        "margin_mm": 2.0,
                        "kernel_type": "ball",
                    },
                }
            ],
        )
        job = self.make_job(pipeline=bad_pipeline)
        job_service.prepare_job(job)
        with self.assertRaises(RuleEvaluationError):
            job_service.execute_rule_step(job, 1)

        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")
        self.assertIn("NoSuchStructure", job.error_message)
        step = RuleStep.objects.get(job=job, order=1)
        self.assertEqual(step.status, "FAILED")
        self.assertIn("NoSuchStructure", step.error)

    def test_redelivery_after_commit_before_step_update(self):
        """Worker died between the disk commit and the step UPDATE: redelivery
        must not duplicate the ROI."""
        job = self._prepared_job()
        job_service.execute_rule_step(job, 1)
        step = RuleStep.objects.get(job=job, order=1)
        step.status = "RUNNING"  # simulate the lost SUCCESS update
        step.save()

        job_service.execute_rule_step(job, 1)  # redelivery

        step.refresh_from_db()
        self.assertEqual(step.status, "SUCCESS")
        rtstruct = self._working_rtstruct(job)
        self.assertEqual(rtstruct.get_roi_names().count("PTV"), 1)


class FinalizeJobTests(StepTestBase):
    def _completed_job(self):
        job = self.make_job()
        job_service.prepare_job(job)
        job_service.execute_rule_step(job, 1)
        job_service.execute_rule_step(job, 2)
        return job

    def test_finalize_writes_output_and_marks_success(self):
        job = self._completed_job()
        with open(self.rtstruct_path, "rb") as fh:
            original_bytes = fh.read()

        summary = job_service.finalize_job(job)
        job.refresh_from_db()

        self.assertEqual(job.status, "SUCCESS")
        self.assertEqual(job.output_file_path, self.rtstruct_path)
        self.assertIsNone(job.error_message)
        with open(self.rtstruct_path, "rb") as fh:
            self.assertNotEqual(original_bytes, fh.read())
        self.assertEqual(summary["created_rois"], ["PTV", "Union"])
        self.assertTrue(job.result_summary["sop_instance_uid"])
        self.assertTrue(job.result_summary["series_instance_uid"])

        # input record UIDs were synced to the regenerated file
        self.rt_record.refresh_from_db()
        self.assertEqual(
            self.rt_record.sop_instance_uid,
            job.result_summary["sop_instance_uid"],
        )
        # work dir cleaned up on success
        self.assertFalse(self.wd(job).exists())

    def test_finalize_is_idempotent(self):
        job = self._completed_job()
        first = job_service.finalize_job(job)
        second = job_service.finalize_job(job)
        self.assertEqual(first, second)
        job.refresh_from_db()
        self.assertEqual(job.status, "SUCCESS")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/python manage.py test rule_based_segmentation.tests.test_pipeline_steps -v 2`
Expected: FAIL with `AttributeError: module 'rule_based_segmentation.utils.job_service' has no attribute 'prepare_job'`

- [ ] **Step 3: Implement the step functions**

In `rule_based_segmentation/utils/job_service.py`:

a) Extend the imports at the top (merge with the existing block; keep the existing `pydicom`, `shutil`, `timezone`, `MissingImageSeriesError`-related code intact):

```python
from django.db import transaction

from ..models import RuleStep, SegmentationJob, SegmentationPipeline
from .engine import SegmentationEngine
from .job_workdir import JobWorkdir, get_job_workdir_base
from .rtstruct_io import (
    _backup_rtstruct,
    load_rtstruct_and_image,
    regenerate_instance_uids,
    save_rtstruct,
)
```

(`SegmentationJob`, `SegmentationPipeline`, `SegmentationEngine`, `_backup_rtstruct` are already imported — merge rather than duplicate. `run_job` stays until Task 5, so keep everything it still uses.)

b) Add the following functions (place them where `run_job` currently is; `run_job` stays until Task 5):

```python
def _fail_job(job: SegmentationJob, message: str) -> None:
    """Mark a job FAILED with a reason; used by every chain-step failure path."""
    job.status = "FAILED"
    job.completed_at = timezone.now()
    job.error_message = message
    job.save()


def _job_input_rtstruct_path(job: SegmentationJob) -> str:
    """Filesystem path of the RTStruct this job processes (input file)."""
    if job.input_type == "UPLOAD" and job.input_upload:
        return job.input_upload.rtstructure_file_path
    if job.input_type == "IMPORT" and job.input_import:
        return (
            job.input_import.reidentified_rt_structure_file_path
            or job.input_import.deidentified_rt_structure_file_path
        )
    raise ValueError(f"Job {job.id} has no input")


def prepare_job(job: SegmentationJob) -> None:
    """
    Chain step 0 — resolve inputs, create the work dir, cache the series,
    seed one PENDING RuleStep per rule.

    Every failure path marks the job FAILED before re-raising, so a failed
    prepare never leaves the job stuck in PENDING.
    """
    try:
        rtstruct_path, series_uid = get_rtstruct_path_and_series_uid(job)
    except Exception as e:
        logger.error(f"Job {job.id} input resolution failed: {e}", exc_info=True)
        _fail_job(job, f"Could not resolve job inputs: {e}")
        raise

    job.status = "STARTED"
    job.started_at = timezone.now()
    job.dicom_series = DICOMSeries.objects.filter(
        series_instance_uid=series_uid
    ).first()
    job.save()

    wd = JobWorkdir(job.id, base_dir=get_job_workdir_base())
    try:
        wd.create()
        job.backup_file_path = _backup_rtstruct(rtstruct_path)
        job.save()
        rtstruct, image, _series = load_rtstruct_and_image(
            rtstruct_path, series_uid, instances_dir=wd.images_dir
        )
        wd.save_image_cache(image)
        wd.write_initial_working(rtstruct)
    except Exception as e:
        logger.error(f"Job {job.id} preparation failed: {e}", exc_info=True)
        _fail_job(job, f"Could not prepare job inputs: {e}")
        raise

    for rule in job.pipeline.rules.all().order_by("order"):
        RuleStep.objects.create(
            job=job, rule=rule, order=rule.order, status="PENDING"
        )
    logger.info(f"Job {job.id} prepared: {job.pipeline.rules.count()} steps queued")


def _claim_step(job: SegmentationJob, order: int) -> RuleStep:
    """Claim a step for execution (RUNNING) in a short transaction.

    Returns None if the step already completed (duplicate delivery).
    The transaction commits before evaluation starts so no row lock is held
    during the (potentially long) rule computation.
    """
    with transaction.atomic():
        step = RuleStep.objects.select_for_update().get(job=job, order=order)
        if step.status == "SUCCESS":
            return None
        step.status = "RUNNING"
        step.started_at = timezone.now()
        step.error = None
        step.save()
    return step


def execute_rule_step(job: SegmentationJob, order: int) -> None:
    """
    Chain step N — evaluate one rule and commit its output to the work dir.

    Idempotent under redelivery: SUCCESS steps are skipped; steps whose disk
    commit already applied (worker died before the step UPDATE) complete
    without re-adding the ROI.
    """
    step = _claim_step(job, order)
    if step is None:
        logger.info(f"Job {job.id} step {order} already completed; skipping")
        return

    wd = JobWorkdir(job.id, base_dir=get_job_workdir_base())
    rule = step.rule

    try:
        engine = SegmentationEngine.from_workdir(wd.root)
    except Exception as e:
        logger.error(f"Job {job.id} step {order} failed to reload state: {e}", exc_info=True)
        step.status = "FAILED"
        step.error = str(e)
        step.completed_at = timezone.now()
        step.save()
        _fail_job(job, f"Could not reload job state for step {order}: {e}")
        raise

    if wd.rule_already_committed(engine.rtstruct, order):
        # Commit already applied (crash between disk commit and step update).
        manifest = wd.read_step_manifest(order)
        step.status = "SUCCESS"
        step.output_roi_name = manifest.get("output_name") if manifest else None
        step.completed_at = timezone.now()
        step.save()
        return

    try:
        output_name = engine.run_rule(rule)
        wd.commit_rule_output(engine.rtstruct, order, output_name)
    except Exception as e:
        logger.error(f"Job {job.id} rule {order} ({rule.name}) failed: {e}", exc_info=True)
        step.status = "FAILED"
        step.error = str(e)
        step.completed_at = timezone.now()
        step.save()
        _fail_job(job, f"Rule '{rule.name}' (step {order}) failed: {e}")
        raise

    step.status = "SUCCESS"
    step.output_roi_name = output_name
    step.completed_at = timezone.now()
    step.save()
    logger.info(f"Job {job.id} step {order} ({rule.name}) committed as '{output_name}'")


def finalize_job(job: SegmentationJob) -> dict:
    """
    Chain final step — write the processed RTStruct, sync DB records, push to
    the destination node, mark the job SUCCESS, and clean up the work dir.

    Idempotent: a redelivered finalize on an already-SUCCESS job is a no-op.
    """
    if job.status == "SUCCESS":
        logger.warning(f"Job {job.id} finalize is a duplicate; skipping")
        return job.result_summary or {}

    rtstruct_path = _job_input_rtstruct_path(job)
    wd = JobWorkdir(job.id, base_dir=get_job_workdir_base())

    try:
        engine = SegmentationEngine.from_workdir(wd.root)
        new_sop_uid, new_series_uid = regenerate_instance_uids(engine.rtstruct)
        save_rtstruct(engine.rtstruct, rtstruct_path)
    except Exception as e:
        logger.error(f"Job {job.id} finalization failed: {e}", exc_info=True)
        _fail_job(job, f"Finalization failed: {e}")
        raise

    summary = {
        "created_rois": [
            s.output_roi_name
            for s in job.steps.filter(
                status="SUCCESS", rule__output_action="CREATE_NEW"
            ).order_by("order")
            if s.output_roi_name
        ],
        "replaced_rois": [
            s.output_roi_name
            for s in job.steps.filter(
                status="SUCCESS", rule__output_action="REPLACE_EXISTING"
            ).order_by("order")
            if s.output_roi_name
        ],
        # Same shape as the legacy engine summary; always [] on the success
        # path (a failed step marks the job FAILED before finalize runs).
        "failed_rules": [
            {"order": s.order, "name": s.rule.name, "error": s.error or ""}
            for s in job.steps.filter(status="FAILED").order_by("order")
        ],
        "sop_instance_uid": new_sop_uid,
        "series_instance_uid": new_series_uid,
    }

    job.status = "SUCCESS"
    job.completed_at = timezone.now()
    job.output_file_path = rtstruct_path
    job.result_summary = summary
    job.error_message = None
    job.save()

    # Same post-processing as the legacy single-task run.
    _sync_record_uids(job, rtstruct_path, summary)
    _mark_rtstruct_as_rule_based(job, rtstruct_path)
    _push_output_to_destination(job, rtstruct_path)
    wd.cleanup()

    logger.info(f"Segmentation job {job.id} completed successfully")
    return summary
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/python manage.py test rule_based_segmentation.tests.test_pipeline_steps -v 2`
Expected: PASS (9 tests). Also run `venv/bin/python manage.py test rule_based_segmentation -v 1` — all previously green tests still pass.

- [ ] **Step 5: Commit**

```bash
git add rule_based_segmentation/utils/job_service.py rule_based_segmentation/tests/test_pipeline_steps.py
git commit -m "feat(rbs): add prepare/execute/finalize chain-step service functions with crash-safe commits"
```

---

### Task 5: Rewrite `tasks.py` as the chain; swap call sites; remove legacy task

**Files:**
- Rewrite: `rule_based_segmentation/tasks.py`
- Modify: `rule_based_segmentation/utils/job_service.py` (`create_segmentation_job`; remove `run_job`)
- Modify: `rule_based_segmentation/views.py:484-486` (the `job_id` branch of `select_series_for_upload`)
- Rewrite: `rule_based_segmentation/tests/test_tasks.py`

**Interfaces:**
- Consumes: `job_service.prepare_job / execute_rule_step / finalize_job` (Task 4), `RuleStep` (Task 1).
- Produces (module-level, used by views/tests):
  - `build_job_chain(job: SegmentationJob)` → Celery chain `prepare_job.s(job_id), run_rule_step.s(<order>)... , finalize_job.s()` (only the head `prepare_job` stores `job_id`; rule steps + finalize receive it from the previous return value). Orders from `job.pipeline.rules.all().order_by("order")`; an empty pipeline yields `prepare → finalize`.
  - `resume_job(job: SegmentationJob) -> None` — no steps yet → enqueue `build_job_chain`; otherwise enqueue `run_rule_step` for every step whose status != SUCCESS (in order) followed by `finalize_job`; all via `.apply_async()`
  - task wrappers `prepare_job(job_id: str) -> str`, `run_rule_step(job_id: str, order: int) -> str`, `finalize_job(job_id: str) -> dict`, `reap_stuck_jobs() -> dict` (Task 7 adds the last)
  - time-limit constants `RULE_STEP_SOFT_TIME_LIMIT = 600`, `RULE_STEP_HARD_TIME_LIMIT = 900`, `PREPARE_SOFT_TIME_LIMIT = 900`, `PREPARE_HARD_TIME_LIMIT = 1200`, `FINALIZE_SOFT_TIME_LIMIT = 600`, `FINALIZE_HARD_TIME_LIMIT = 900`

Chain contract (CRITICAL — production incident 2026-11-22): Celery PREPENDS the previous task's return value to the next task's stored args (`celery/canvas.py` `Signature._merge`), it does NOT replace them. So only the chain head stores `job_id` explicitly; each subsequent task receives it as the injected first positional arg. Storing `job_id` on a non-head task causes `TypeError: takes N positional arguments but N+1 were given` and silently breaks the chain. `resume_job` is special: its first task is the head of a NEW chain (no preceding return value), so it stores `job_id` explicitly, and only that first task does.

- [ ] **Step 1: Rewrite `tasks.py`**

Replace the `run_segmentation_job` task (lines 1–41 of the current file) and its now-unused imports with the chain code below. **Keep verbatim** the existing `_wait_for` helper and `retrieve_rtstruct_for_pipeline` task (plus the `import time` / `from django.db import connections` imports they need) — they appear in the final file after the new chain code, unchanged. The final file content is the new code below followed by those kept sections:

```python
"""Celery tasks for rule-based segmentation (chain-based execution).

One job runs as a sequential chain:

    prepare_job -> run_rule_step(order=1..N) -> finalize_job

Every step reloads persisted state from the job work dir (see
utils/job_workdir.py), so a step that is redelivered after a worker crash
re-does at most one rule instead of the whole pipeline.

Chain arg contract (Celery 5): the previous task's return value is
PREPENDED to the next task's stored args (canvas.Signature._merge). Each
step therefore returns the job_id string, and only the chain HEAD carries
job_id explicitly — every non-head signature must NOT store job_id again,
or the injected value overflows the function's positional parameters
('takes N positional arguments but N+1 were given').
"""

import logging

from celery import chain, shared_task
from django.db import connections

from .models import SegmentationJob
from .utils import job_service

logger = logging.getLogger(__name__)

# Per-step time limits (seconds). Soft limit raises SoftTimeLimitExceeded,
# which the service layer turns into a clean step/job FAILED; the hard limit
# SIGKILLs the worker, and acks_late redelivers the step (idempotent by design).
RULE_STEP_SOFT_TIME_LIMIT = 600
RULE_STEP_HARD_TIME_LIMIT = 900
PREPARE_SOFT_TIME_LIMIT = 900
PREPARE_HARD_TIME_LIMIT = 1200
FINALIZE_SOFT_TIME_LIMIT = 600
FINALIZE_HARD_TIME_LIMIT = 900


def _get_job(job_id: str) -> SegmentationJob:
    try:
        return SegmentationJob.objects.get(id=job_id)
    except SegmentationJob.DoesNotExist:
        logger.error(f"SegmentationJob {job_id} not found")
        raise


def _close_db_connections() -> None:
    """Close real DB connections after a task (long-lived worker hygiene).

    Skipped while a connection is inside an atomic block — e.g. under Django
    test cases, where closing would poison the test transaction.
    """
    for alias in connections:
        conn = connections[alias]
        if conn.connection is not None and not conn.in_atomic_block:
            conn.close()


def build_job_chain(job: SegmentationJob):
    """Build the prepare -> rules -> finalize chain for a (new) job.

    Only prepare_job (the chain head) carries job_id explicitly; the rule
    steps and finalize receive it from the previous task's return value.
    """
    job_id = str(job.id)
    rule_sigs = [
        run_rule_step.s(rule.order)
        for rule in job.pipeline.rules.all().order_by("order")
    ]
    return chain(prepare_job.s(job_id), *rule_sigs, finalize_job.s())


def resume_job(job: SegmentationJob) -> None:
    """Re-enqueue the remaining chain steps for a job (retry after failure).

    Steps already SUCCESS are skipped; the remaining steps (in order) are
    enqueued, followed by finalize. A job that never reached prepare (no
    steps) gets the full chain. The first task of a resumed chain receives
    no injected return value, so it must carry job_id explicitly; later
    tasks receive it from the previous task's return value.
    """
    job_id = str(job.id)
    steps = list(job.steps.select_related("rule").order_by("order"))
    if not steps:
        build_job_chain(job).apply_async()
        return
    remaining = [s for s in steps if s.status != "SUCCESS"]
    if not remaining:
        # All rule steps committed; only finalization is left (idempotent).
        finalize_job.s(job_id).apply_async()
        return
    sigs = [run_rule_step.s(job_id, remaining[0].order)]
    sigs.extend(run_rule_step.s(s.order) for s in remaining[1:])
    chain(*sigs, finalize_job.s()).apply_async()


@shared_task(
    name="rule_based_segmentation.prepare_job",
    soft_time_limit=PREPARE_SOFT_TIME_LIMIT,
    time_limit=PREPARE_HARD_TIME_LIMIT,
)
def prepare_job(job_id: str) -> str:
    try:
        job = _get_job(job_id)
        job_service.prepare_job(job)
        return job_id
    finally:
        _close_db_connections()


@shared_task(
    name="rule_based_segmentation.run_rule_step",
    soft_time_limit=RULE_STEP_SOFT_TIME_LIMIT,
    time_limit=RULE_STEP_HARD_TIME_LIMIT,
)
def run_rule_step(job_id: str, order: int) -> str:
    try:
        job = _get_job(job_id)
        job_service.execute_rule_step(job, order)
        return job_id
    finally:
        _close_db_connections()


@shared_task(
    name="rule_based_segmentation.finalize_job",
    soft_time_limit=FINALIZE_SOFT_TIME_LIMIT,
    time_limit=FINALIZE_HARD_TIME_LIMIT,
)
def finalize_job(job_id: str) -> dict:
    try:
        job = _get_job(job_id)
        return job_service.finalize_job(job)
    finally:
        _close_db_connections()
```

- [ ] **Step 2: Swap the enqueue call site in `job_service.py`**

In `create_segmentation_job`, replace:

```python
    from ..tasks import run_segmentation_job
    ...
    run_segmentation_job.delay(str(job.id))
    return job
```

with:

```python
    from ..tasks import build_job_chain
    ...
    build_job_chain(job).apply_async()
    return job
```

and update the docstring's last line to: `"""Create a pending segmentation job and enqueue its execution chain."""`

- [ ] **Step 3: Remove legacy `run_job` from `job_service.py`**

First, re-point the one test that calls `run_job` — the physics mega-suite's driver. In `rule_based_segmentation/tests/test_pipeline_e2e_physics.py`, inside `_run_pipeline`, replace the single line

```python
        job_service.run_job(job)
```

with

```python
        job_service.prepare_job(job)
        for rule in job.pipeline.rules.order_by("order"):
            job_service.execute_rule_step(job, rule.order)
        job_service.finalize_job(job)
```

Also update the docstring/comment references to `run_job` in that file (module docstring, `_fresh_rt_path` docstring, `_run_pipeline` docstring, `test_mega_pipeline_runs_and_verifies_rtstruct` docstring) to say "the chain-step functions (prepare/execute/finalize)" instead of "run_job". **No assertions or test logic may change.**

Then delete the whole `def run_job(job: SegmentationJob) -> None:` function (it is now unused — verify with `rg "run_job\\(" rule_based_segmentation/ | grep -v tests | grep -v "_job"` after the edit; only `prepare_job`/`execute_rule_step`/`finalize_job` should remain).

- [ ] **Step 4: Swap the view call site**

In `rule_based_segmentation/views.py`, `select_series_for_upload`, replace:

```python
            if job_id:
                job = get_object_or_404(SegmentationJob, id=job_id)
                job.dicom_series = series
                job.save(update_fields=["dicom_series"])
                from .tasks import run_segmentation_job

                run_segmentation_job.delay(str(job.id))
                return redirect("rule_based_segmentation:job_detail", job_id=job.id)
```

with:

```python
            if job_id:
                job = get_object_or_404(SegmentationJob, id=job_id)
                job.dicom_series = series
                job.save(update_fields=["dicom_series"])
                from .tasks import resume_job

                resume_job(job)
                return redirect("rule_based_segmentation:job_detail", job_id=job.id)
```

- [ ] **Step 5: Rewrite `tests/test_tasks.py`**

Replace the entire content of `rule_based_segmentation/tests/test_tasks.py`:

```python
"""Tests for the Celery chain tasks (chain shape, wrappers, resume; reap tests land in Task 7)."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from ..models import RuleStep, SegmentationJob, SegmentationPipeline
from ..tasks import (
    build_job_chain,
    finalize_job,
    prepare_job,
    resume_job,
    run_rule_step,
)
from .helpers import create_pipeline_with_rules

User = get_user_model()

RULES = [
    {
        "rule_type": "MARGIN",
        "name": "PTV",
        "config": {"variant": "UNIFORM", "source": "Box", "margin_mm": 2.0},
    },
    {
        "rule_type": "CROP",
        "name": "Clipped",
        "config": {"source": "Box", "boundaries": ["Box"]},
    },
]


def make_job():
    user = User.objects.create_user(username="chainuser", password="x")
    pipeline = create_pipeline_with_rules(name="Chain", rules_data=RULES)
    return SegmentationJob.objects.create(
        pipeline=pipeline, input_type="UPLOAD", created_by=user, status="PENDING"
    )


class ChainShapeTests(TestCase):
    def test_chain_is_prepare_rules_finalize_in_order(self):
        job = make_job()
        sigs = build_job_chain(job).tasks  # Celery 5.6: constituents live in .tasks
        self.assertEqual(
            [s.name for s in sigs],
            [
                "rule_based_segmentation.prepare_job",
                "rule_based_segmentation.run_rule_step",
                "rule_based_segmentation.run_rule_step",
                "rule_based_segmentation.finalize_job",
            ],
        )
        rule_sigs = [s for s in sigs if s.name == "rule_based_segmentation.run_rule_step"]
        # job_id is NOT stored in non-head signatures: the previous task's
        # return value is prepended as the first positional argument.
        self.assertEqual([tuple(s.args) for s in rule_sigs], [(1,), (2,)])
        self.assertEqual(tuple(sigs[-1].args), ())

    def test_empty_pipeline_chain_is_prepare_finalize(self):
        user = User.objects.create_user(username="emptyuser", password="x")
        pipeline = SegmentationPipeline.objects.create(name="Empty")
        job = SegmentationJob.objects.create(
            pipeline=pipeline, input_type="UPLOAD", status="PENDING"
        )
        sigs = build_job_chain(job).tasks
        self.assertEqual(
            [s.name for s in sigs],
            [
                "rule_based_segmentation.prepare_job",
                "rule_based_segmentation.finalize_job",
            ],
        )


class TaskWrapperTests(TestCase):
    def test_missing_job_raises(self):
        with self.assertRaises(SegmentationJob.DoesNotExist):
            prepare_job("00000000-0000-0000-0000-000000000000")

    @patch("rule_based_segmentation.utils.job_service.prepare_job")
    def test_prepare_job_returns_job_id(self, mock_prep):
        job = make_job()
        self.assertEqual(prepare_job(str(job.id)), str(job.id))
        mock_prep.assert_called_once_with(job)

    @patch("rule_based_segmentation.utils.job_service.execute_rule_step")
    def test_run_rule_step_returns_job_id(self, mock_exec):
        job = make_job()
        self.assertEqual(run_rule_step(str(job.id), 1), str(job.id))
        mock_exec.assert_called_once_with(job, 1)

    @patch("rule_based_segmentation.utils.job_service.finalize_job")
    def test_finalize_job_returns_summary(self, mock_fin):
        mock_fin.return_value = {"created_rois": []}
        job = make_job()
        self.assertEqual(finalize_job(str(job.id)), {"created_rois": []})
        mock_fin.assert_called_once_with(job)


class ResumeJobTests(TestCase):
    def test_resume_enqueues_only_unfinished_steps(self):
        job = make_job()
        r1, r2 = list(job.pipeline.rules.all().order_by("order"))
        RuleStep.objects.create(
            job=job, rule=r1, order=1, status="SUCCESS", output_roi_name="PTV"
        )
        RuleStep.objects.create(job=job, rule=r2, order=2, status="FAILED", error="boom")

        with patch("rule_based_segmentation.tasks.chain") as mock_chain:
            mock_chain.return_value.apply_async = lambda: None
            resume_job(job)
        sigs = mock_chain.call_args[0]
        self.assertEqual(
            [s.name for s in sigs],
            [
                "rule_based_segmentation.run_rule_step",
                "rule_based_segmentation.finalize_job",
            ],
        )
        self.assertEqual(sigs[0].args, (str(job.id), 2))
        # the resumed head carries job_id explicitly; finalize receives it
        # from the previous task's return value
        self.assertEqual(tuple(sigs[1].args), ())

    def test_resume_without_steps_builds_full_chain(self):
        job = make_job()
        with patch("rule_based_segmentation.tasks.chain") as mock_chain:
            mock_chain.return_value.apply_async = lambda: None
            resume_job(job)
        sigs = mock_chain.call_args[0]
        self.assertEqual(len(sigs), 4)
        self.assertEqual(sigs[0].name, "rule_based_segmentation.prepare_job")
        self.assertEqual(tuple(sigs[1].args), (1,))
        self.assertEqual(tuple(sigs[3].args), ())

    def test_resume_all_steps_successful_enqueues_bare_finalize(self):
        job = make_job()
        r1, r2 = list(job.pipeline.rules.all().order_by("order"))
        RuleStep.objects.create(
            job=job, rule=r1, order=1, status="SUCCESS", output_roi_name="PTV"
        )
        RuleStep.objects.create(
            job=job, rule=r2, order=2, status="SUCCESS", output_roi_name="Clipped"
        )
        with patch("rule_based_segmentation.tasks.finalize_job") as mock_fin:
            mock_fin.s.return_value.apply_async = lambda *a, **k: None
            resume_job(job)
        mock_fin.s.assert_called_once_with(str(job.id))


class ChainDispatchTests(TestCase):
    """Reproduce Celery's real chain dispatch arg check.

    celery.app.trace._dispatch_callbacks_and_chain applies the next
    signature with the previous task's return value PREPENDED to that
    signature's stored args (canvas.Signature._merge). These tests push
    each chain signature through that exact code path against an in-memory
    broker (nothing reaches a real queue), so a signature that stores the
    injected job_id again fails with 'takes N positional arguments but
    N+1 were given' — the production chain-breaker of 2026-11-22.
    """

    _CELERY_CONF_KEYS = ("broker_url", "result_backend", "task_publish_retry")

    def _dispatch(self, sig, injected_args, remaining):
        from draw_client.celery import app as celery_app

        saved = {k: celery_app.conf.get(k) for k in self._CELERY_CONF_KEYS}
        celery_app.conf.update(
            broker_url="memory://",
            result_backend="disabled",
            task_publish_retry=False,
        )
        try:
            # Same call production makes
            # (celery/app/trace.py:_dispatch_callbacks_and_chain):
            # the previous task's return value is prepended to this
            # signature's stored args.
            sig.apply_async(injected_args, chain=remaining)
        finally:
            celery_app.conf.update(saved)

    def test_full_chain_dispatch_arg_counts(self):
        job = make_job()
        sigs = list(build_job_chain(job).tasks)
        job_id = str(job.id)
        for i, sig in enumerate(sigs):
            with self.subTest(i=i, task=sig.name):
                self._dispatch(sig, () if i == 0 else (job_id,), sigs[i + 1 :])

    def test_resume_chain_dispatch_arg_counts(self):
        job = make_job()
        r1, r2 = list(job.pipeline.rules.all().order_by("order"))
        RuleStep.objects.create(job=job, rule=r1, order=1, status="SUCCESS")
        RuleStep.objects.create(
            job=job, rule=r2, order=2, status="FAILED", error="boom"
        )
        captured = {}

        def capture(*sigs):
            captured["sigs"] = sigs
            raise _SkipApply  # the chain object is never used further

        with patch("rule_based_segmentation.tasks.chain", side_effect=capture):
            with self.assertRaises(_SkipApply):
                resume_job(job)
        sigs = captured["sigs"]
        job_id = str(job.id)
        for i, sig in enumerate(sigs):
            with self.subTest(i=i, task=sig.name):
                self._dispatch(sig, () if i == 0 else (job_id,), sigs[i + 1 :])


class _SkipApply(Exception):
    """Raised to skip the (irrelevant) chain.apply_async in capture tests."""
```

(`ReapStuckJobsTests` is added by Task 7, together with the task it tests.)

- [ ] **Step 6: Run the task tests**

Run: `venv/bin/python manage.py test rule_based_segmentation.tests.test_tasks -v 2`
Expected: PASS (chain shape, wrappers, and resume tests)

Also run the re-pointed physics mega-suite before committing: `venv/bin/python manage.py test rule_based_segmentation.tests.test_pipeline_e2e_physics` (≈165 s)
Expected: PASS — 15 tests, all assertions unchanged.

- [ ] **Step 7: Verify no legacy references remain**

Run:
```bash
rg "run_segmentation_job|run_job\(" rule_based_segmentation/ templates/ --type py
```
Expected: no matches (tests were rewritten in Step 5; `run_job` removed in Step 3).

- [ ] **Step 8: Commit**

```bash
git add rule_based_segmentation/tasks.py rule_based_segmentation/utils/job_service.py rule_based_segmentation/views.py rule_based_segmentation/tests/test_tasks.py
git commit -m "feat(rbs): execute pipelines as a celery chain (prepare -> per-rule steps -> finalize)"
```

---

### Task 6: Step progress in `job_status`, retry view, and status template

**Files:**
- Modify: `rule_based_segmentation/views.py` (`job_status`, new `job_retry`)
- Modify: `rule_based_segmentation/urls.py`
- Modify: `templates/rule_based_segmentation/job_status.html`
- Test: `rule_based_segmentation/tests/test_views.py`

**Interfaces:**
- Consumes: `RuleStep` (Task 1), `resume_job` (Task 5).
- Produces:
  - `GET jobs/<id>/status/` JSON now includes `current_step` (int|null) and `steps`: list of `{"order": int, "rule_name": str, "status": str, "error": str|null, "output_roi_name": str|null}`
  - `POST jobs/<id>/retry/` (`job_retry`) — 200 `{"ok": true}` after re-enqueueing; 409 `{"error": ...}` unless job status is `FAILED` or `PENDING`
  - URL name `rule_based_segmentation:job_retry`

- [ ] **Step 1: Write the failing tests**

Append to `rule_based_segmentation/tests/test_views.py` (that file already imports `PipelineRule`, `SegmentationPipeline`, `patch`, `reverse` — add `RuleStep` and `SegmentationJob` to the `from ..models import (...)` line):

```python
class JobStatusStepsTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        self.user = get_user_model().objects.create_user(username="steps_user", password="x")
        self.client.force_login(self.user)
        self.pipeline = SegmentationPipeline.objects.create(name="P")
        self.rule = PipelineRule.objects.create(
            pipeline=self.pipeline, order=1, rule_type="MARGIN", name="PTV"
        )
        self.job = SegmentationJob.objects.create(
            pipeline=self.pipeline, input_type="UPLOAD", status="STARTED",
            created_by=self.user,
        )
        RuleStep.objects.create(job=self.job, rule=self.rule, order=1, status="FAILED", error="boom")

    def test_job_status_includes_steps(self):
        resp = self.client.get(
            reverse("rule_based_segmentation:job_status", args=[self.job.id])
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data["steps"]), 1)
        self.assertEqual(data["steps"][0]["order"], 1)
        self.assertEqual(data["steps"][0]["rule_name"], "PTV")
        self.assertEqual(data["steps"][0]["status"], "FAILED")
        self.assertEqual(data["steps"][0]["error"], "boom")
        self.assertIsNone(data["current_step"])

    def test_job_status_current_step_when_running(self):
        RuleStep.objects.filter(job=self.job, order=1).update(status="RUNNING")
        data = self.client.get(
            reverse("rule_based_segmentation:job_status", args=[self.job.id])
        ).json()
        self.assertEqual(data["current_step"], 1)


class JobRetryTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        self.user = get_user_model().objects.create_user(username="retry_user", password="x")
        self.client.force_login(self.user)
        self.pipeline = SegmentationPipeline.objects.create(name="P")
        self.rule = PipelineRule.objects.create(
            pipeline=self.pipeline, order=1, rule_type="MARGIN", name="PTV"
        )
        self.job = SegmentationJob.objects.create(
            pipeline=self.pipeline, input_type="UPLOAD", status="FAILED",
            created_by=self.user,
        )
        RuleStep.objects.create(job=self.job, rule=self.rule, order=1, status="FAILED", error="boom")

    def test_retry_rejects_success_job(self):
        self.job.status = "SUCCESS"
        self.job.save()
        resp = self.client.post(
            reverse("rule_based_segmentation:job_retry", args=[self.job.id])
        )
        self.assertEqual(resp.status_code, 409)

    @patch("rule_based_segmentation.tasks.resume_job")
    def test_retry_failed_job_resumes(self, mock_resume):
        resp = self.client.post(
            reverse("rule_based_segmentation:job_retry", args=[self.job.id])
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"ok": True})
        mock_resume.assert_called_once_with(self.job)

    def test_retry_requires_post(self):
        resp = self.client.get(
            reverse("rule_based_segmentation:job_retry", args=[self.job.id])
        )
        self.assertEqual(resp.status_code, 405)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/python manage.py test rule_based_segmentation.tests.test_views.JobStatusStepsTests rule_based_segmentation.tests.test_views.JobRetryTests -v 2`
Expected: FAIL — `NoReverseMatch` for `job_retry`, and `steps` missing from the JSON payload

- [ ] **Step 3: Implement the view changes**

In `rule_based_segmentation/views.py`:

a) Replace the body of `job_status` with:

```python
@login_required
def job_status(request, job_id):
    """Return job status as JSON for polling (includes per-rule step progress)."""
    job = get_object_or_404(SegmentationJob, id=job_id)
    steps = job.steps.select_related("rule").all()
    running = next((s for s in steps if s.status == "RUNNING"), None)
    return JsonResponse(
        {
            "id": str(job.id),
            "status": job.status,
            "error": job.error_message,
            "summary": job.result_summary,
            "output_file_path": job.output_file_path,
            "backup_file_path": job.backup_file_path,
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            "current_step": running.order if running else None,
            "steps": [
                {
                    "order": s.order,
                    "rule_name": s.rule.name,
                    "status": s.status,
                    "error": s.error,
                    "output_roi_name": s.output_roi_name,
                }
                for s in steps
            ],
        }
    )
```

b) Add, next to `job_detail`:

```python
@login_required
@require_POST
def job_retry(request, job_id):
    """Re-enqueue the remaining chain steps of a failed (or stuck pending) job."""
    job = get_object_or_404(SegmentationJob, id=job_id)
    if job.status not in ("FAILED", "PENDING"):
        return JsonResponse(
            {"error": "Only failed or pending jobs can be retried."}, status=409
        )
    from .tasks import resume_job

    resume_job(job)
    return JsonResponse({"ok": True})
```

- [ ] **Step 4: Add the URL**

In `rule_based_segmentation/urls.py`, after the `jobs/<uuid:job_id>/download/` line:

```python
    path("jobs/<uuid:job_id>/retry/", views.job_retry, name="job_retry"),
```

- [ ] **Step 5: Update `job_status.html`**

In `templates/rule_based_segmentation/job_status.html`:

a) Replace the progress-container block's label line

```html
            <p class="text-sm text-gray-600 mb-2">Processing…</p>
```

with

```html
            <p id="progress-label" class="text-sm text-gray-600 mb-2">Waiting…</p>
```

b) After the `{% if job.error_message %}` block, add the steps list:

```html
        {% if job.steps.exists %}
        <div class="rounded-md border p-4">
            <h3 class="text-sm font-medium text-gray-700 mb-2">Steps</h3>
            <ul class="text-sm space-y-1">
                {% for step in job.steps.all %}
                <li>
                    {% if step.status == "SUCCESS" %}✅{% elif step.status == "FAILED" %}❌{% elif step.status == "RUNNING" %}⏳{% else %}•{% endif %}
                    {{ step.order }}. {{ step.rule.name }}
                    {% if step.output_roi_name %}<span class="text-gray-500">→ {{ step.output_roi_name }}</span>{% endif %}
                    {% if step.error %}<span class="text-red-600">— {{ step.error }}</span>{% endif %}
                </li>
                {% endfor %}
            </ul>
        </div>
        {% endif %}
```

c) In the button row (`<div class="flex space-x-3 pt-4">`), add before the "Back to Jobs" link:

```html
            {% if job.status == "FAILED" %}
            <form method="post" action="{% url 'rule_based_segmentation:job_retry' job.id %}">
                {% csrf_token %}
                <button type="submit" class="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-primary-600 hover:bg-primary-700">Retry from failed step</button>
            </form>
            {% endif %}
```

d) Replace the entire `{% block extra_js %}` script with:

```html
{% block extra_js %}
<script>
(function() {
    const statusUrl = "{% url 'rule_based_segmentation:job_status' job.id %}";
    const initialStatus = "{{ job.status }}";

    function updateProgress(data) {
        const steps = data.steps || [];
        const bar = document.getElementById("progress-bar");
        const label = document.getElementById("progress-label");
        if (bar && steps.length) {
            const done = steps.filter(s => s.status === "SUCCESS").length;
            bar.style.width = Math.round((done / steps.length) * 100) + "%";
        }
        if (label && steps.length) {
            const failed = steps.find(s => s.status === "FAILED");
            const running = steps.find(s => s.status === "RUNNING");
            if (failed) {
                label.textContent = "Failed at step " + failed.order + ": " + failed.rule_name;
            } else if (running) {
                label.textContent = "Processing step " + running.order + "/" + steps.length + ": " + running.rule_name;
            } else {
                label.textContent = "Finishing…";
            }
        }
    }

    if (initialStatus === "PENDING" || initialStatus === "STARTED") {
        const interval = setInterval(() => {
            fetch(statusUrl)
                .then(r => r.json())
                .then(data => {
                    updateProgress(data);
                    if (data.status === "SUCCESS" || data.status === "FAILED") {
                        clearInterval(interval);
                        location.reload();
                    }
                })
                .catch(err => console.error(err));
        }, 2000);
    }
})();
</script>
{% endblock %}
```

(The unused `jobId` const from the old script is intentionally dropped.)

- [ ] **Step 6: Run tests**

Run: `venv/bin/python manage.py test rule_based_segmentation.tests.test_views -v 2`
Expected: PASS (new tests + all pre-existing view tests)

- [ ] **Step 7: Commit**

```bash
git add rule_based_segmentation/views.py rule_based_segmentation/urls.py templates/rule_based_segmentation/job_status.html rule_based_segmentation/tests/test_views.py
git commit -m "feat(rbs): expose per-rule job progress and retry-from-failed-step"
```

---

### Task 7: `reap_stuck_jobs` safety-net beat task

**Files:**
- Modify: `rule_based_segmentation/tasks.py` (append)
- Modify: `draw_client/settings.py` (`CELERY_BEAT_SCHEDULE`)

**Interfaces:**
- Consumes: `RuleStep`, `SegmentationJob` (Tasks 1/5), `get_job_workdir_base` (Task 2).
- Produces:
  - module constants `REAP_RUNNING_GRACE_SECONDS = 1800`, `REAP_PENDING_GRACE_SECONDS = 600`, `JOB_WORKDIR_TTL_DAYS = 7`
  - task `reap_stuck_jobs() -> dict` with keys `reaped` (int) and `cleaned_workdirs` (int)

Behavior:
1. `RuleStep` RUNNING with `started_at` older than `REAP_RUNNING_GRACE_SECONDS` → step FAILED ("Step did not complete (worker lost or timed out)"); if its job is STARTED, job FAILED with `error_message` f"Step {order} did not complete (worker lost or timed out)".
2. Job PENDING, no steps, `created_at` older than `REAP_PENDING_GRACE_SECONDS` → job FAILED ("Job was not started (task lost or inputs unresolved)").
3. Work dir `{base}/{job_id}` for a FAILED job whose `completed_at` is ≥ `JOB_WORKDIR_TTL_DAYS` days old → `shutil.rmtree`.

- [ ] **Step 1: Add the task to `tasks.py`**

Append to `rule_based_segmentation/tasks.py`:

```python
import os
import shutil
from datetime import timedelta

from django.utils import timezone

from .utils import job_workdir

# Safety-net thresholds (seconds) for the periodic reap task.
REAP_RUNNING_GRACE_SECONDS = 1800
REAP_PENDING_GRACE_SECONDS = 600
JOB_WORKDIR_TTL_DAYS = 7


@shared_task(name="rule_based_segmentation.reap_stuck_jobs")
def reap_stuck_jobs() -> dict:
    """
    Safety net for lost messages / hard-timeout kills:

    - RUNNING steps older than the grace window -> FAILED (and job FAILED).
    - STARTED jobs older than the grace window whose steps never progressed
      (no RUNNING/SUCCESS step — the chain dispatch itself failed) -> FAILED.
    - PENDING jobs with no steps older than the grace window -> FAILED.
    - Work dirs of FAILED jobs older than JOB_WORKDIR_TTL_DAYS -> removed.
    """
    now = timezone.now()
    reaped = 0

    stuck_steps = RuleStep.objects.filter(
        status="RUNNING",
        started_at__lt=now - timedelta(seconds=REAP_RUNNING_GRACE_SECONDS),
    ).select_related("job")
    for step in stuck_steps:
        step.status = "FAILED"
        step.error = "Step did not complete (worker lost or timed out)"
        step.completed_at = now
        step.save()
        if step.job.status == "STARTED":
            step.job.status = "FAILED"
            step.job.error_message = (
                f"Step {step.order} did not complete (worker lost or timed out)"
            )
            step.job.completed_at = now
            step.job.save()
        reaped += 1
        logger.warning(f"Reaped stuck step {step.pk} (job {step.job_id})")

    # A STARTED job whose steps have never progressed (no RUNNING/SUCCESS
    # step) cannot move forward: the chain dispatch itself failed (e.g. a
    # message or argument error), so no worker can make progress. Mark it
    # FAILED so the operator can retry from the failed step.
    started_stuck = SegmentationJob.objects.filter(
        status="STARTED",
        started_at__lt=now - timedelta(seconds=REAP_RUNNING_GRACE_SECONDS),
    )
    for job in started_stuck:
        if job.steps.filter(status__in=["RUNNING", "SUCCESS"]).exists():
            continue  # in progress, or finalizing after the last commit
        job.status = "FAILED"
        job.error_message = "Job did not progress (chain dispatch lost or failed)"
        job.completed_at = now
        job.save()
        reaped += 1
        logger.warning(f"Reaped stuck started job {job.id}")

    stale_pending = SegmentationJob.objects.filter(
        status="PENDING",
        created_at__lt=now - timedelta(seconds=REAP_PENDING_GRACE_SECONDS),
    )
    for job in stale_pending:
        if job.steps.exists():
            continue
        job.status = "FAILED"
        job.error_message = "Job was not started (task lost or inputs unresolved)"
        job.completed_at = now
        job.save()
        reaped += 1
        logger.warning(f"Reaped stuck pending job {job.id}")

    cleaned = 0
    base = job_workdir.get_job_workdir_base()
    if os.path.isdir(base):
        for name in os.listdir(base):
            path = os.path.join(base, name)
            try:
                job = SegmentationJob.objects.get(id=name, status="FAILED")
            except SegmentationJob.DoesNotExist:
                continue
            if job.completed_at and (now - job.completed_at).days >= JOB_WORKDIR_TTL_DAYS:
                if os.path.isdir(path):
                    shutil.rmtree(path, ignore_errors=True)
                    cleaned += 1
                    logger.info(f"Removed stale work dir for job {name}")

    return {"reaped": reaped, "cleaned_workdirs": cleaned}
```

(Add `RuleStep` to the top-level `from .models import ...` line, and put `import os`, `import shutil`, `from datetime import timedelta`, `from django.utils import timezone`, `from .utils import job_workdir` at the top of the module with the other imports — the snippet shows the new code as an append for readability.)

- [ ] **Step 2: Add the reap tests**

Append to `rule_based_segmentation/tests/test_tasks.py` (and add `from datetime import timedelta`, `from django.utils import timezone`, `reap_stuck_jobs`, `REAP_PENDING_GRACE_SECONDS`, `REAP_RUNNING_GRACE_SECONDS` to that file's imports):

```python
class ReapStuckJobsTests(TestCase):
    def _job_with_running_step(self, age_seconds):
        user = User.objects.create_user(username="reapuser", password="x")
        pipeline = create_pipeline_with_rules(name="Reap", rules_data=RULES)
        job = SegmentationJob.objects.create(
            pipeline=pipeline, input_type="UPLOAD", status="STARTED", created_by=user
        )
        rule = job.pipeline.rules.first()
        RuleStep.objects.create(
            job=job,
            rule=rule,
            order=1,
            status="RUNNING",
            started_at=timezone.now() - timedelta(seconds=age_seconds),
        )
        return job

    def test_old_running_step_marks_step_and_job_failed(self):
        job = self._job_with_running_step(REAP_RUNNING_GRACE_SECONDS + 60)
        reap_stuck_jobs()
        step = RuleStep.objects.get(job=job, order=1)
        self.assertEqual(step.status, "FAILED")
        self.assertIn("did not complete", step.error)
        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")
        self.assertIn("Step 1", job.error_message)

    def test_recent_running_step_untouched(self):
        job = self._job_with_running_step(60)
        reap_stuck_jobs()
        self.assertEqual(RuleStep.objects.get(job=job, order=1).status, "RUNNING")
        job.refresh_from_db()
        self.assertEqual(job.status, "STARTED")

    def test_old_pending_job_without_steps_failed(self):
        user = User.objects.create_user(username="reapuser2", password="x")
        pipeline = SegmentationPipeline.objects.create(name="P")
        job = SegmentationJob.objects.create(
            pipeline=pipeline, input_type="UPLOAD", status="PENDING", created_by=user
        )
        # backdate created_at (auto_now_add can't be set at create time)
        SegmentationJob.objects.filter(id=job.id).update(
            created_at=timezone.now() - timedelta(seconds=REAP_PENDING_GRACE_SECONDS + 60)
        )
        reap_stuck_jobs()
        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")
        self.assertIn("not started", job.error_message)

    def test_old_started_job_with_only_pending_steps_failed(self):
        user = User.objects.create_user(username="reapuser5", password="x")
        pipeline = create_pipeline_with_rules(name="Reap5", rules_data=RULES)
        job = SegmentationJob.objects.create(
            pipeline=pipeline,
            input_type="UPLOAD",
            status="STARTED",
            created_by=user,
            started_at=timezone.now() - timedelta(seconds=REAP_RUNNING_GRACE_SECONDS + 60),
        )
        rule = job.pipeline.rules.first()
        RuleStep.objects.create(job=job, rule=rule, order=1, status="PENDING")
        reap_stuck_jobs()
        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")
        self.assertIn("did not progress", job.error_message)

    def test_started_job_with_successful_step_not_reaped(self):
        user = User.objects.create_user(username="reapuser6", password="x")
        pipeline = create_pipeline_with_rules(name="Reap6", rules_data=RULES)
        job = SegmentationJob.objects.create(
            pipeline=pipeline,
            input_type="UPLOAD",
            status="STARTED",
            created_by=user,
            started_at=timezone.now() - timedelta(seconds=REAP_RUNNING_GRACE_SECONDS + 60),
        )
        r1, r2 = list(job.pipeline.rules.all().order_by("order"))
        RuleStep.objects.create(job=job, rule=r1, order=1, status="SUCCESS")
        RuleStep.objects.create(
            job=job, rule=r2, order=2, status="RUNNING", started_at=timezone.now()
        )
        reap_stuck_jobs()
        job.refresh_from_db()
        self.assertEqual(job.status, "STARTED")

    def test_old_failed_job_workdir_removed(self):
        import os
        import tempfile

        base = tempfile.mkdtemp(prefix="rbs_reap_")
        user = User.objects.create_user(username="reapuser3", password="x")
        pipeline = create_pipeline_with_rules(name="Reap2", rules_data=RULES)
        job = SegmentationJob.objects.create(
            pipeline=pipeline,
            input_type="UPLOAD",
            status="FAILED",
            created_by=user,
            completed_at=timezone.now() - timedelta(days=8),
        )
        workdir = os.path.join(base, str(job.id))
        os.makedirs(workdir)
        with patch(
            "rule_based_segmentation.utils.job_workdir.get_job_workdir_base",
            return_value=base,
        ):
            result = reap_stuck_jobs()
        self.assertEqual(result["cleaned_workdirs"], 1)
        self.assertFalse(os.path.exists(workdir))
```

- [ ] **Step 3: Add the beat schedule entry**

In `draw_client/settings.py`, inside `CELERY_BEAT_SCHEDULE` (after the `'dicom-import'` entry, keeping the dict syntax):

```python
    'rbs-reap-stuck-jobs': {
        'task': 'rule_based_segmentation.reap_stuck_jobs',
        'schedule': crontab(minute='*/5'),  # every 5 minutes
        'options': {'expires': 60 * 4},
    },
```

- [ ] **Step 4: Run the full test_tasks module (now complete)**

Run: `venv/bin/python manage.py test rule_based_segmentation.tests.test_tasks -v 2`
Expected: PASS — including `ReapStuckJobsTests` (6 tests).

- [ ] **Step 5: Commit**

```bash
git add rule_based_segmentation/tasks.py rule_based_segmentation/tests/test_tasks.py draw_client/settings.py
git commit -m "feat(rbs): add periodic reap task for stuck chain steps and stale work dirs"
```

---

### Task 8: Full-suite verification and cleanup

**Files:** none new — verification only.

- [ ] **Step 1: Run the whole app test suite**

Run: `venv/bin/python manage.py test rule_based_segmentation -v 1`
Expected: PASS, 0 failures, 0 errors. Pre-existing suites (`test_engine`, `test_end_to_end` original tests, `test_pipeline_e2e_physics`, `test_models`, `test_intensity_segmentation`, `test_path_sanitization`) must be unmodified.

- [ ] **Step 2: Grep for leftover legacy references**

Run:
```bash
rg "run_segmentation_job" rule_based_segmentation/ templates/ --type py
rg "def run_job" rule_based_segmentation/ --type py
```
Expected: no matches.

- [ ] **Step 3: System check**

Run: `venv/bin/python manage.py check`
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 4: Final commit (if any drift was fixed)**

```bash
git status --short
# only commit if something changed:
git add -A && git commit -m "chore(rbs): chain-execution migration cleanup"
```

- [ ] **Step 5: Deployment notes (manual, do NOT commit)**

- Run `manage.py migrate` on the target environment (migration `0004_rulestep`).
- The Celery worker does not need new queue/routing config — tasks go to the default queue.
- If a job was `STARTED` under the old single-task code during the deploy window, its work dir does not exist; the new `run_rule_step` will fail to reload state and mark it FAILED — the operator can then hit "Retry from failed step" (which rebuilds from prepare when no steps exist).
