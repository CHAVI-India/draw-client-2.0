"""A5: consolidation migration (per-row pipelines -> one template pipeline)."""

import importlib

from django.contrib.auth.models import User
from django.test import TestCase

from dicom_handler.models import AdditionalStructures, AutosegmentationTemplate
from rule_based_segmentation.models import SegmentationPipeline
from rule_based_segmentation.utils.pipeline_persistence import save_pipeline_from_dict

_mig = importlib.import_module(
    "dicom_handler.migrations.0064_consolidate_template_pipelines"
)


class ConsolidateMigrationTests(TestCase):
    def _template_with_rows(self):
        user = User.objects.create(username="u_mig")
        template = AutosegmentationTemplate.objects.create(template_name="Head")
        row1 = AdditionalStructures.objects.create(
            autosegmentation_template=template, roi_label="PTV",
            rt_roi_interpreted_type="PTV", roi_display_color="255\\0\\0",
        )
        p1 = save_pipeline_from_dict(
            {
                "name": "PTV generation",
                "structures": ["CTV"],
                "rules": [
                    {"rule_type": "MARGIN", "name": "PTV",
                     "output_action": "CREATE_NEW",
                     "config": {"source": "CTV", "margin_l_mm": 5},
                     "tempId": "a"},
                ],
            },
            user,
        )
        row1.pipeline = p1
        row1.save()
        # empty-ROI placeholder (no pipeline)
        AdditionalStructures.objects.create(
            autosegmentation_template=template, roi_label="Spa",
            rt_roi_interpreted_type="OAR", roi_display_color="0\\255\\0",
        )
        return template, p1

    def test_consolidates_into_one_template_pipeline(self):
        template, p1 = self._template_with_rows()
        _mig._migrate(None, None)

        template.refresh_from_db()
        self.assertIsNotNone(template.additional_structures_pipeline)
        p = template.additional_structures_pipeline
        self.assertEqual(p.rules.count(), 2)  # MARGIN (from row1) + EMPTY (row2)
        self.assertEqual(
            set(p.rules.values_list("rule_type", flat=True)), {"MARGIN", "EMPTY"}
        )
        self.assertEqual(
            set(p.rules.values_list("name", flat=True)), {"PTV", "Spa"}
        )
        # Non-destructive: the original per-row pipeline still exists.
        self.assertTrue(SegmentationPipeline.objects.filter(id=p1.id).exists())
        self.assertNotEqual(p.id, p1.id)

    def test_idempotent(self):
        template, _ = self._template_with_rows()
        _mig._migrate(None, None)
        template.refresh_from_db()
        first_pipeline = template.additional_structures_pipeline
        _mig._migrate(None, None)  # run again
        template.refresh_from_db()
        self.assertEqual(template.additional_structures_pipeline, first_pipeline)
        self.assertEqual(template.additional_structures_pipeline.rules.count(), 2)
        # only the consolidated pipeline was added (no extras)
        self.assertEqual(SegmentationPipeline.objects.count(), 2)

    def test_name_collision_is_renamed_and_references_rewritten(self):
        # Two rows whose pipelines produce the same output name.
        user = User.objects.create(username="u_coll")
        template = AutosegmentationTemplate.objects.create(template_name="Coll")
        for label in ("A", "B"):
            row = AdditionalStructures.objects.create(
                autosegmentation_template=template, roi_label=label,
                rt_roi_interpreted_type="PTV",
            )
            p = save_pipeline_from_dict(
                {
                    "name": f"{label} gen",
                    "structures": ["CTV"],
                    "rules": [
                        {"rule_type": "MARGIN", "name": "Same",
                         "output_action": "CREATE_NEW",
                         "config": {"source": "CTV", "margin_l_mm": 2},
                         "tempId": label},
                    ],
                },
                user,
            )
            row.pipeline = p
            row.save()

        _mig._migrate(None, None)
        template.refresh_from_db()
        p = template.additional_structures_pipeline
        names = set(p.rules.values_list("name", flat=True))
        # two distinct outputs, one auto-suffixed
        self.assertEqual(p.rules.count(), 2)
        self.assertNotEqual(len(names), 1)
        self.assertIn("Same", names)
        self.assertTrue(any(n.startswith("Same_") for n in names))
