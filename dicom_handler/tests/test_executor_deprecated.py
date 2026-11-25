"""The legacy generated-contour executor is deprecated in favor of RBS."""

import warnings
from django.test import TestCase

from dicom_handler.utils.pipeline_executor import (
    ProductionPipelineExecutor,
    execute_additional_structure_pipeline,
)


class ExecutorDeprecatedTests(TestCase):
    def test_convenience_function_is_deprecated(self):
        with self.assertRaises(NotImplementedError):
            execute_additional_structure_pipeline(
                None, None, "x", {"operations": []}, [0, 0, 0]
            )

    def test_executor_execute_pipeline_is_deprecated(self):
        with self.assertRaises(NotImplementedError):
            ProductionPipelineExecutor(None, None).execute_pipeline(
                {"operations": []}
            )

    def test_deprecation_warning_emitted(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            try:
                execute_additional_structure_pipeline(
                    None, None, "x", {"operations": []}, [0, 0, 0]
                )
            except NotImplementedError:
                pass
        self.assertTrue(
            any(isinstance(w.message, DeprecationWarning) for w in caught),
            "expected a DeprecationWarning to be emitted",
        )
