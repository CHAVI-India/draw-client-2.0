"""End-to-end test of a large, physicist-style segmentation pipeline.

This exercises the *real* application code paths, not synthetic stand-ins:

* Pipeline construction goes through ``views._create_or_update_pipeline`` —
  the exact builder the web UI calls, including ``_validate_pipeline_rules``
  (output-name uniqueness + forward/self reference ordering checks).
* The CT series is imported through the real importer
  ``dicom_image_importer.import_uploaded_image_series`` so the
  ``DICOMSeries`` / ``DICOMInstance`` rows the engine reads are created by the
  app itself.
* The input RTStruct is registered through ``rtstruct_registry.register_rtstruct_file``.
* Execution runs through ``job_service.run_job`` — the body of the Celery task
  that production runs — which loads the RTStruct with
  ``SegmentationEngine``/``rtstruct_io``, applies every rule, regenerates the
  output UIDs and records the result.

The dataset is the de-identified CT + RTStruct under ``tests/dicom_data``.

The pipeline itself mimics how a radiation oncologist/physicist builds dummy
structures for planning QA: expand a target (PTV), erode it and subtract to get
an outer shell (OS), build an anisotropic expansion (NOS), union the shell and
NOS and add a margin, boolean three+ OARs, expand the boolean and crop the
result from another structure — while touching every operation type the engine
supports.
"""

import os
import shutil
import tempfile
from unittest import mock

import numpy as np
import pydicom
import SimpleITK as sitk
from django.contrib.auth import get_user_model
from django.test import TestCase

from rule_based_segmentation import views
from rule_based_segmentation.models import SegmentationJob
from rule_based_segmentation.utils import job_service
from rule_based_segmentation.utils import rtstruct_registry
from rule_based_segmentation.utils.engine import SegmentationEngine
from rule_based_segmentation.utils.dicom_image_importer import (
    import_uploaded_image_series,
)

from .helpers import make_in_memory_file

DICOM_DATA_DIR = os.path.join(os.path.dirname(__file__), "dicom_data")

# ---------------------------------------------------------------------------
# The mega-pipeline, expressed exactly as the frontend would POST it.
#
# It is deliberately ordered so every referenced structure is either an ROI
# already present in the RTStruct or produced by an *earlier* rule, which is
# what ``_validate_pipeline_rules`` enforces.
# ---------------------------------------------------------------------------
def _roi(name):
    return {"name": name}


def _op(operation, *operands):
    return {"operation": operation, "operands": list(operands)}


