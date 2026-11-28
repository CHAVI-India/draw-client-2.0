"""Per-job working directory for chain-based pipeline execution.

Layout (under ``get_job_workdir_base()``):

    {job_id}/
        images/            copied DICOM instances (for rt-utils)
        image.nii.gz       SimpleITK cache of the reference image series
        working.dcm        RTStruct with all completed rules applied
        working.tmp.dcm    scratch file for commit-by-rename
        step-{order}.json  commit manifest: {"output_name": "<ROI name>"}
        intermediate/      NIfTI masks of INTERMEDIATE (not-exported) rule
                           outputs: {order:03d}.nii.gz — available to later
                           steps but NEVER written into working.dcm

Commit protocol (crash-safe, see plan design notes):
    1. save updated RTStruct to working.tmp.dcm
    2. atomically write step-{order}.json (records the chosen ROI name)
    3. os.replace(working.tmp.dcm -> working.dcm)
"""

import json
import logging
import os
import shutil
from typing import Dict, List, Optional

import SimpleITK as sitk

from dicom_handler.models import DICOMInstance, SystemConfiguration

logger = logging.getLogger(__name__)


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
        self.intermediate_dir = os.path.join(self.root, "intermediate")

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

    # -- intermediate (not-exported) masks ---------------------------------

    def intermediate_mask_path(self, order: int) -> str:
        return os.path.join(self.intermediate_dir, f"{order:03d}.nii.gz")

    def save_intermediate_mask(self, order: int, mask) -> None:
        """Persist an INTERMEDIATE rule's mask so later steps (each running in
        its own process) can resolve it. Kept OUT of working.dcm on purpose —
        intermediate structures must not appear in the exported RTStruct."""
        import SimpleITK as sitk

        os.makedirs(self.intermediate_dir, exist_ok=True)
        # SimpleITK selects its writer by file extension, so the scratch
        # file must keep a .nii.gz suffix to be renamed into place.
        tmp = os.path.join(self.intermediate_dir, f"{order:03d}.tmp.nii.gz")
        sitk.WriteImage(mask, tmp, compressionLevel=3)
        os.replace(tmp, self.intermediate_mask_path(order))

    def load_intermediate_masks(self) -> Dict[str, "sitk.Image"]:
        """Return {ROI name: SimpleITK mask} for all persisted intermediates."""
        return load_intermediate_masks(self.root)


def load_intermediate_masks(workdir_root: str) -> Dict[str, "sitk.Image"]:
    """Load INTERMEDIATE masks persisted under ``<root>/intermediate/``.

    Each ``{order:03d}.nii.gz`` is paired with its ``step-{order}.json``
    manifest for the ROI name; orphan files (manifest lost) are skipped.
    Returns an empty dict when the directory does not exist.
    """
    import SimpleITK as sitk

    inter_dir = os.path.join(workdir_root, "intermediate")
    masks: Dict[str, "sitk.Image"] = {}
    if not os.path.isdir(inter_dir):
        return masks
    for fname in sorted(os.listdir(inter_dir)):
        if not fname.endswith(".nii.gz"):
            continue
        order = int(fname[:3])
        manifest_path = os.path.join(workdir_root, f"step-{order}.json")
        name = None
        if os.path.exists(manifest_path):
            with open(manifest_path, "r", encoding="utf-8") as fh:
                name = json.load(fh).get("output_name")
        if not name:
            logger.warning(
                "Intermediate mask %s has no step manifest; skipping", fname
            )
            continue
        masks[name] = sitk.ReadImage(os.path.join(inter_dir, fname))
    return masks
