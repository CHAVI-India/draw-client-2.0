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
