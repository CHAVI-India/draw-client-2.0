"""
Unit tests for structure_set_output.build_output_structure_set.

Covers: new file created (input unchanged), new RTStructureSetFile record,
per-ROI approval (original ROIs inherit the input file's 300E approval, new
ROIs are UNAPPROVED), and the new file's file-level 300E,0002 == UNAPPROVED.
"""

import os
import tempfile
import uuid

import pydicom
from django.test import TestCase

from spatial_overlap.models import RTStructureSetFile
from rule_based_segmentation.utils.engine import SegmentationEngine
from rule_based_segmentation.utils.rtstruct_io import (
    add_mask_as_roi,
    regenerate_instance_uids,
)
from rule_based_segmentation.utils.structure_set_output import (
    build_output_structure_set,
)

from .helpers import (
    create_dicom_models,
    create_synthetic_ct_series,
    create_synthetic_rtstruct,
)


def _add_approval_tags(
    rtstruct_path: str,
    status: str = "APPROVED",
    review_date: str = "20240115",
    review_time: str = "123000",
    reviewer: str = "Doe^Jane",
) -> None:
    """Stamp the file-level DICOM Approval Module (300E) onto an RTStruct."""
    ds = pydicom.dcmread(rtstruct_path, force=True)
    ds.ApprovalStatus = status  # (300E,0002)
    ds.ReviewDate = review_date  # (300E,0004)
    ds.ReviewTime = review_time  # (300E,0005)
    ds.ReviewerName = reviewer  # (300E,0008)
    ds.save_as(rtstruct_path)


class _Job:
    """Minimal stand-in exposing only the attribute the builder needs."""

    def __init__(self, id):
        self.id = id


class BuildOutputStructureSetTests(TestCase):
    """build_output_structure_set emits a new structure set; input untouched."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.series_uid = str(uuid.uuid4())
        self.study_uid = str(uuid.uuid4())
        self.patient_id = "TESTPAT"
        self.patient_name = "Test Patient"

        ct_paths = create_synthetic_ct_series(
            self.temp_dir,
            num_slices=4,
            rows=8,
            cols=8,
            spacing=(1.0, 1.0, 2.0),
            series_uid=self.series_uid,
            study_uid=self.study_uid,
            patient_id=self.patient_id,
            patient_name=self.patient_name,
        )
        self.rtstruct_path = os.path.join(self.temp_dir, "rtstruct_in.dcm")
        import numpy as np

        mask = np.zeros((4, 8, 8), dtype=np.uint8)
        mask[:, 2:6, 2:6] = 1
        create_synthetic_rtstruct(
            self.rtstruct_path, ct_paths, "Box", mask, [255, 0, 0]
        )
        _add_approval_tags(self.rtstruct_path)
        self.dicom_series = create_dicom_models(
            ct_paths,
            self.series_uid,
            self.study_uid,
            self.patient_id,
            self.patient_name,
        )
        # Input structure set record (the one the pipeline runs against).
        ds = pydicom.dcmread(self.rtstruct_path, force=True)
        self.input_record = RTStructureSetFile.objects.create(
            patient_name=self.patient_name,
            patient_id=self.patient_id,
            study_instance_uid=self.study_uid,
            series_instance_uid=self.series_uid,
            sop_instance_uid=str(ds.SOPInstanceUID),
            structure_set_label="Original",
            referenced_series_instance_uid=self.series_uid,
            rtstructure_file_path=self.rtstruct_path,
            working_directory=self.temp_dir,
        )
        self.original_sop_uid = str(ds.SOPInstanceUID)
        self.original_file_bytes = open(self.rtstruct_path, "rb").read()

    def _build(self, created, replaced):
        engine = SegmentationEngine(self.rtstruct_path, self.series_uid)
        # Simulate a rule-created ROI.
        import numpy as np
        import SimpleITK as sitk

        new_mask = np.zeros((4, 8, 8), dtype=np.uint8)
        new_mask[:, 1:3, 1:3] = 1
        add_mask_as_roi(
            engine.rtstruct, sitk.GetImageFromArray(new_mask), "NewROI", [0, 255, 0],
            roi_type="ORGAN_AT_RISK",
        )
        regenerate_instance_uids(engine.rtstruct)
        job = _Job(id=uuid.uuid4())
        return build_output_structure_set(
            engine.rtstruct, self.rtstruct_path, job, created, replaced
        )

    def test_new_file_created_and_input_unchanged(self):
        result = self._build(created=["NewROI"], replaced=[])
        self.assertTrue(os.path.exists(result["new_path"]))
        self.assertNotEqual(result["new_path"], self.rtstruct_path)
        # Input file is byte-identical.
        self.assertEqual(
            open(self.rtstruct_path, "rb").read(), self.original_file_bytes
        )
        # New file has fresh UIDs (not the original SOP UID).
        new_ds = pydicom.dcmread(result["new_path"], force=True)
        self.assertNotEqual(str(new_ds.SOPInstanceUID), self.original_sop_uid)
        self.assertEqual(result["sop_instance_uid"], str(new_ds.SOPInstanceUID))

    def test_new_record_and_per_roi_approval(self):
        result = self._build(created=["NewROI"], replaced=[])
        record = RTStructureSetFile.objects.get(id=result["record_id"])
        self.assertEqual(record.sop_instance_uid, result["sop_instance_uid"])
        self.assertEqual(record.rtstructure_file_path, result["new_path"])
        self.assertNotEqual(record, self.input_record)

        voimap = {v.roi_name: v for v in record.vois.all()}
        # Original ROI inherited the input file's approval.
        self.assertEqual(voimap["Box"].approval_status, "APPROVED")
        self.assertEqual(voimap["Box"].reviewer_name, "Doe^Jane")
        self.assertIsNotNone(voimap["Box"].review_date)
        # New ROI is unapproved.
        self.assertEqual(voimap["NewROI"].approval_status, "UNAPPROVED")
        self.assertIsNone(voimap["NewROI"].reviewer_name)
        self.assertIn("NewROI", result["new_rois"])
        self.assertIn("Box", result["preserved_rois"])

    def test_new_file_file_level_approval_unapproved(self):
        result = self._build(created=["NewROI"], replaced=[])
        new_ds = pydicom.dcmread(result["new_path"], force=True)
        self.assertEqual(str(new_ds.ApprovalStatus), "UNAPPROVED")
        # No review date/time/reviewer on the new (unapproved) file.
        self.assertFalse(hasattr(new_ds, "ReviewerName"))

    def test_input_record_untouched(self):
        before = self.input_record
        self._build(created=["NewROI"], replaced=[])
        before.refresh_from_db()
        self.assertEqual(before.sop_instance_uid, self.original_sop_uid)
        self.assertEqual(before.rtstructure_file_path, self.rtstruct_path)
