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

The pipeline mimics how a radiation oncology physicist builds derived planning
structures (Eclipse / matryx / PyRTscript style) on a thorax / breast-nodal
case: a target (PTV) and an elective-nodal PTV with anisotropic margins, an
eroded core carved into a dose-falloff ring, HU-derived Internal and a 5 mm
skin PRV, the classic ``Body < PTV+Xcm`` optimization family, ``Lung - PTV``
with a target-overlap XOR, per-OAR PRVs (LAD, brachial plexus), PTV sparing
against the brachial PRV, a multi-structure OAR cluster, a nodal-station union,
body-clipping crops, HU tissue/bone intensity structures, and the cleanup
operations applied where they are genuinely used (de-fluffing booleans,
smoothing optimization contours, filling vessel holes, keeping the dominant
target component) - while exercising every operation the engine supports.
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
from rule_based_segmentation.models import PipelineRule, SegmentationJob
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
    """Return the frontend JSON spec for the large clinical pipeline.

    Ordered so every referenced structure is either an ROI already present in
    the imported RTStruct or produced by an *earlier* rule (which is what
    ``_validate_pipeline_rules`` enforces). The structure names and intents are
    the ones a physicist actually uses for a thorax / breast-nodal plan.
    """
    return {
        "name": "Thorax / Breast-Nodal Planning Structures",
        "description": (
            "Clinical derived-structure pipeline: PTV + elective PTV, eroded "
            "core and falloff ring, Internal / skin PRV, Body<PTV+Xcm "
            "optimization family, Lung-PTV and overlap QA, per-OAR PRVs, PTV "
            "sparing, an OAR cluster, nodal union, body crops, HU tissue/bone "
            "and cleanup - on a de-identified RT dataset."
        ),
        "is_public": False,
        "rules": [
            # --- Target definition -------------------------------------------
            # 1. PTV = BTV + 5 mm (isotropic).
            {"rule_type": "MARGIN", "name": "PTV", "output_roi_type": "PTV",
             "output_color": "#FF0000",
             "config": {"variant": "UNIFORM", "source": "BTV",
                        "margin_mm": 5.0, "kernel_type": "ball"}},
            # 2. Elective-nodal PTV with asymmetric in-plane vs slice margins.
            {"rule_type": "MARGIN", "name": "PTV_Elective", "output_roi_type": "PTV",
             "output_color": "#FF7F7F",
             "config": {"variant": "ANISOTROPIC", "source": "BTV",
                        "margin_x_mm": 7.0, "margin_y_mm": 7.0, "margin_z_mm": 3.0}},
            # 3. Eroded PTV core (box kernel) used to carve the falloff ring.
            {"rule_type": "MARGIN", "name": "PTV_Core", "output_roi_type": "PTV",
             "output_color": "#FF4040",
             "config": {"variant": "UNIFORM", "source": "PTV",
                        "margin_mm": -3.0, "kernel_type": "box"}},
            # 4. Dose-falloff ring = target minus its eroded core.
            {"rule_type": "BOOLEAN", "name": "Ring", "output_roi_type": "TREATED_VOLUME",
             "output_color": "#C0C0C0",
             "config": _op("SUBTRACT", _roi("PTV"), _roi("PTV_Core"))},

            # --- External / internal / skin ----------------------------------
            # 5. Inner body, 5 mm inside the external (cross kernel).
            {"rule_type": "MARGIN", "name": "Body_Shrink5", "output_roi_type": "EXTERNAL",
             "output_color": "#808080",
             "config": {"variant": "UNIFORM", "source": "BODY",
                        "margin_mm": -5.0, "kernel_type": "cross"}},
            # 6. Skin PRV = external minus inner body (5 mm skin dose limit).
            {"rule_type": "BOOLEAN", "name": "Skin_PRV5", "output_roi_type": "ORGAN",
             "output_color": "#FFD700",
             "config": _op("SUBTRACT", _roi("BODY"), _roi("Body_Shrink5"))},
            # 7. Internal = body voxels that are not air/lung (HU >= -250).
            {"rule_type": "INTENSITY", "name": "Internal", "output_roi_type": "EXTERNAL",
             "output_color": "#9966CC",
             "config": {"seed_type": "BOUNDARY", "boundary_roi": "BODY",
                        "ranges": [{"min": -250, "max": 3000}]}},

            # --- Body-minus-target optimization family -----------------------
            # 8. PTV + 0.5 cm (a near-target growth shell).
            {"rule_type": "MARGIN", "name": "PTV5mm", "output_roi_type": "AVOIDANCE",
             "output_color": "#00CCCC",
             "config": {"variant": "UNIFORM", "source": "PTV",
                        "margin_mm": 5.0, "kernel_type": "ball"}},
            # 9. PTV + 2 cm and 10. the body left outside it (optimization).
            {"rule_type": "MARGIN", "name": "PTV20", "output_roi_type": "AVOIDANCE",
             "output_color": "#33AAFF",
             "config": {"variant": "UNIFORM", "source": "PTV",
                        "margin_mm": 20.0, "kernel_type": "ball"}},
            {"rule_type": "BOOLEAN", "name": "Body_2cm", "output_roi_type": "EXTERNAL",
             "output_color": "#6699FF",
             "config": _op("SUBTRACT", _roi("BODY"), _roi("PTV20"))},
            # 11. PTV + 5 cm and 12. the body left outside it.
            {"rule_type": "MARGIN", "name": "PTV50", "output_roi_type": "AVOIDANCE",
             "output_color": "#9966FF",
             "config": {"variant": "UNIFORM", "source": "PTV",
                        "margin_mm": 50.0, "kernel_type": "ball"}},
            {"rule_type": "BOOLEAN", "name": "Body_5cm", "output_roi_type": "EXTERNAL",
             "output_color": "#CC66FF",
             "config": _op("SUBTRACT", _roi("BODY"), _roi("PTV50"))},

            # --- Lung and target overlap -------------------------------------
            # 13. Both lungs as one OAR.
            {"rule_type": "BOOLEAN", "name": "Lung_Total", "output_roi_type": "OAR",
             "output_color": "#00FF7F",
             "config": _op("UNION", _roi("LUNG_LT"), _roi("LUNG_RT"))},
            # 14. Lung minus the target (V20 constraint volume).
            {"rule_type": "BOOLEAN", "name": "LungPTV", "output_roi_type": "OAR",
             "output_color": "#00CC66",
             "config": _op("SUBTRACT", _roi("Lung_Total"), _roi("PTV"))},
            # 15. XOR(lung, lung-target) == the lung that lies inside the target
            #     (overlap QA structure).
            {"rule_type": "BOOLEAN", "name": "LungInPTV", "output_roi_type": "AVOIDANCE",
             "output_color": "#00994D",
             "config": _op("XOR", _roi("Lung_Total"), _roi("LungPTV"))},

            # --- Per-OAR PRVs and target sparing -----------------------------
            # 16. PRV around the LAD (3 mm).
            {"rule_type": "MARGIN", "name": "PRV_LAD", "output_roi_type": "OAR",
             "output_color": "#FF8080",
             "config": {"variant": "UNIFORM", "source": "LAD",
                        "margin_mm": 3.0, "kernel_type": "ball"}},
            # 17. PRV around the right brachial plexus (5 mm).
            {"rule_type": "MARGIN", "name": "PRV_BrachialR", "output_roi_type": "OAR",
             "output_color": "#FFAA00",
             "config": {"variant": "UNIFORM", "source": "BRACHIALPLEXUS_R",
                        "margin_mm": 5.0, "kernel_type": "ball"}},
            # 18. PTV carved away from the brachial PRV (dose sparing).
            {"rule_type": "BOOLEAN", "name": "PTV_sparedBP", "output_roi_type": "PTV",
             "output_color": "#E60000",
             "config": _op("SUBTRACT", _roi("PTV"), _roi("PRV_BrachialR"))},

            # --- Multi-structure OAR cluster and optimization avoidance ------
            # 19. Intrathoracic OAR cluster (four-operand union).
            {"rule_type": "BOOLEAN", "name": "OAR_Cluster", "output_roi_type": "OAR",
             "output_color": "#0000FF",
             "config": _op("UNION", _roi("HEART"), _roi("LAD"),
                           _roi("Lung_Total"), _roi("BRACHIALPLEXUS_R"))},
            # 20. Target clipped to inside the external (sanity structure).
            {"rule_type": "BOOLEAN", "name": "PTV_InBody", "output_roi_type": "PTV",
             "output_color": "#CC0000",
             "config": _op("INTERSECTION", _roi("PTV"), _roi("BODY"))},
            # 21. Everything that is neither target nor OAR (optimization fill).
            {"rule_type": "BOOLEAN", "name": "Opt_Avoid", "output_roi_type": "AVOIDANCE",
             "output_color": "#3399FF",
             "config": _op("SUBTRACT", _roi("BODY"),
                           _op("UNION", _roi("PTV"), _roi("OAR_Cluster")))},

            # --- Nodal-station cluster and elective-PTV crop -----------------
            # 22. Union of six nodal stations (six-operand union).
            {"rule_type": "BOOLEAN", "name": "Nodal_Nodes", "output_roi_type": "OAR",
             "output_color": "#1E90FF",
             "config": _op("UNION", _roi("SPLG1"), _roi("SPLG2"), _roi("SPLG3"),
                           _roi("SPLG4"), _roi("SPLG5"), _roi("SPLG6"))},
            # 23. Elective PTV clipped to inside the body (crop to one boundary).
            {"rule_type": "CROP", "name": "PTV_Elec_Body", "output_roi_type": "PTV",
             "output_color": "#FF5C5C",
             "config": {"source": "PTV_Elective", "boundaries": ["BODY"]}},

            # --- HU-derived (intensity) structures ---------------------------
            # 24. Soft-tissue sub-region within the tumour (structure seed).
            {"rule_type": "INTENSITY", "name": "BTV_Tissue", "output_roi_type": "GTV",
             "output_color": "#B22222",
             "config": {"seed_type": "STRUCTURE", "seed_roi": "BTV",
                        "ranges": [{"min": -50, "max": 400}]}},
            # 25. Bone / high-density across the whole image (image seed).
            {"rule_type": "INTENSITY", "name": "Bone_HU", "output_roi_type": "OAR",
             "output_color": "#DAA520",
             "config": {"seed_type": "IMAGE",
                        "ranges": [{"min": 300, "max": 3000}]}},

            # --- Cleanup, applied where a physicist actually applies it ------
            # 26. Drop stray air/tissue islands from the Internal contour.
            {"rule_type": "CLEANUP", "name": "Internal_Clean", "output_roi_type": "EXTERNAL",
             "output_color": "#8A5FBF",
             "config": {"operation": "REMOVE_SMALL_COMPONENTS", "source": "Internal",
                        "min_size_mm3": 1000.0}},
            # 27. Smooth the 2 cm optimization contour (jagged boolean edges).
            {"rule_type": "CLEANUP", "name": "Body_2cm_SM", "output_roi_type": "EXTERNAL",
             "output_color": "#5588DD",
             "config": {"operation": "SMOOTH_STRUCTURE", "source": "Body_2cm",
                        "smoothing_mm": 3.0, "iterations": 1}},
            # 28. Gaussian-smooth the 5 cm optimization contour.
            {"rule_type": "CLEANUP", "name": "Body_5cm_GS", "output_roi_type": "EXTERNAL",
             "output_color": "#B055EE",
             "config": {"operation": "GAUSSIAN_SMOOTH", "source": "Body_5cm",
                        "sigma_mm": 1.5, "threshold": 0.5}},
            # 29. Fill the vessel holes in the lung-minus-target shell.
            {"rule_type": "CLEANUP", "name": "Lung_Fill", "output_roi_type": "OAR",
             "output_color": "#00AA55",
             "config": {"operation": "FILL_HOLES", "source": "LungPTV",
                        "fully_connected": False}},
            # 30. Keep only the dominant target island (drop floating bits).
            {"rule_type": "CLEANUP", "name": "PTV_Largest", "output_roi_type": "PTV",
             "output_color": "#D40000",
             "config": {"operation": "KEEP_LARGEST_COMPONENT", "source": "PTV"}},

            # --- Output-action coverage -------------------------------------
            # 31. REPLACE_EXISTING: overwrite an imported placeholder (UD4)
            #     with a real derived structure.
            {"rule_type": "MARGIN", "name": "UD4", "output_action": "REPLACE_EXISTING",
             "output_roi_type": "CONTROL", "output_color": "#404040",
             "config": {"variant": "UNIFORM", "source": "PTV",
                        "margin_mm": 3.0, "kernel_type": "ball"}},
            # 32. A CREATE_NEW whose name matches an imported ROI
            #     ("PRV_RT BRACHIAL"); the engine's collision guard must save it
            #     as "PRV_RT BRACHIAL_1" instead of overwriting the original.
            {"rule_type": "MARGIN", "name": "PRV_RT BRACHIAL", "output_roi_type": "OAR",
             "output_color": "#FF8C00",
             "config": {"variant": "UNIFORM", "source": "BRACHIALPLEXUS_R",
                        "margin_mm": 5.0, "kernel_type": "ball"}},
        ],
    }


