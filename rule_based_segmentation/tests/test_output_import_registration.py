"""Tests: ``_register_output_import`` records an RBS pipeline's output as a
``RTStructureFileImport`` (so it is listed on the RT-structure page and openable
in the DICOM viewer, which resolve the file via
``reidentified_rt_structure_file_path``) and is idempotent under redelivery.
"""

import os
import tempfile
import uuid

from django.test import TestCase

from dicom_handler.models import RTStructureFileImport
from spatial_overlap.models import RTStructureSetFile
from rule_based_segmentation.utils.job_service import _register_output_import

from .helpers import create_dicom_models, create_synthetic_ct_series


class _FakeJob:
    """Lightweight job exposing only what ``_register_output_import`` reads."""

    def __init__(self, dicom_series, input_upload, id="job-1"):
        self.id = id
        self.dicom_series = dicom_series
        self.input_upload = input_upload


class RegisterOutputImportTests(TestCase):
    def setUp(self):
        self.temp = tempfile.mkdtemp()
        self.series_uid = str(uuid.uuid4())
        self.study_uid = str(uuid.uuid4())
        ct = create_synthetic_ct_series(
            self.temp, num_slices=2, rows=4, cols=4,
            series_uid=self.series_uid, study_uid=self.study_uid,
        )
        self.series = create_dicom_models(ct, self.series_uid, self.study_uid)
        self.input_rssf = RTStructureSetFile.objects.create(
            patient_name="Test^Patient",
            patient_id="TESTPAT",
            study_instance_uid=str(uuid.uuid4()),
            series_instance_uid=str(uuid.uuid4()),
            sop_instance_uid=str(uuid.uuid4()),
            structure_set_label="input",
            referenced_series_instance_uid=self.series.series_instance_uid,
            rtstructure_file_path=os.path.join(self.temp, "input.dcm"),
        )
        self.output_path = os.path.join(self.temp, "output.dcm")
        self.output = {
            "sop_instance_uid": str(uuid.uuid4()),
            "series_instance_uid": str(uuid.uuid4()),
            "new_path": self.output_path,
        }

    def _imports(self):
        return RTStructureFileImport.objects.filter(
            reidentified_rt_structure_file_sop_instance_uid=self.output["sop_instance_uid"],
            deidentified_series_instance_uid=self.series,
        )

    def test_creates_import_pointing_at_output_file(self):
        _register_output_import(_FakeJob(self.series, self.input_rssf), self.output)
        imp = self._imports().get()
        self.assertEqual(imp.reidentified_rt_structure_file_path, self.output_path)
        self.assertEqual(imp.server_segmentation_status, "RULE_BASED_COMPLETED")
        self.assertEqual(imp.deidentified_sop_instance_uid, self.input_rssf.sop_instance_uid)
        self.assertEqual(imp.reidentified_rt_structure_file_series_instance_uid,
                         self.output["series_instance_uid"])

    def test_idempotent_under_redelivery(self):
        job = _FakeJob(self.series, self.input_rssf)
        _register_output_import(job, self.output)
        _register_output_import(job, self.output)
        self.assertEqual(self._imports().count(), 1)

    def test_missing_ct_series_is_skipped(self):
        _register_output_import(_FakeJob(None, self.input_rssf), self.output)
        self.assertFalse(RTStructureFileImport.objects.exists())

    def test_missing_input_upload_is_ok(self):
        _register_output_import(_FakeJob(self.series, None), self.output)
        imp = self._imports().get()
        self.assertIsNone(imp.deidentified_sop_instance_uid)
        self.assertEqual(imp.reidentified_rt_structure_file_path, self.output_path)
