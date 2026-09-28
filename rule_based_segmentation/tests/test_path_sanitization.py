"""
Regression tests for path traversal hardening in the image-series importer
and RTStruct upload paths (CWE-22).

Uploaded filenames and DICOM UID tags are attacker-controlled; they must never
reach the filesystem unsanitized.
"""

import os
import tempfile
from unittest.mock import MagicMock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from dicom_handler.models import SystemConfiguration
from ..utils.dicom_image_importer import (
    _copy_datasets_to_directory,
    _get_series_target_directory,
    _safe_uid_component,
    _save_uploaded_files,
    sanitize_filename_component,
)


class SanitizeFilenameComponentTests(TestCase):
    def test_plain_name(self):
        self.assertEqual(sanitize_filename_component('scan_001.dcm'), 'scan_001.dcm')

    def test_relative_traversal_reduced_to_basename(self):
        self.assertEqual(sanitize_filename_component('../../etc/passwd'), 'passwd')

    def test_absolute_path_reduced_to_basename(self):
        self.assertEqual(sanitize_filename_component('/etc/passwd'), 'passwd')

    def test_windows_separator(self):
        self.assertEqual(sanitize_filename_component('..\\..\\evil.dcm'), 'evil.dcm')

    def test_dotdot_rejected(self):
        self.assertEqual(sanitize_filename_component('..'), '')
        self.assertEqual(sanitize_filename_component('...'), '')

    def test_empty_and_none(self):
        self.assertEqual(sanitize_filename_component(''), '')
        self.assertEqual(sanitize_filename_component(None), '')

    def test_null_byte_removed(self):
        self.assertEqual(sanitize_filename_component('a\x00b.dcm'), 'ab.dcm')


class SafeUidComponentTests(TestCase):
    def test_valid_uid(self):
        self.assertEqual(_safe_uid_component('1.2.840.1'), '1.2.840.1')

    def test_traversal_falls_back(self):
        self.assertEqual(_safe_uid_component('../../evil', 'FB'), 'FB')

    def test_consecutive_dots_fall_back(self):
        self.assertEqual(_safe_uid_component('1.2..3', 'FB'), 'FB')

    def test_absolute_falls_back(self):
        self.assertEqual(_safe_uid_component('/abs/path', 'FB'), 'FB')

    def test_none_falls_back(self):
        self.assertIsNone(_safe_uid_component(None))
        self.assertIsNone(_safe_uid_component(''))


class SaveUploadedFilesTests(TestCase):
    def test_malicious_name_stays_in_target_dir(self):
        base = tempfile.mkdtemp()
        try:
            target = os.path.join(base, 'a', 'b')
            os.makedirs(target)

            upload = SimpleUploadedFile('../escaped.dcm', b'dicom-bytes')
            _save_uploaded_files([upload], target)

            escaped = os.path.join(base, 'a', 'escaped.dcm')
            self.assertFalse(os.path.exists(escaped))
            self.assertTrue(os.path.exists(os.path.join(target, 'escaped.dcm')))
        finally:
            import shutil
            shutil.rmtree(base, ignore_errors=True)

    def test_absolute_name_stays_in_target_dir(self):
        with tempfile.TemporaryDirectory() as target:
            upload = SimpleUploadedFile('/etc/payload.dcm', b'dicom-bytes')
            _save_uploaded_files([upload], target)
            self.assertTrue(os.path.exists(os.path.join(target, 'payload.dcm')))

    def test_dangerous_name_gets_fallback(self):
        with tempfile.TemporaryDirectory() as target:
            upload = SimpleUploadedFile('..', b'dicom-bytes')
            _save_uploaded_files([upload], target)
            self.assertTrue(os.path.exists(os.path.join(target, 'upload_0000')))


class SeriesTargetDirectoryTests(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.addCleanup(self._cleanup_temp)
        SystemConfiguration.objects.create(folder_configuration=self.temp_dir)

    def _cleanup_temp(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_invalid_series_uid_raises(self):
        with self.assertRaises(ValueError):
            _get_series_target_directory('../../evil')

    def test_valid_uid_stays_inside_base(self):
        path = _get_series_target_directory('1.2.3.4')
        self.assertTrue(
            os.path.realpath(path).startswith(os.path.realpath(self.temp_dir) + os.sep)
        )

    def test_copy_datasets_sanitizes_sop_uid(self):
        with tempfile.TemporaryDirectory() as target:
            ds = MagicMock()
            ds.SOPInstanceUID = '../../evil'
            _copy_datasets_to_directory([ds], target)

            saved_path = ds.save_as.call_args[0][0]
            self.assertTrue(
                os.path.realpath(saved_path).startswith(
                    os.path.realpath(target) + os.sep
                )
            )
            self.assertTrue(saved_path.endswith('instance_0000.dcm'))
