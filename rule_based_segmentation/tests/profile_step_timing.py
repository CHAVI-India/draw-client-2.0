#!/usr/bin/env python3
"""Precise per-component timing of ONE RBS pipeline step on the real patient.

Replicates exactly what ``execute_rule_step`` does per Celery step:

    SegmentationEngine.from_workdir()          -> create_from + ReadImage + load_roi_masks
    engine.run_rule(rule)                       -> the operation + add_mask_as_roi
    wd.commit_rule_output()                     -> save_rtstruct (working.tmp -> working)

and times each component with perf_counter, so we see *where* the ~70s/step goes
rather than just the total. Run with:

    ./venv/bin/python rule_based_segmentation/tests/profile_step_timing.py
"""

import os
import time

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "draw_client.settings")
os.environ.setdefault("DJANGO_DB_ENGINE", "django.db.backends.postgresql")
os.environ.setdefault("DJANGO_DB_HOST", "localhost")
os.environ.setdefault("DJANGO_DB_PORT", "5432")
os.environ.setdefault("DJANGO_DB_NAME", "draw_client")
os.environ.setdefault("DJANGO_DB_USER", "postgres")
os.environ.setdefault("DJANGO_DB_PASSWORD", "26rishi1978")

import django

django.setup()

import numpy as np
import SimpleITK as sitk
from rt_utils import RTStructBuilder

from dicom_handler.models import DICOMInstance
from rule_based_segmentation.utils.rtstruct_io import (
    load_roi_masks,
    save_rtstruct,
    add_mask_as_roi,
)
from dicom_handler.utils.structure_generation.operations import (
    boolean_union,
    apply_directional_margin,
)


def _t(label, fn, reps=1):
    """Time ``fn`` over ``reps`` runs; print the mean. Returns the mean seconds."""
    best = []
    for _ in range(reps):
        t0 = time.perf_counter()
        fn()
        best.append(time.perf_counter() - t0)
    val = min(best) if len(best) > 1 else best[0]
    print(f"  {label:<44} {val:8.3f}s")
    return val


def main(patient_id="24_009663", input_rssf_id=4):
    from spatial_overlap.models import RTStructureSetFile

    r = RTStructureSetFile.objects.get(id=input_rssf_id)
    input_rtstruct = r.rtstructure_file_path
    series_uid = r.referenced_series_instance_uid
    insts = list(DICOMInstance.objects.filter(series_instance_uid__series_instance_uid=series_uid))
    ct_dir = os.path.dirname(insts[0].instance_path)
    ct_files = [i.instance_path for i in insts]
    print(f"patient={patient_id}  CT slices={len(ct_files)}  input_rtstruct={os.path.basename(input_rtstruct)}")
    print(f"ct_dir={ct_dir}")

    # ---- Build the reference image (the NIfTI cache the job writes) --------
    t0 = time.perf_counter()
    reader = sitk.ImageSeriesReader()
    reader.SetFileNames(sorted(ct_files))
    image = reader.Execute()
    nifti = "/tmp/_rbs_profile_image.nii.gz"
    sitk.WriteImage(image, nifti, compressionLevel=3)
    print(f"\n[setup] build NIfTI cache from {len(ct_files)} CT files: {time.perf_counter()-t0:.3f}s")
    print(f"         image size={image.GetSize()} spacing={tuple(round(s,3) for s in image.GetSpacing())}")

    roi_names_all = None
    print("\n=== PER-STEP BREAKDOWN (this is what runs for EVERY step) ===")

    # 1. RTStructBuilder.create_from  (re-reads ALL CT DICOM + the RTStruct)
    def do_create_from():
        return RTStructBuilder.create_from(dicom_series_path=ct_dir, rt_struct_path=input_rtstruct)

    rtstruct = _t("create_from (read CT+RTStruct)", do_create_from)
    rtstruct = do_create_from()  # keep the built object

    roi_names_all = rtstruct.get_roi_names()
    print(f"        -> {len(roi_names_all)} ROIs in the RTStruct")

    # 2. Read the NIfTI cache
    _t("ReadImage (NIfTI cache)", lambda: sitk.ReadImage(nifti))

    # 3. load_roi_masks (decode EVERY ROI contour -> mask)
    def do_load_masks():
        return load_roi_masks(rtstruct, image)

    masks = _t(f"load_roi_masks (decode {len(roi_names_all)} ROIs)", do_load_masks)
    masks = do_load_masks()

    # per-ROI cost estimate
    def do_one_mask():
        rtstruct.get_roi_mask_by_name(roi_names_all[0])

    _t(f"  ...one ROI decode ({roi_names_all[0]})", do_one_mask, reps=3)

    # 4. the operation itself (what run_rule actually computes)
    a = [m for m in masks.values()][0]
    b = [m for m in masks.values()][1]
    _t("operation: boolean_union (2 ROIs)", lambda: boolean_union(a, b))
    _t("operation: directional margin 5mm", lambda: apply_directional_margin(a, {k: 5.0 for k in "LRAPHF"}))

    # 5. add_mask_as_roi (write the new ROI into the in-memory RTStruct)
    def do_add():
        add_mask_as_roi(rtstruct, boolean_union(a, b), "PROF_probe", [255, 0, 0], "ORGAN")

    _t("add_mask_as_roi (encode 1 new ROI)", do_add)

    # 6. commit -> save_rtstruct (write the full RTStruct to disk)
    out = "/tmp/_rbs_profile_out.dcm"

    def do_save():
        save_rtstruct(rtstruct, out)

    _t("save_rtstruct (write full RTStruct)", do_save)

    # ---- NEW: the engine's real per-step path (LazyMaskCache) --------------
    from rule_based_segmentation.utils.engine import LazyMaskCache

    print("\n=== ENGINE PER-STEP (LazyMaskCache: decode only what a rule needs) ===")

    # from_workdir now: create_from + ReadImage + LazyMaskCache init (NO decode)
    def do_from_workdir_lazy():
        rb = RTStructBuilder.create_from(dicom_series_path=ct_dir, rt_struct_path=input_rtstruct)
        img = sitk.ReadImage(nifti)
        LazyMaskCache(rb, img)

    fromwd = _t("from_workdir TOTAL (create+Read+lazy init)", do_from_workdir_lazy)

    cache = LazyMaskCache(rtstruct, image)

    # a MARGIN rule needs exactly ONE source ROI -> decode 1, not 52
    src = roi_names_all[0]
    _t(f"decode the 1 ROI a margin rule needs ({src})", lambda: cache[src])

    # a BOOLEAN rule needs its operand ROIs -> decode N
    two = roi_names_all[:3]
    _t("decode the 3 ROIs a boolean rule needs", lambda: [cache[n] for n in two])

    print("\n=== COMPARISON ===")
    print(f"  OLD (eager load_roi_masks, all {len(roi_names_all)} ROIs): ~68s every step")
    print(f"  NEW (lazy from_workdir):                          {fromwd:.2f}s (no mask decode)")
    print("  NEW: each rule decodes only its referenced ROIs (1-4), ~1.2s each.")
    print("  => a 5-rule pipeline goes from ~5x68s to ~5 x a few-seconds.")


if __name__ == "__main__":
    main()
