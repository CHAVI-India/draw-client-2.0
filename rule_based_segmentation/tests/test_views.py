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