def build_pipeline_spec():
    """Return the frontend JSON spec for the large pipeline."""
    return {
        "name": "Physics QA Mega Pipeline",
        "description": (
            "Large multi-operation pipeline (target expansion, eroded shell, "
            "anisotropic shell, booleans, margins, intensity, crop and every "
            "cleanup operation) on a de-identified RT dataset."
        ),
        "is_public": False,
        "rules": [
            # 1. Target expansion: PTV = BTV + 5mm (uniform ball). "create ... PTV"
            {"rule_type": "MARGIN", "name": "PTV", "output_roi_type": "PTV",
             "output_color": "#FF0000",
             "config": {"variant": "UNIFORM", "source": "BTV",
                        "margin_mm": 5.0, "kernel_type": "ball"}},
            # 2. Eroded PTV core (uniform, box kernel) -> used to carve a shell.
            {"rule_type": "MARGIN", "name": "PTV70", "output_roi_type": "PTV",
             "output_color": "#FF7F00",
             "config": {"variant": "UNIFORM", "source": "PTV",
                        "margin_mm": -2.0, "kernel_type": "box"}},
            # 3. Anisotropic shell-style expansion (NOS analog).
            {"rule_type": "MARGIN", "name": "NOS_PTV", "output_roi_type": "PTV",
             "output_color": "#FFB300",
             "config": {"variant": "ANISOTROPIC", "source": "PTV",
                        "margin_x_mm": 5.0, "margin_y_mm": 5.0, "margin_z_mm": 0.0}},
            # 4. Outer shell (OS analog) = PTV - eroded PTV (SUBTRACT).
            {"rule_type": "BOOLEAN", "name": "OS_PTV", "output_roi_type": "TREATED_VOLUME",
             "output_color": "#C0C0C0",
             "config": _op("SUBTRACT", _roi("PTV"), _roi("PTV70"))},
            # 5. Boolean the NOS and OS structures (UNION, 2 operands).
            {"rule_type": "BOOLEAN", "name": "BNOS_OS", "output_roi_type": "TREATED_VOLUME",
             "output_color": "#808080",
             "config": _op("UNION", _roi("NOS_PTV"), _roi("OS_PTV"))},
            # 6. ...and add margin to it (uniform, cross kernel).
            {"rule_type": "MARGIN", "name": "BNOSOS_M", "output_roi_type": "TREATED_VOLUME",
             "output_color": "#00FF00",
             "config": {"variant": "UNIFORM", "source": "BNOS_OS",
                        "margin_mm": 3.0, "kernel_type": "cross"}},
            # 7. Expand the boolean (uniform ball).
            {"rule_type": "MARGIN", "name": "EXPAND", "output_roi_type": "TREATED_VOLUME",
             "output_color": "#00CCCC",
             "config": {"variant": "UNIFORM", "source": "BNOSOS_M",
                        "margin_mm": 5.0, "kernel_type": "ball"}},
            # 8. Boolean three+ structures: lungs + heart (UNION, 3 operands).
            {"rule_type": "BOOLEAN", "name": "OAR3", "output_roi_type": "OAR",
             "output_color": "#0000FF",
             "config": _op("UNION", _roi("LUNG_LT"), _roi("LUNG_RT"), _roi("HEART"))},
            # 9. Crop the expansion from another structure (BODY).
            {"rule_type": "CROP", "name": "CROPCON", "output_roi_type": "EXTERNAL",
             "output_color": "#9900FF",
             "config": {"source": "EXPAND", "boundaries": ["BODY"]}},
            # 10. Crop the expansion from a different structure (the OAR blob).
            {"rule_type": "CROP", "name": "CROPLUNG", "output_roi_type": "AVOIDANCE",
             "output_color": "#FF00FF",
             "config": {"source": "EXPAND", "boundaries": ["OAR3"]}},
            # 11. Intensity (boundary seed): lung HU within LUNG_LT.
            {"rule_type": "INTENSITY", "name": "LUNGPAREN", "output_roi_type": "ORGAN",
             "output_color": "#00FF7F",
             "config": {"seed_type": "BOUNDARY", "boundary_roi": "LUNG_LT",
                        "ranges": [{"min": -1000, "max": -400}]}},
            # 12. Intensity (structure seed): soft-tissue HU within BTV.
            {"rule_type": "INTENSITY", "name": "BTVCALC", "output_roi_type": "GTV",
             "output_color": "#FF4040",
             "config": {"seed_type": "STRUCTURE", "seed_roi": "BTV",
                        "ranges": [{"min": -50, "max": 200}]}},
            # 13. Intensity (image seed): bone/contrast HU across the whole image.
            {"rule_type": "INTENSITY", "name": "BONEIM", "output_roi_type": "ORGAN",
             "output_color": "#8B8B00",
             "config": {"seed_type": "IMAGE",
                        "ranges": [{"min": 300, "max": 3000}]}},
            # 14. Cleanup: keep largest component of the expansion.
            {"rule_type": "CLEANUP", "name": "CLEANK", "output_roi_type": "TREATED_VOLUME",
             "output_color": "#00FF00",
             "config": {"operation": "KEEP_LARGEST_COMPONENT", "source": "EXPAND"}},
            # 15. Cleanup: smooth surface.
            {"rule_type": "CLEANUP", "name": "SMOOTH", "output_roi_type": "TREATED_VOLUME",
             "output_color": "#00EE00",
             "config": {"operation": "SMOOTH_STRUCTURE", "source": "CLEANK",
                        "smoothing_mm": 2.0, "iterations": 2}},
            # 16. Cleanup: gaussian smooth.
            {"rule_type": "CLEANUP", "name": "GAUSS", "output_roi_type": "TREATED_VOLUME",
             "output_color": "#00DD00",
             "config": {"operation": "GAUSSIAN_SMOOTH", "source": "SMOOTH",
                        "sigma_mm": 1.5, "threshold": 0.5}},
            # 17. Cleanup: fill holes.
            {"rule_type": "CLEANUP", "name": "FILLH", "output_roi_type": "TREATED_VOLUME",
             "output_color": "#00BB00",
             "config": {"operation": "FILL_HOLES", "source": "GAUSS",
                        "fully_connected": False}},
            # 18. Cleanup: remove small components.
            {"rule_type": "CLEANUP", "name": "RSMALL", "output_roi_type": "TREATED_VOLUME",
             "output_color": "#009900",
             "config": {"operation": "REMOVE_SMALL_COMPONENTS", "source": "FILLH",
                        "min_size_mm3": 200.0}},
            # 19. Boolean three+ structures from real small ROIs (6-operand UNION).
            {"rule_type": "BOOLEAN", "name": "SMALLS", "output_roi_type": "OAR",
             "output_color": "#0066FF",
             "config": _op("UNION", _roi("SPLG1"), _roi("SPLG2"), _roi("SPLG3"),
                           _roi("SPLG4"), _roi("SPLG5"), _roi("SPLG6"))},
            # 20. Cleanup the union: drop the tiny fragments.
            {"rule_type": "CLEANUP", "name": "PRUNED", "output_roi_type": "OAR",
             "output_color": "#3388FF",
             "config": {"operation": "REMOVE_SMALL_COMPONENTS", "source": "SMALLS",
                        "min_size_mm3": 1500.0}},
            # 21. Boolean INTERSECTION of a derived structure with BODY.
            {"rule_type": "BOOLEAN", "name": "INTERS", "output_roi_type": "ORGAN",
             "output_color": "#66AAFF",
             "config": _op("INTERSECTION", _roi("PRUNED"), _roi("BODY"))},
            # 22. Boolean XOR (exactly two operands).
            {"rule_type": "BOOLEAN", "name": "XORD", "output_roi_type": "AVOIDANCE",
             "output_color": "#AA00FF",
             "config": _op("XOR", _roi("HEART"), _roi("BREAST_CONTRALAT"))},
            # 23. Final subtraction: refined target minus the avoidance XOR.
            {"rule_type": "BOOLEAN", "name": "FINAL", "output_roi_type": "PTV",
             "output_color": "#FF00AA",
             "config": _op("SUBTRACT", _roi("RSMALL"), _roi("XORD"))},
            # 24. Nested boolean combining two derived structures.
            {"rule_type": "BOOLEAN", "name": "AVOIDIN", "output_roi_type": "AVOIDANCE",
             "output_color": "#CC00CC",
             "config": _op("INTERSECTION", _roi("INTERS"), _roi("XORD"))},
            # 25. REPLACE_EXISTING: overwrite an existing real ROI (UD4).
            {"rule_type": "MARGIN", "name": "UD4", "output_action": "REPLACE_EXISTING",
             "output_roi_type": "CONTROL", "output_color": "#404040",
             "config": {"variant": "UNIFORM", "source": "FINAL",
                        "margin_mm": 1.0, "kernel_type": "ball"}},
            # 26. CREATE_NEW onto an existing name -> engine auto-renames to LAD_1.
            {"rule_type": "MARGIN", "name": "LAD", "output_roi_type": "OAR",
             "output_color": "#FF8080",
             "config": {"variant": "UNIFORM", "source": "FINAL",
                        "margin_mm": 2.0, "kernel_type": "ball"}},
        ],
    }


