"""
Regression tests for path traversal hardening in the C-STORE handler (CWE-22).

DICOM UIDs arrive over the network from arbitrary Storage SCUs, so every
UID-derived path component must be sanitized before hitting the filesystem.
"""

import os
import tempfile
import types

from django.test import TestCase

from dicom_handler.models import SystemConfiguration
from dicom_server.handlers.c_store_handler import (
    _get_filename,
    _get_storage_path,
    _path_within,
    _sanitize_dicom_uid,
    _sanitize_for_filesystem,
)
from dicom_server.models import DicomServerConfig


class SanitizeDicomUidTests(TestCase):
    def test_valid_uid_unchanged(self):
        uid = '1.2.840.10008.5.1.4.1.1.481.3'
        self.assertEqual(_sanitize_dicom_uid(uid), uid)

    def test_relative_traversal_sanitized(self):
        result = _sanitize_dicom_uid('../../etc/passwd')
        self.assertNotIn('/', result)
        self.assertNotIn('..', result)

    def test_absolute_path_sanitized(self):
        self.assertNotIn('/', _sanitize_dicom_uid('/etc/passwd'))

    def test_dotdot_component_not_returned(self):
        result = _sanitize_dicom_uid('..')
        self.assertNotEqual(result, '..')
        self.assertNotIn('..', result)

    def test_consecutive_dots_rejected(self):
        # '1.2..3' matches the digit/dot whitelist but contains a '..' segment
        result = _sanitize_dicom_uid('1.2..3')
        self.assertNotIn('..', result)

    def test_windows_separator_sanitized(self):
        self.assertNotIn('\\', _sanitize_dicom_uid('..\\..\\evil'))

    def test_null_byte_sanitized(self):
        self.assertNotIn('\x00', _sanitize_dicom_uid('1.2.3\x00../../x'))

    def test_empty_and_none(self):
        self.assertEqual(_sanitize_dicom_uid(''), 'UNKNOWN')
        self.assertEqual(_sanitize_dicom_uid(None), 'UNKNOWN')


class PathWithinTests(TestCase):
    def test_child_inside(self):
        with tempfile.TemporaryDirectory() as base:
            child = os.path.join(base, 'a', 'f.dcm')
            self.assertTrue(_path_within(child, base))

    def test_child_escapes(self):
        with tempfile.TemporaryDirectory() as base:
            child = os.path.join(base, '..', 'outside.dcm')
            self.assertFalse(_path_within(child, base))

    def test_sibling_prefix_is_not_inside(self):
        # /tmp/baseX must not count as inside /tmp/base
        with tempfile.TemporaryDirectory() as base:
            sibling = base.rstrip(os.sep) + '_sibling'
            self.assertFalse(_path_within(os.path.join(sibling, 'f.dcm'), base))


class StoragePathTraversalTests(TestCase):
    """_get_storage_path must keep malicious UIDs inside the storage root."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.addCleanup(self._cleanup_temp)
        SystemConfiguration.objects.create(folder_configuration=self.temp_dir)
        self.config = DicomServerConfig.objects.create(ae_title='TEST_SCP')

    def _cleanup_temp(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @staticmethod
    def _ds(**kwargs):
        return types.SimpleNamespace(**kwargs)

    def test_study_structure_traversal(self):
        self.config.storage_structure = 'study'
        ds = self._ds(StudyInstanceUID='../../tmp/evil')
        path = _get_storage_path(None, ds, self.config)
        self.assertTrue(_path_within(path, self.temp_dir))

    def test_series_structure_traversal(self):
        self.config.storage_structure = 'series'
        ds = self._ds(
            PatientID='P123',
            StudyInstanceUID='../../escape',
            SeriesInstanceUID='/absolute/path',
        )
        path = _get_storage_path(None, ds, self.config)
        self.assertTrue(_path_within(path, self.temp_dir))

    def test_series_structure_valid_uids_unchanged(self):
        self.config.storage_structure = 'series'
        ds = self._ds(
            PatientID='P123',
            StudyInstanceUID='1.2.3',
            SeriesInstanceUID='4.5.6',
        )
        path = _get_storage_path(None, ds, self.config)
        self.assertTrue(path.endswith(os.path.join('P123', '1.2.3', '4.5.6')))


class FilenameTraversalTests(TestCase):
    """_get_filename must never return a name containing path separators."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.addCleanup(self._cleanup_temp)
        SystemConfiguration.objects.create(folder_configuration=self.temp_dir)
        self.config = DicomServerConfig.objects.create(ae_title='TEST_SCP')

    def _cleanup_temp(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @staticmethod
    def _ds(**kwargs):
        return types.SimpleNamespace(**kwargs)

    def test_sop_uid_naming_traversal(self):
        self.config.file_naming_convention = 'sop_uid'
        ds = self._ds(SOPInstanceUID='../../etc/cron.d/evil')
        filename = _get_filename(None, ds, self.config)
        self.assertNotIn('/', filename)
        self.assertNotIn('..', filename)
        self.assertTrue(filename.endswith('.dcm'))
        self.assertEqual(filename, os.path.basename(filename))

    def test_default_fallback_traversal(self):
        # Unknown/missing naming convention still uses the SOP UID fallback
        self.config.file_naming_convention = 'bogus'
        ds = self._ds(SOPInstanceUID='../../../tmp/x')
        filename = _get_filename(None, ds, self.config)
        self.assertNotIn('/', filename)
        self.assertNotIn('..', filename)

    def test_joined_file_path_stays_in_storage(self):
        self.config.storage_structure = 'study'
        self.config.file_naming_convention = 'sop_uid'
        ds = self._ds(
            StudyInstanceUID='../../evil',
            SOPInstanceUID='../../evil_file',
        )
        storage_path = _get_storage_path(None, ds, self.config)
        filename = _get_filename(None, ds, self.config)
        file_path = os.path.join(storage_path, filename)
        self.assertTrue(_path_within(file_path, storage_path))