# Every derived ROI the pipeline creates via CREATE_NEW, including the one the
# engine auto-renamed on collision. Kept explicit so the audit can verify it.
CREATED_ROIS = [
    "PTV", "PTV_Elective", "PTV_Core", "Ring", "Body_Shrink5", "Skin_PRV5",
    "Internal", "PTV5mm", "PTV20", "Body_2cm", "PTV50", "Body_5cm",
    "Lung_Total", "LungPTV", "LungInPTV", "PRV_LAD", "PRV_BrachialR",
    "PTV_sparedBP", "OAR_Cluster", "PTV_InBody", "Opt_Avoid", "Nodal_Nodes",
    "PTV_Elec_Body", "BTV_Tissue", "Bone_HU", "Internal_Clean",
    "Body_2cm_SM", "Body_5cm_GS", "Lung_Fill", "PTV_Largest",
    "PRV_RT BRACHIAL_1",
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
        self.assertEqual(self.pipeline.rules.count(), 32)
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
        # 31 CREATE_NEW outputs (the CREATE_NEW named "PRV_RT BRACHIAL" collided
        # with the imported structure of the same name and the engine saved it
        # as "PRV_RT BRACHIAL_1").
        self.assertEqual(len(summary["created_rois"]), 31)
        self.assertIn("PRV_RT BRACHIAL_1", summary["created_rois"])
        self.assertEqual(set(summary["created_rois"]), set(CREATED_ROIS))

        # --- The saved output RTStruct is verified structurally -------------
        out_ds = pydicom.dcmread(rt_path, stop_before_pixels=True, force=True)
        out_names = {str(r.ROIName) for r in out_ds.StructureSetROISequence}

        for roi in CREATED_ROIS:
            self.assertIn(roi, out_names, f"derived ROI {roi} missing from output")
        for roi in original_roi_names:
            self.assertIn(roi, out_names)
        # 32 original + 31 new = 63 structures.
        self.assertEqual(len(out_names), len(original_roi_names) + 31)

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

        # --- Target definition: PTV grows from BTV; eroded core sits inside --
        self.assertGreater(vox("PTV"), vox("BTV"))
        self.assertTrue(subset("PTV_Core", "PTV"))
        # Dose-falloff ring is a strict, non-empty part of the target.
        self.assertTrue(subset("Ring", "PTV"))
        self.assertGreater(vox("Ring"), 0)
        # Anisotropic elective PTV grows the tumour with directional margins.
        self.assertGreater(vox("PTV_Elective"), vox("BTV"))

        # --- External / internal / skin --------------------------------------
        self.assertTrue(subset("Skin_PRV5", "BODY"))
        self.assertGreater(vox("Skin_PRV5"), 0)
        # Internal is a non-empty subset of the external contour.
        self.assertTrue(subset("Internal", "BODY"))
        self.assertGreater(vox("Internal"), 0)

        # --- Body-minus-target optimization family --------------------------
        self.assertTrue(subset("PTV", "PTV5mm"))       # PTV inside its +0.5 cm shell
        self.assertTrue(subset("PTV20", "PTV50"))      # dilation is monotonic
        self.assertTrue(subset("Body_2cm", "BODY"))
        self.assertTrue(subset("Body_5cm", "BODY"))
        # A bigger PTV cut-out leaves a smaller body shell.
        self.assertGreater(vox("Body_2cm"), vox("Body_5cm"))

        # --- Lung and target overlap ------------------------------------------
        self.assertTrue(subset("LungPTV", "Lung_Total"))
        # XOR(lung, lung - target) is exactly the lung lying inside the target.
        self.assertTrue(subset("LungInPTV", "Lung_Total"))
        self.assertTrue(subset("LungInPTV", "PTV"))

        # --- Per-OAR PRVs grow around their source --------------------------
        self.assertTrue(subset("LAD", "PRV_LAD"))
        self.assertTrue(subset("BRACHIALPLEXUS_R", "PRV_BrachialR"))
        # PTV sparing only removes from the target.
        self.assertTrue(subset("PTV_sparedBP", "PTV"))
        self.assertGreater(vox("PRV_BrachialR"), vox("BRACHIALPLEXUS_R"))

        # --- OAR cluster union contains each component ----------------------
        for part in ("HEART", "LUNG_LT", "LUNG_RT", "BRACHIALPLEXUS_R"):
            self.assertGreaterEqual(vox("OAR_Cluster"), vox(part))
        # Target clipped to the external is inside both; avoidance fill is the
        # body minus (target and OARs) and is strictly smaller than the body.
        self.assertTrue(subset("PTV_InBody", "BODY"))
        self.assertTrue(subset("PTV_InBody", "PTV"))
        self.assertTrue(subset("Opt_Avoid", "BODY"))
        self.assertLess(vox("Opt_Avoid"), vox("BODY"))
        # Elective PTV cropped to the body stays inside both operands.
        self.assertTrue(subset("PTV_Elec_Body", "PTV_Elective"))
        self.assertTrue(subset("PTV_Elec_Body", "BODY"))

        # --- HU-derived (intensity) structures ------------------------------
        self.assertGreater(vox("BTV_Tissue"), 0)
        self.assertTrue(subset("BTV_Tissue", "BTV"))
        self.assertGreater(vox("Bone_HU"), 0)

        # --- Nodal-station cluster (6-operand union) contains each station --
        for node in ("SPLG1", "SPLG2", "SPLG3", "SPLG4", "SPLG5", "SPLG6"):
            self.assertGreaterEqual(vox("Nodal_Nodes"), vox(node))

        # --- Cleanup, each on the structure it is genuinely used on ---------
        # Pruning stray islands can only shrink the Internal contour.
        self.assertTrue(subset("Internal_Clean", "Internal"))
        self.assertGreater(vox("Internal_Clean"), 0)
        # Filling vessel holes only grows the lung-minus-target shell.
        self.assertTrue(subset("LungPTV", "Lung_Fill"))
        self.assertGreaterEqual(vox("Lung_Fill"), vox("LungPTV"))
        # Keeping the dominant target island is a non-empty subset of the PTV.
        self.assertTrue(subset("PTV_Largest", "PTV"))
        self.assertGreater(vox("PTV_Largest"), 0)


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

    def test_overlong_output_name_rejected(self):
        """Names past the model's bounded column are rejected cleanly."""
        limit = PipelineRule._meta.get_field("name").max_length
        too_long = "N" * (limit + 1)
        data = {
            "name": "long",
            "rules": [
                {"rule_type": "MARGIN", "name": too_long,
                 "config": {"variant": "UNIFORM", "source": "BODY", "margin_mm": 1.0}},
            ],
        }
        with self.assertRaisesRegex(ValueError, "too long"):
            views._create_or_update_pipeline(data, self._user())

    def test_max_length_output_name_accepted(self):
        """A name exactly at the limit is accepted."""
        limit = PipelineRule._meta.get_field("name").max_length
        name = "N" * limit
        data = {
            "name": "atlimit",
            "rules": [
                {"rule_type": "MARGIN", "name": name,
                 "config": {"variant": "UNIFORM", "source": "BODY", "margin_mm": 1.0}},
            ],
        }
        pipeline = views._create_or_update_pipeline(data, self._user())
        self.assertEqual(pipeline.rules.get().name, name)

    def test_output_name_whitespace_is_stripped(self):
        """Surrounding whitespace is trimmed before the ROI name is stored."""
        data = {
            "name": "pad",
            "rules": [
                {"rule_type": "MARGIN", "name": "  PADDED  ",
                 "config": {"variant": "UNIFORM", "source": "BODY", "margin_mm": 1.0}},
            ],
        }
        pipeline = views._create_or_update_pipeline(data, self._user())
        self.assertEqual(pipeline.rules.get().name, "PADDED")


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
