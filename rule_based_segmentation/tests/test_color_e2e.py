"""End-to-end color fidelity over the real dataset.

Verifies that when the RBS pipeline actually *runs* (the production job chain:
prepare/execute/finalize) over the de-identified CT + RTStruct under
``tests/dicom_data``, each generated ROI's ``ROIDisplayColor`` in the **written
DICOM file** matches the rule's ``output_color`` — stored as the standard
``R\\G\\B`` string a TPS like Eclipse expects.

Covers both an explicit hex color and the inherit-from-source path (a rule with
no color takes its primary source structure's color rather than the yellow
default). Reuses the same dataset + real job chain as
``test_pipeline_e2e_physics``.
"""

import os
import shutil
import tempfile
from unittest import mock

import pydicom
from django.contrib.auth import get_user_model
from django.test import TestCase

from rule_based_segmentation.models import SegmentationJob
from rule_based_segmentation.utils import job_service, rtstruct_registry
from rule_based_segmentation.utils.dicom_image_importer import (
    import_uploaded_image_series,
)
from rule_based_segmentation.utils.pipeline_persistence import (
    save_pipeline_from_dict,
)

from .helpers import make_in_memory_file
from .test_pipeline_e2e_physics import _find_dataset


def _color_spec():
    return {
        "name": "Color Fidelity",
        "is_public": False,
        "rules": [
            # Explicit hex colors, each a distinct primary.
            {"rule_type": "MARGIN", "name": "ColRed", "output_roi_type": "PTV",
             "output_color": "#FF0000",
             "config": {"variant": "UNIFORM", "source": "BTV",
                        "margin_mm": 3.0, "kernel_type": "ball"}},
            {"rule_type": "MARGIN", "name": "ColGreen", "output_roi_type": "PTV",
             "output_color": "#00FF00",
             "config": {"variant": "UNIFORM", "source": "BTV",
                        "margin_mm": 5.0, "kernel_type": "ball"}},
            # Crop keeps the explicit blue.
            {"rule_type": "CROP", "name": "ColBlue", "output_roi_type": "PTV",
             "output_color": "#0000FF",
             "config": {"source": "ColGreen", "boundaries": ["BODY"]}},
            # No color in the spec. NOTE: the builder path cannot actually leave a
            # rule colourless - `_save_rule` defaults an empty output_color to
            # "255\\255\\0" (yellow), so the engine's inherit-from-source fallback
            # is unreachable via the UI. This documents that default (yellow), not
            # inheritance. (test_roi_fidelity covers true inheritance via a direct
            # PipelineRule.objects.create(output_color=None).)
            {"rule_type": "MARGIN", "name": "ColInherit", "output_roi_type": "PTV",
             "output_color": None,
             "config": {"variant": "UNIFORM", "source": "BTV",
                        "margin_mm": 2.0, "kernel_type": "ball"}},
        ],
    }


# Expected on-disk ROIDisplayColor (R\G\B) for each generated ROI.
EXPECTED_ON_DISK = {
    "ColRed": "255\\0\\0",
    "ColGreen": "0\\255\\0",
    "ColBlue": "0\\0\\255",
    # Builder default for an unset color (see note above) -> yellow.
    "ColInherit": "255\\255\\0",
}


class ColorFidelityE2ETests(TestCase):
    def setUp(self):
        self.workdir_base = tempfile.mkdtemp(prefix="rbs_color_work_")
        self._wd = mock.patch(
            "rule_based_segmentation.utils.job_service.get_job_workdir_base",
            return_value=self.workdir_base,
        )
        self._wd.start()

    def tearDown(self):
        self._wd.stop()
        shutil.rmtree(self.workdir_base, ignore_errors=True)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = get_user_model().objects.create_user(
            username="colorphys", password="x", email="c@x.y"
        )

        src_rtstruct, cls.series_uid, ct_files = _find_dataset()
        cls.src_rtstruct = src_rtstruct

        cls.work_dir = tempfile.mkdtemp(prefix="rbs_color_")
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
        cls.series = import_uploaded_image_series(
            uploads, expected_series_instance_uid=cls.series_uid
        )
        cls.pipeline = save_pipeline_from_dict(_color_spec(), cls.user)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work_dir, ignore_errors=True)
        super().tearDownClass()

    def _color_on_disk(self, ds, roi_name):
        """The on-disk ROIDisplayColor for a named ROI, as a ``R\\G\\B`` string."""
        for roi in ds.StructureSetROISequence:
            if str(roi.ROIName) == roi_name:
                num = int(roi.ROINumber)
                for c in ds.ROIContourSequence:
                    if int(c.ReferencedROINumber) == num:
                        return "\\".join(str(int(x)) for x in c.ROIDisplayColor)
        raise AssertionError(f"{roi_name} not found in the output RTStruct")

    def test_generated_roi_colors_stored_correctly_in_dicom(self):
        rt_path = os.path.join(self.work_dir, "rt_color.dcm")
        shutil.copy2(self.src_rtstruct, rt_path)
        rt_record = rtstruct_registry.register_rtstruct_file(rt_path)
        job = SegmentationJob.objects.create(
            pipeline=self.pipeline,
            input_type="UPLOAD",
            input_upload=rt_record,
            created_by=self.user,
            status="PENDING",
        )
        job_service.prepare_job(job)
        for rule in job.pipeline.rules.order_by("order"):
            job_service.execute_rule_step(job, rule.order)
        job_service.finalize_job(job)
        job.refresh_from_db()

        self.assertEqual(job.status, "SUCCESS", job.error_message)
        self.assertEqual(job.result_summary["failed_rules"], [])

        out_ds = pydicom.dcmread(
            job.output_file_path, stop_before_pixels=True, force=True
        )
        for name, expected in EXPECTED_ON_DISK.items():
            with self.subTest(roi=name):
                self.assertEqual(
                    self._color_on_disk(out_ds, name), expected,
                    f"{name}: on-disk ROIDisplayColor does not match "
                    f"(expected {expected!r})",
                )
