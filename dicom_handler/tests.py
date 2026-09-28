import os

from django.test import TestCase


class RoiCacheFilenameTests(TestCase):
    """
    Mask-cache filenames are derived from ROI names that attackers can control
    (request JSON / RT Structure contents). They must always resolve inside the
    cache directory (CWE-22).
    """

    def test_traversal_name_produces_safe_filename(self):
        from dicom_handler.dicom_viewer_views import _roi_cache_filename

        name = _roi_cache_filename('../../../tmp/evil', '.pkl')
        self.assertNotIn('/', name)
        self.assertNotIn('\\', name)
        self.assertNotIn('..', name)
        self.assertTrue(name.endswith('.pkl'))
        self.assertEqual(name, os.path.basename(name))

    def test_failed_marker_extension(self):
        from dicom_handler.dicom_viewer_views import _roi_cache_filename

        name = _roi_cache_filename('../../x', '.failed')
        self.assertTrue(name.endswith('.failed'))
        self.assertEqual(name, os.path.basename(name))

    def test_deterministic_and_unique(self):
        from dicom_handler.dicom_viewer_views import _roi_cache_filename

        self.assertEqual(
            _roi_cache_filename('PTV', '.pkl'),
            _roi_cache_filename('PTV', '.pkl'),
        )
        self.assertNotEqual(
            _roi_cache_filename('PTV', '.pkl'),
            _roi_cache_filename('GTV', '.pkl'),
        )


class TaskIdFilenameTests(TestCase):
    """
    export.task_id is taken from the remote server response and interpolated
    into a download filename - it must be sanitized (CWE-22).
    """

    def test_task_id_traversal_sanitized(self):
        from dicom_handler.import_services.task1_poll_and_retrieve_rtstruct import (
            _sanitize_filename_component,
        )

        result = _sanitize_filename_component('../../etc/cron.d/x')
        self.assertNotIn('/', result)
        self.assertNotIn('..', result)

    def test_absolute_task_id_sanitized(self):
        from dicom_handler.import_services.task1_poll_and_retrieve_rtstruct import (
            _sanitize_filename_component,
        )

        result = _sanitize_filename_component('/etc/passwd')
        self.assertNotIn('/', result)

    def test_normal_task_id_unchanged(self):
        from dicom_handler.import_services.task1_poll_and_retrieve_rtstruct import (
            _sanitize_filename_component,
        )

        self.assertEqual(
            _sanitize_filename_component('a1b2c3-task_1234'),
            'a1b2c3-task_1234',
        )

    def test_empty_task_id_fallback(self):
        from dicom_handler.import_services.task1_poll_and_retrieve_rtstruct import (
            _sanitize_filename_component,
        )

        self.assertEqual(_sanitize_filename_component(''), 'unknown')
        self.assertEqual(_sanitize_filename_component('../../..'), 'unknown')