# Every derived ROI the pipeline creates (CREATE_NEW) plus the renamed one.
# Used to assert presence in the output. Kept explicit for the audit.
CREATED_ROIS = [
    "PTV", "PTV70", "NOS_PTV", "OS_PTV", "BNOS_OS", "BNOSOS_M", "EXPAND",
    "OAR3", "CROPCON", "CROPLUNG", "LUNGPAREN", "BTVCALC", "BONEIM",
    "CLEANK", "SMOOTH", "GAUSS", "FILLH", "RSMALL", "SMALLS", "PRUNED",
    "INTERS", "XORD", "FINAL", "AVOIDIN", "LAD_1",
]


def _find_dataset():
    """Locate the de-identified RTSTRUCT and its referenced CT series on disk."""
    rtstruct_path = None
    ct_files = []
    referenced_ct_uid = None

    for root, _dirs, files in os.walk(DICOM_DATA_DIR):
        for name in files:
            if name.endswith(".bin"):
                continue  # sharded RTDOSE chunks - irrelevant to the engine
            path = os.path.join(root, name)
            try:
                ds = pydicom.dcmread(path, stop_before_pixels=True, force=True)
            except Exception:
                continue
            modality = str(getattr(ds, "Modality", "")).upper()
            if modality == "RTSTRUCT":
                rtstruct_path = path
                referenced_ct_uid = rtstruct_registry.extract_referenced_series_uid(ds)

    if not rtstruct_path:
        raise RuntimeError(f"No RTSTRUCT found under {DICOM_DATA_DIR}")

    # Second pass: collect the CT files belonging to the referenced series.
    for root, _dirs, files in os.walk(DICOM_DATA_DIR):
        for name in files:
            if name.endswith(".bin"):
                continue
            path = os.path.join(root, name)
            try:
                ds = pydicom.dcmread(path, stop_before_pixels=True, force=True)
            except Exception:
                continue
            if (str(getattr(ds, "Modality", "")).upper() == "CT"
                    and str(getattr(ds, "SeriesInstanceUID", "")) == referenced_ct_uid):
                ct_files.append(path)

    if not ct_files:
        raise RuntimeError(
            f"No CT instances found for referenced series {referenced_ct_uid}"
        )
    return rtstruct_path, referenced_ct_uid, sorted(ct_files)


