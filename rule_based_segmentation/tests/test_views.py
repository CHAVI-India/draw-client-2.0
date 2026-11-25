"""Tests for rule_based_segmentation views."""

import json
import os
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from ..models import PipelineRule, RuleStep, SegmentationJob, SegmentationPipeline
from dicom_handler.models import AdditionalStructures, AutosegmentationTemplate
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

    def test_pipeline_edit_injects_backend_rule_types(self):
        """The add-rule dropdown must be driven by the backend model choices
        (single source of truth), not a hardcoded JS list — so newly added
        spatial rule types appear automatically."""
        import re

        pipeline = SegmentationPipeline.objects.create(name="P", created_by=self.user)
        response = self.client.get(
            reverse("rule_based_segmentation:pipeline_edit", args=[pipeline.id])
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('id="rule-types"', content)

        match = re.search(
            r'id="rule-types"[^>]*>(.*?)</script>', content, re.DOTALL
        )
        self.assertIsNotNone(match, "rule-types payload missing from page")
        injected = json.loads(match.group(1))
        injected_values = {value for value, _ in injected}

        # Exactly matches the model choices (the source of truth).
        self.assertEqual(
            injected_values,
            {value for value, _ in PipelineRule.RULE_TYPE_CHOICES},
        )
        # The new spatial rule types are present.
        for rule_type in ("RING", "OVERLAP", "EXPAND_SUBTRACT", "AVOID_MARGIN"):
            self.assertIn(rule_type, injected_values)

    def test_pipeline_create_spatial_rule_types_round_trip(self):
        """All four spatial rule types are createable through the same view the
        UI posts to (exact JS-serialized shape), persist to the correct config
        models, and round-trip back to the editor unchanged."""
        import re

        rules = [
            {
                "rule_type": "RING", "name": "Ring", "output_action": "CREATE_NEW",
                "output_color": "#FFFF00", "output_roi_type": "ORGAN",
                "config": {"variant": "UNIFORM", "source": "Box", "thickness_mm": 5.0,
                           "thickness_x_mm": 0.0, "thickness_y_mm": 0.0, "thickness_z_mm": 0.0,
                           "kernel_type": "ball"},
            },
            {
                "rule_type": "OVERLAP", "name": "Ov", "output_action": "CREATE_NEW",
                "output_color": "#FFFF00", "output_roi_type": "ORGAN",
                "config": {"source": "Box", "others": ["Other1", "Other2"]},
            },
            {
                "rule_type": "EXPAND_SUBTRACT", "name": "ES", "output_action": "CREATE_NEW",
                "output_color": "#FFFF00", "output_roi_type": "ORGAN",
                "config": {"variant": "UNIFORM", "source": "Box", "subtract": "Other1",
                           "distance_mm": 5.0, "distance_x_mm": 0.0, "distance_y_mm": 0.0,
                           "distance_z_mm": 0.0, "kernel_type": "ball"},
            },
            {
                "rule_type": "AVOID_MARGIN", "name": "AM", "output_action": "CREATE_NEW",
                "output_color": "#FFFF00", "output_roi_type": "AVOIDANCE",
                "config": {"variant": "UNIFORM", "source": "Box", "avoid": "Other1",
                           "margin_mm": 5.0, "margin_x_mm": 0.0, "margin_y_mm": 0.0,
                           "margin_z_mm": 0.0, "kernel_type": "ball"},
            },
        ]
        payload = {"name": "Spatial Pipeline", "description": "", "is_public": False, "rules": rules}
        response = self.client.post(
            reverse("rule_based_segmentation:pipeline_create"),
            {"pipeline_data": json.dumps(payload)},
        )
        self.assertEqual(response.status_code, 302, getattr(response, "context", None))
        self.assertEqual(SegmentationPipeline.objects.count(), 1)
        pipeline = SegmentationPipeline.objects.get()
        self.assertEqual(pipeline.rules.count(), 4)

        # DB config records are correct.
        ring = pipeline.rules.get(rule_type="RING").ring_config
        self.assertEqual(ring.source, "Box")
        self.assertEqual(ring.thickness_mm, 5.0)
        overlap = pipeline.rules.get(rule_type="OVERLAP").overlap_config
        self.assertEqual(
            list(overlap.others.order_by("order").values_list("other_roi", flat=True)),
            ["Other1", "Other2"],
        )
        es = pipeline.rules.get(rule_type="EXPAND_SUBTRACT").expand_subtract_config
        self.assertEqual(es.subtract, "Other1")
        am = pipeline.rules.get(rule_type="AVOID_MARGIN").avoid_margin_config
        self.assertEqual(am.avoid, "Other1")

        # Round-trip: the edit page returns the configs to the editor unchanged.
        edit = self.client.get(
            reverse("rule_based_segmentation:pipeline_edit", args=[pipeline.id])
        )
        self.assertEqual(edit.status_code, 200)
        match = re.search(r'id="pipeline-data"[^>]*>(.*?)</script>', edit.content.decode(), re.DOTALL)
        self.assertIsNotNone(match)
        by_type = {r["rule_type"]: r["config"] for r in json.loads(match.group(1))["rules"]}
        self.assertEqual(by_type["RING"]["thickness_mm"], 5.0)
        self.assertEqual(by_type["OVERLAP"]["others"], ["Other1", "Other2"])
        self.assertEqual(by_type["EXPAND_SUBTRACT"]["subtract"], "Other1")
        self.assertEqual(by_type["AVOID_MARGIN"]["avoid"], "Other1")

    def test_pipeline_create_persists_structures(self):
        """The structure snapshot (name/color/roi_type) is saved with the
        pipeline and returned to the editor on later edit."""
        structures = [
            {"name": "CTV", "color": "#ff0000", "roi_type": "CTV"},
            {"name": "Lung", "color": "#00ff00", "roi_type": "ORGAN"},
        ]
        payload = {
            "name": "Struct Pipeline", "description": "", "is_public": False,
            "structures": structures,
            "rules": [{
                "rule_type": "MARGIN", "name": "PTV", "output_action": "CREATE_NEW",
                "output_color": "#FFFF00", "output_roi_type": "PTV",
                "config": {"variant": "UNIFORM", "source": "CTV", "margin_mm": 5.0,
                           "margin_x_mm": 0.0, "margin_y_mm": 0.0, "margin_z_mm": 0.0,
                           "kernel_type": "ball"},
            }],
        }
        response = self.client.post(
            reverse("rule_based_segmentation:pipeline_create"),
            {"pipeline_data": json.dumps(payload)},
        )
        self.assertEqual(response.status_code, 302, getattr(response, "context", None))
        pipeline = SegmentationPipeline.objects.get()
        self.assertEqual(pipeline.structures, structures)

        # Round-trip: the edit page returns the persisted structures.
        import re
        edit = self.client.get(
            reverse("rule_based_segmentation:pipeline_edit", args=[pipeline.id])
        )
        match = re.search(
            r'id="pipeline-data"[^>]*>(.*?)</script>', edit.content.decode(), re.DOTALL
        )
        data = json.loads(match.group(1))
        self.assertEqual(data["structures"], structures)

    def test_pipeline_rejects_forward_reference(self):
        """A rule may not reference an ROI produced by a LATER rule. Here rule 1
        (EXPAND_SUBTRACT) subtracts 'Y', which is only produced by rule 2."""
        payload = {
            "name": "Bad Order", "description": "", "is_public": False,
            "structures": [],
            "rules": [
                {
                    "rule_type": "EXPAND_SUBTRACT", "name": "X", "output_action": "CREATE_NEW",
                    "output_color": "#FFFF00", "output_roi_type": "ORGAN",
                    "config": {"variant": "UNIFORM", "source": "Base", "subtract": "Y",
                               "distance_mm": 5.0, "distance_x_mm": 0.0, "distance_y_mm": 0.0,
                               "distance_z_mm": 0.0, "kernel_type": "ball"},
                },
                {
                    "rule_type": "MARGIN", "name": "Y", "output_action": "CREATE_NEW",
                    "output_color": "#FFFF00", "output_roi_type": "ORGAN",
                    "config": {"variant": "UNIFORM", "source": "Base", "margin_mm": 5.0,
                               "margin_x_mm": 0.0, "margin_y_mm": 0.0, "margin_z_mm": 0.0,
                               "kernel_type": "ball"},
                },
            ],
        }
        response = self.client.post(
            reverse("rule_based_segmentation:pipeline_create"),
            {"pipeline_data": json.dumps(payload)},
        )
        # Rejected: the form is re-rendered (200) with an error, not saved (302).
        self.assertEqual(response.status_code, 200)
        self.assertEqual(SegmentationPipeline.objects.count(), 0)
        self.assertIn("produced by rule", response.content.decode())

    def test_pipeline_allows_custom_structure_names(self):
        """Free-text structure names that are neither in the catalog nor produced
        by any rule are accepted (they may exist only in the target RTStruct)."""
        payload = {
            "name": "Custom Names", "description": "", "is_public": False,
            "structures": [],
            "rules": [
                {
                    "rule_type": "AVOID_MARGIN", "name": "Avoided", "output_action": "CREATE_NEW",
                    "output_color": "#FFFF00", "output_roi_type": "AVOIDANCE",
                    "config": {"variant": "UNIFORM", "source": "KeepMe",
                               "avoid": "A Structure Not In The Sample", "margin_mm": 3.0,
                               "margin_x_mm": 0.0, "margin_y_mm": 0.0, "margin_z_mm": 0.0,
                               "kernel_type": "ball"},
                },
            ],
        }
        response = self.client.post(
            reverse("rule_based_segmentation:pipeline_create"),
            {"pipeline_data": json.dumps(payload)},
        )
        self.assertEqual(response.status_code, 302, getattr(response, "context", None))
        rule = SegmentationPipeline.objects.get().rules.get()
        self.assertEqual(rule.avoid_margin_config.avoid, "A Structure Not In The Sample")

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


class TemplatePreviewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="prevuser", password="x")
        self.client = Client()
        self.client.force_login(self.user)

    def _template(self):
        template = AutosegmentationTemplate.objects.create(template_name="t")
        AdditionalStructures.objects.create(
            autosegmentation_template=template,
            roi_label="PTV_final",
            rt_roi_interpreted_type="PTV",
            roi_display_color="255\\0\\0",
            roi_generation_logic={"operations": [
                {"type": "margin", "structures": ["CTV"],
                 "parameters": {"margin_mm": 5.0, "variant": "UNIFORM"}},
                {"type": "crop_to_boundary", "structures": ["Body"], "parameters": {}},
            ]},
        )
        AdditionalStructures.objects.create(
            autosegmentation_template=template,
            roi_label="Spa",
            rt_roi_interpreted_type="OAR",
        )
        return template

    def test_preview_lists_synthesized_rules(self):
        template = self._template()
        from ..models import SegmentationPipeline

        before = SegmentationPipeline.objects.count()
        resp = self.client.get(
            reverse("rule_based_segmentation:api_template_preview"),
            {"template_id": str(template.pk)},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        labels = {s["roi_label"] for s in data["structures"]}
        self.assertEqual(labels, {"PTV_final", "Spa"})
        ptv = next(s for s in data["structures"] if s["roi_label"] == "PTV_final")
        self.assertEqual(len(ptv["rules"]), 2)
        self.assertEqual(ptv["rules"][0]["output_action"], "INTERMEDIATE")
        self.assertEqual(ptv["rules"][1]["output_action"], "CREATE_NEW")
        self.assertEqual(ptv["rules"][1]["name"], "PTV_final")
        # empty structure has no rules
        spa = next(s for s in data["structures"] if s["roi_label"] == "Spa")
        self.assertEqual(spa["rules"], [])
        # the transient preview pipeline is cleaned up
        self.assertEqual(SegmentationPipeline.objects.count(), before)

    def test_preview_requires_template_id(self):
        resp = self.client.get(reverse("rule_based_segmentation:api_template_preview"))
        self.assertEqual(resp.status_code, 400)

    def test_preview_unknown_template_404(self):
        resp = self.client.get(
            reverse("rule_based_segmentation:api_template_preview"),
            {"template_id": "00000000-0000-0000-0000-000000000000"},
        )
        self.assertEqual(resp.status_code, 404)
