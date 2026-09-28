"""Tests for rule_based_segmentation views."""

import json
import os
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from ..models import PipelineRule, SegmentationPipeline
from .helpers import create_minimal_rtstruct_file, make_in_memory_file

User = get_user_model()


class ViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="testpass")
        self.client = Client()
        self.client.force_login(self.user)

    def test_pipeline_list_view(self):
        response = self.client.get(reverse("rule_based_segmentation:pipeline_list"))
        self.assertEqual(response.status_code, 200)

    def test_pipeline_create_view(self):
        data = {
            "pipeline_data": json.dumps({
                "name": "PTV Pipeline",
                "description": "CTV + margin",
                "is_public": False,
                "rules": [
                    {
                        "rule_type": "MARGIN",
                        "name": "PTV",
                        "output_action": "CREATE_NEW",
                        "output_color": "#FFFF00",
                        "output_roi_type": "PTV",
                        "config": {
                            "variant": "UNIFORM",
                            "source": "CTV",
                            "margin_mm": 5.0,
                            "kernel_type": "ball",
                        },
                    }
                ],
            })
        }
        response = self.client.post(reverse("rule_based_segmentation:pipeline_create"), data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(SegmentationPipeline.objects.count(), 1)
        self.assertEqual(PipelineRule.objects.count(), 1)

    def test_pipeline_create_boolean_tree(self):
        data = {
            "pipeline_data": json.dumps({
                "name": "Boolean Pipeline",
                "description": "",
                "is_public": False,
                "rules": [
                    {
                        "rule_type": "BOOLEAN",
                        "name": "Result",
                        "output_action": "CREATE_NEW",
                        "output_color": "#FFFF00",
                        "output_roi_type": "ORGAN",
                        "config": {
                            "operation": "UNION",
                            "operands": [
                                {"name": "A"},
                                {"name": "B"},
                            ],
                        },
                    }
                ],
            })
        }
        response = self.client.post(reverse("rule_based_segmentation:pipeline_create"), data)
        self.assertEqual(response.status_code, 302)
        rule = PipelineRule.objects.first()
        self.assertEqual(rule.boolean_nodes.count(), 3)

    def test_pipeline_create_rejects_duplicate_output_names(self):
        data = {
            "pipeline_data": json.dumps({
                "name": "Duplicate Names Pipeline",
                "description": "",
                "is_public": False,
                "rules": [
                    {
                        "rule_type": "MARGIN",
                        "name": "PTV",
                        "output_action": "CREATE_NEW",
                        "output_color": "#FFFF00",
                        "output_roi_type": "PTV",
                        "config": {"variant": "UNIFORM", "source": "CTV", "margin_mm": 5.0, "kernel_type": "ball"},
                    },
                    {
                        "rule_type": "CLEANUP",
                        "name": "PTV",
                        "output_action": "CREATE_NEW",
                        "output_color": "#FFFF00",
                        "output_roi_type": "PTV",
                        "config": {"operation": "SMOOTH_STRUCTURE", "source": "PTV", "smoothing_mm": 2.0, "iterations": 1},
                    },
                ],
            })
        }
        response = self.client.post(reverse("rule_based_segmentation:pipeline_create"), data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Output ROI names must be unique")
        self.assertEqual(SegmentationPipeline.objects.count(), 0)

    def test_pipeline_create_rejects_forward_reference(self):
        data = {
            "pipeline_data": json.dumps({
                "name": "Forward Reference Pipeline",
                "description": "",
                "is_public": False,
                "rules": [
                    {
                        "rule_type": "CROP",
                        "name": "Cropped",
                        "output_action": "CREATE_NEW",
                        "output_color": "#FFFF00",
                        "output_roi_type": "ORGAN",
                        "config": {"source": "Generated", "boundaries": ["External"]},
                    },
                    {
                        "rule_type": "BOOLEAN",
                        "name": "Generated",
                        "output_action": "CREATE_NEW",
                        "output_color": "#FFFF00",
                        "output_roi_type": "ORGAN",
                        "config": {"operation": "UNION", "operands": [{"name": "A"}, {"name": "B"}]},
                    },
                ],
            })
        }
        response = self.client.post(reverse("rule_based_segmentation:pipeline_create"), data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Move the source rule before this rule")
        self.assertEqual(SegmentationPipeline.objects.count(), 0)

    def test_api_upload_sample_rtstruct(self):
        content = create_minimal_rtstruct_file(
            roi_names=["CTV", "GTV"], colors=[[255, 0, 0], [0, 255, 0]]
        )
        uploaded_file = make_in_memory_file("sample_rtstruct.dcm", content)

        target_dir = tempfile.mkdtemp(prefix="rbs_upload_")
        with patch(
            "rule_based_segmentation.views._get_rtstruct_upload_directory",
            return_value=target_dir,
        ):
            response = self.client.post(
                reverse("rule_based_segmentation:api_upload_sample_rtstruct"),
                {"rtstruct_file": uploaded_file},
            )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["structures"]), 2)
        self.assertIn("CTV", [s["value"] for s in data["structures"]])
        ctv = next(s for s in data["structures"] if s["value"] == "CTV")
        self.assertEqual(ctv["color"], "#ff0000")


class RTStructSearchTests(TestCase):
    """Tests for the Select2 AJAX RTStruct search endpoint."""

    def setUp(self):
        self.user = User.objects.create_user(username="searchuser", password="testpass")
        self.client = Client()
        self.client.force_login(self.user)
        self.url = reverse("rule_based_segmentation:api_search_rtstructs")

        from spatial_overlap.models import RTStructureSetFile
        from dicom_handler.models import (
            DICOMSeries,
            DICOMStudy,
            Patient,
            RTStructureFileImport,
        )

        self.upload = RTStructureSetFile.objects.create(
            patient_name="Doe^John",
            patient_id="P001",
            study_instance_uid="1.2.3",
            series_instance_uid="1.2.3.4",
            sop_instance_uid="1.2.3.4.5",
            structure_set_label="CT STRUCT",
            referenced_series_instance_uid="9.9.9",
        )

        patient = Patient.objects.create(patient_name="Smith^Jane", patient_id="P002")
        study = DICOMStudy.objects.create(
            patient=patient,
            study_instance_uid="2.2.2",
            study_description="Head CT",
        )
        series = DICOMSeries.objects.create(
            study=study,
            series_instance_uid="2.2.2.3",
            series_description="Axial CT",
        )
        self.rt_import = RTStructureFileImport.objects.create(
            deidentified_series_instance_uid=series,
            reidentified_rt_structure_file_path="/tmp/rt.dcm",
        )

        self.RTStructureSetFile = RTStructureSetFile
        self.RTStructureFileImport = RTStructureFileImport

    def _children(self, data, group_text):
        group = next((g for g in data["results"] if g["text"] == group_text), None)
        return group["children"] if group else []

    def test_requires_login(self):
        self.client.logout()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_empty_query_returns_both_groups(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        data = response.json()

        uploads = self._children(data, "Uploaded")
        imports = self._children(data, "Auto-segmented")
        self.assertEqual([c["id"] for c in uploads], [f"upload:{self.upload.id}"])
        self.assertEqual([c["id"] for c in imports], [f"import:{self.rt_import.id}"])
        self.assertIn("Doe^John", uploads[0]["text"])
        self.assertIn("Smith^Jane", imports[0]["text"])
        self.assertFalse(data["pagination"]["more"])

    def test_search_filters_uploaded_by_patient_name(self):
        response = self.client.get(self.url, {"q": "Doe"})
        data = response.json()
        self.assertEqual(len(self._children(data, "Uploaded")), 1)
        self.assertEqual(len(self._children(data, "Auto-segmented")), 0)

    def test_search_filters_imports_via_series_patient(self):
        response = self.client.get(self.url, {"q": "Smith"})
        data = response.json()
        self.assertEqual(len(self._children(data, "Uploaded")), 0)
        imports = self._children(data, "Auto-segmented")
        self.assertEqual(len(imports), 1)
        self.assertIn("P002", imports[0]["text"])

    def test_search_filters_imports_by_series_description(self):
        response = self.client.get(self.url, {"q": "Axial"})
        data = response.json()
        imports = self._children(data, "Auto-segmented")
        self.assertEqual(len(imports), 1)

    def test_no_match_returns_empty_results(self):
        response = self.client.get(self.url, {"q": "nonexistent-xyz"})
        data = response.json()
        self.assertEqual(data["results"], [])
        self.assertFalse(data["pagination"]["more"])

    def test_pagination_reports_more(self):
        from rule_based_segmentation.views import RTSTRUCT_SEARCH_PAGE_SIZE

        for i in range(RTSTRUCT_SEARCH_PAGE_SIZE):
            self.RTStructureSetFile.objects.create(
                patient_name=f"Bulk{i}",
                patient_id=f"B{i}",
                study_instance_uid=f"3.3.{i}",
                series_instance_uid=f"3.3.{i}.1",
                sop_instance_uid=f"3.3.{i}.1.1",
                structure_set_label="S",
                referenced_series_instance_uid="8.8.8",
            )
        data = self.client.get(self.url).json()
        self.assertTrue(data["pagination"]["more"])
        self.assertEqual(len(self._children(data, "Uploaded")), RTSTRUCT_SEARCH_PAGE_SIZE)
        page2 = self.client.get(self.url, {"page": 2}).json()
        page2_uploads = self._children(page2, "Uploaded")
        self.assertEqual([c["id"] for c in page2_uploads], [f"upload:{self.upload.id}"])

    def test_import_without_series_still_labeled(self):
        orphan = self.RTStructureFileImport.objects.create(
            deidentified_series_instance_uid=None,
            reidentified_rt_structure_file_path="/tmp/orphan_rt.dcm",
        )
        data = self.client.get(self.url).json()
        imports = self._children(data, "Auto-segmented")
        entry = next(c for c in imports if c["id"] == f"import:{orphan.id}")
        self.assertIn("orphan_rt.dcm", entry["text"])