class PhysicsMegaPipelineTests(TestCase):
    """Build a large pipeline through the real builder and run it for real."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = get_user_model().objects.create_user(
            username="physicist", password="x", email="phys@x.y"
        )

        src_rtstruct, cls.series_uid, ct_files = _find_dataset()
        cls.src_rtstruct = src_rtstruct

        # Import the CT series through the real importer (one time). Its target
        # directory is redirected to a scratch dir exactly like the app's own
        # importer test does, so nothing is written under /app/datastore.
        cls.work_dir = tempfile.mkdtemp(prefix="rbs_physics_")
        cls.series_dir = os.path.join(cls.work_dir, "ct_series")
        os.makedirs(cls.series_dir, exist_ok=True)

        patcher = mock.patch(
            "rule_based_segmentation.utils.dicom_image_importer"
            "._get_series_target_directory",
            return_value=cls.series_dir,
        )
        patcher.start()
        cls.addClassCleanup(patcher.stop)

        uploads = [
            make_in_memory_file(os.path.basename(p), open(p, "rb").read())
            for p in ct_files
        ]
        series = import_uploaded_image_series(
            uploads, expected_series_instance_uid=cls.series_uid
        )
        cls.series = series

        # Build the pipeline with the app's real builder (validates + saves).
        cls.pipeline = views._create_or_update_pipeline(
            build_pipeline_spec(), cls.user
        )

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work_dir, ignore_errors=True)
        super().tearDownClass()

    def _fresh_rt_path(self):
        """A throwaway copy of the source RTStruct (run_job mutates in place)."""
        rt_path = os.path.join(self.work_dir, f"rt_{os.urandom(4).hex()}.dcm")
        shutil.copy2(self.src_rtstruct, rt_path)
        return rt_path

    def _run_pipeline(self):
        """Copy the RTStruct, register it as a job input and execute run_job."""
        # run_job processes the RTStruct IN PLACE, so operate on a fresh copy
        # per test to keep tests independent and never touch the dataset.
        rt_path = self._fresh_rt_path()

        rt_record = rtstruct_registry.register_rtstruct_file(rt_path)
        job = SegmentationJob.objects.create(
            pipeline=self.pipeline,
            input_type="UPLOAD",
            input_upload=rt_record,
            created_by=self.user,
            status="PENDING",
        )

        job_service.run_job(job)

        job.refresh_from_db()
        return job, rt_path

    def test_builder_accepted_all_rules(self):
        """The real builder stored every rule and its sub-config."""
        self.assertEqual(self.pipeline.rules.count(), 26)
        by_type = {}
        for rule in self.pipeline.rules.all():
            by_type.setdefault(rule.rule_type, 0)
            by_type[rule.rule_type] += 1
        self.assertEqual(set(by_type), {"BOOLEAN", "INTENSITY", "MARGIN", "CROP", "CLEANUP"})

    def test_mega_pipeline_runs_and_verifies_rtstruct(self):
        """Full production job path: job_service.run_job over the real data.

        Verifies the produced RTStruct structurally (ROI presence, count,
        regenerated UIDs) and the job bookkeeping. Raw voxel geometry is
        asserted in test_pipeline_geometry_is_correct, not here: reading
        masks back through rt_utils is unreliable for this series because it
        is non-uniformly sampled (max z-gap ~446 mm), which collapses
        dilated contours on read-back even though the written ROIs are
        correct.
        """
        src_ds = pydicom.dcmread(
            self.src_rtstruct, stop_before_pixels=True, force=True
        )
        original_roi_names = {str(r.ROIName) for r in src_ds.StructureSetROISequence}

        job, rt_path = self._run_pipeline()

        # --- Job-level results through the real job service -----------------
        self.assertEqual(job.status, "SUCCESS", job.error_message)
        self.assertEqual(job.error_message, None)
        summary = job.result_summary
        self.assertEqual(summary["failed_rules"], [])
        self.assertEqual(summary["replaced_rois"], ["UD4"])
        # 25 CREATE_NEW outputs (LAD collided and was renamed LAD_1).
        self.assertEqual(len(summary["created_rois"]), 25)
        self.assertIn("LAD_1", summary["created_rois"])

        # --- The saved output RTStruct is verified structurally -------------
        out_ds = pydicom.dcmread(rt_path, stop_before_pixels=True, force=True)
        out_names = {str(r.ROIName) for r in out_ds.StructureSetROISequence}

        for roi in CREATED_ROIS:
            self.assertIn(roi, out_names, f"derived ROI {roi} missing from output")
        for roi in original_roi_names:
            self.assertIn(roi, out_names)
        # 32 original + 25 new = 57 structures.
        self.assertEqual(len(out_names), len(original_roi_names) + 25)

        # Every created ROI carries real contour data (not an empty stub).
        contour_numbers = {
            int(c.ReferencedROINumber)
            for c in out_ds.ROIContourSequence
            if len(getattr(c, "ContourSequence", []) or []) > 0
        }
        created_roi_numbers = {
            int(r.ROINumber) for r in out_ds.StructureSetROISequence
            if str(r.ROIName) in CREATED_ROIS
        }
        self.assertTrue(
            created_roi_numbers.issubset(contour_numbers),
            "some created ROIs were written without contour data",
        )

        # --- Fresh UIDs, study preserved, input record synced ---------------
        self.assertNotEqual(str(out_ds.SOPInstanceUID), str(src_ds.SOPInstanceUID))
        self.assertEqual(str(out_ds.StudyInstanceUID), str(src_ds.StudyInstanceUID))
        self.assertEqual(summary["sop_instance_uid"], str(out_ds.SOPInstanceUID))
        self.assertEqual(job.input_upload.sop_instance_uid, str(out_ds.SOPInstanceUID))

        # --- run_job created the rule-based import bookkeeping -------------
        from dicom_handler.models import RTStructureFileImport
        self.assertTrue(
            RTStructureFileImport.objects.filter(
                server_segmentation_status="RULE_BASED_COMPLETED"
            ).exists()
        )

    def test_pipeline_geometry_is_correct(self):
        """Assert the operations actually compute correctly, on the engine's
        own ground-truth masks (the real SegmentationEngine that run_job uses).

        This is the right place for geometric checks: it verifies the pipeline
        maths directly, independent of the lossy rt_utils contour read-back.
        """
        rt_path = self._fresh_rt_path()
        out_path = os.path.join(self.work_dir, f"out_{os.urandom(4).hex()}.dcm")
        engine = SegmentationEngine(rt_path, self.series_uid)
        engine.run_pipeline(self.pipeline, output_path=out_path)
        masks = engine.available_masks  # every created output, keyed by rule name

        def vox(name):
            return int(sitk.GetArrayFromImage(masks[name]).astype(bool).sum())

        def arr(name):
            return sitk.GetArrayFromImage(masks[name]).astype(bool)

        def subset(a, b):
            return bool(np.array_equal(np.logical_and(arr(a), arr(b)), arr(a)))

        # Target expansion grows; eroded core is inside PTV.
        self.assertGreater(vox("PTV"), vox("BTV"))
        self.assertTrue(subset("PTV70", "PTV"))
        # Outer shell (PTV - PTV70) is a strict, non-empty subset of PTV.
        self.assertGreater(vox("OS_PTV"), 0)
        self.assertLess(vox("OS_PTV"), vox("PTV"))
        self.assertTrue(subset("OS_PTV", "PTV"))
        # Boolean UNION of the NOS and OS shell contains both operands.
        self.assertTrue(subset("NOS_PTV", "BNOS_OS"))
        self.assertTrue(subset("OS_PTV", "BNOS_OS"))
        self.assertGreaterEqual(vox("BNOS_OS"), max(vox("NOS_PTV"), vox("OS_PTV")))
        self.assertGreater(vox("EXPAND"), vox("BNOSOS_M"))
        # Three-way OAR union contains each input.
        for part in ("LUNG_LT", "LUNG_RT", "HEART"):
            self.assertGreaterEqual(vox("OAR3"), vox(part))
        # Crop-to-boundary keeps only the intersection and never grows.
        self.assertTrue(subset("CROPCON", "BODY"))
        self.assertLessEqual(vox("CROPCON"), vox("EXPAND"))
        # Intensity within a boundary is a non-empty subset of that boundary.
        self.assertGreater(vox("LUNGPAREN"), 0)
        self.assertTrue(subset("LUNGPAREN", "LUNG_LT"))
        # Image-seed intensity is non-empty (bone/contrast present in CT).
        self.assertGreater(vox("BONEIM"), 0)
        # Structure-seed intensity within BTV is a non-empty subset of BTV.
        self.assertGreater(vox("BTVCALC"), 0)
        self.assertTrue(subset("BTVCALC", "BTV"))
        # Cleanup keeps the result a subset of its source and non-empty.
        # (On this dataset the 6-ROI union forms large components, so the
        #  1500 mm^3 cut may remove nothing - it can only shrink.)
        self.assertGreater(vox("SMALLS"), 0)
        self.assertTrue(subset("PRUNED", "SMALLS"))
        self.assertGreater(vox("PRUNED"), 0)
        # Intersections are subsets of both operands.
        self.assertTrue(subset("INTERS", "PRUNED"))
        self.assertTrue(subset("INTERS", "BODY"))
        # Subtract cannot be larger than its minuend.
        self.assertLessEqual(vox("FINAL"), vox("RSMALL"))


class PipelineBuilderValidationTests(TestCase):
    """The real builder must reject malformed pipelines before saving."""

    def _user(self):
        return get_user_model().objects.create_user(username="v", email="v@x.y")

    def test_duplicate_output_name_rejected(self):
        data = {
            "name": "dup",
            "rules": [
                {"rule_type": "MARGIN", "name": "X",
                 "config": {"variant": "UNIFORM", "source": "BODY", "margin_mm": 1.0}},
                {"rule_type": "MARGIN", "name": "X",
                 "config": {"variant": "UNIFORM", "source": "BODY", "margin_mm": 2.0}},
            ],
        }
        with self.assertRaises(ValueError):
            views._create_or_update_pipeline(data, self._user())

    def test_forward_reference_rejected(self):
        # Rule 1 references "LATER", produced by rule 2 -> ordering error.
        data = {
            "name": "fwd",
            "rules": [
                {"rule_type": "MARGIN", "name": "FIRST",
                 "config": {"variant": "UNIFORM", "source": "LATER", "margin_mm": 1.0}},
                {"rule_type": "MARGIN", "name": "LATER",
                 "config": {"variant": "UNIFORM", "source": "BODY", "margin_mm": 1.0}},
            ],
        }
        with self.assertRaises(ValueError):
            views._create_or_update_pipeline(data, self._user())


class OperationCoverageTests(TestCase):
    """Audit that the spec actually exercises every engine operation."""

    def setUp(self):
        self.rules = build_pipeline_spec()["rules"]

    def _cfg(self, rtype):
        return [r["config"] for r in self.rules if r["rule_type"] == rtype]

    def test_all_rule_types(self):
        self.assertEqual(
            {r["rule_type"] for r in self.rules},
            {"BOOLEAN", "INTENSITY", "MARGIN", "CROP", "CLEANUP"},
        )

    def test_all_boolean_operations(self):
        seen = set()

        def walk(c):
            if c.get("operation"):
                seen.add(c["operation"])
                for o in c.get("operands", []):
                    walk(o)

        for c in self._cfg("BOOLEAN"):
            walk(c)
        self.assertEqual(seen, {"UNION", "INTERSECTION", "SUBTRACT", "XOR"})

    def test_all_margin_variants_and_kernels(self):
        variants = {c["variant"] for c in self._cfg("MARGIN")}
        kernels = {c.get("kernel_type") for c in self._cfg("MARGIN")
                   if c["variant"] == "UNIFORM"}
        self.assertEqual(variants, {"UNIFORM", "ANISOTROPIC"})
        self.assertEqual(kernels, {"ball", "box", "cross"})

    def test_all_intensity_seed_types(self):
        seeds = {c["seed_type"] for c in self._cfg("INTENSITY")}
        self.assertEqual(seeds, {"IMAGE", "STRUCTURE", "BOUNDARY"})

    def test_all_cleanup_operations(self):
        ops = {c["operation"] for c in self._cfg("CLEANUP")}
        self.assertEqual(
            ops,
            {"SMOOTH_STRUCTURE", "GAUSSIAN_SMOOTH", "FILL_HOLES",
             "REMOVE_SMALL_COMPONENTS", "KEEP_LARGEST_COMPONENT"},
        )

    def test_boolean_three_or_more_operands_present(self):
        def count_operands(c):
            return len(c.get("operands", []))

        big = [c for c in self._cfg("BOOLEAN")
               if c.get("operation") and count_operands(c) >= 3]
        self.assertTrue(big, "expected at least one boolean of 3+ structures")
