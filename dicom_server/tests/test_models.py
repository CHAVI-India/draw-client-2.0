"""
Test suite for DICOM Server models.
"""

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from dicom_server.models import (
    DicomServerConfig,
    DicomServiceStatus,
    AllowedAETitle,
    DicomTransaction
)
from dicom_handler.models import SystemConfiguration
import tempfile
import os

User = get_user_model()


class DicomServerConfigTestCase(TestCase):
    """Test DicomServerConfig model."""
    
    def setUp(self):
        """Set up test data."""
        self.temp_dir = tempfile.mkdtemp()
        self.system_config = SystemConfiguration.objects.create(
            folder_configuration=self.temp_dir
        )
    
    def test_create_default_config(self):
        """Test creating config with default values."""
        config = DicomServerConfig.objects.create()
        
        self.assertEqual(config.ae_title, 'DRAW_SCP')
        self.assertEqual(config.host, '0.0.0.0')
        self.assertEqual(config.port, 11112)
        self.assertEqual(config.max_associations, 10)
        self.assertTrue(config.enable_c_echo)
        self.assertTrue(config.enable_c_store)
    
    def test_ae_title_validation(self):
        """Test AE title validation (max 16 chars, uppercase)."""
        config = DicomServerConfig.objects.create()
        
        # Valid AE title
        config.ae_title = 'TEST_SCP'
        config.full_clean()
        
        # Too long (>16 chars)
        config.ae_title = 'THIS_IS_TOO_LONG_AE_TITLE'
        with self.assertRaises(ValidationError):
            config.full_clean()
    
    def test_port_validation(self):
        """Test port number validation."""
        config = DicomServerConfig.objects.create()
        
        # Valid port
        config.port = 11112
        config.full_clean()
        
        # Invalid port (too low)
        config.port = 100
        with self.assertRaises(ValidationError):
            config.full_clean()
        
        # Invalid port (too high)
        config.port = 70000
        with self.assertRaises(ValidationError):
            config.full_clean()
    
    def test_storage_usage_calculation(self):
        """Test storage usage calculation."""
        config = DicomServerConfig.objects.create()
        
        # Should return 0 or actual usage
        usage = config.storage_usage_gb
        self.assertIsInstance(usage, (int, float))
        self.assertGreaterEqual(usage, 0)
    
    def test_singleton_pattern(self):
        """Test that only one config instance can exist."""
        config1 = DicomServerConfig.objects.create()
        
        # Attempting to create another should raise validation error
        with self.assertRaises(Exception):
            config2 = DicomServerConfig.objects.create()
        
        # Should only have one config
        self.assertEqual(DicomServerConfig.objects.count(), 1)


class DicomServiceStatusTestCase(TestCase):
    """Test DicomServiceStatus model."""
    
    def setUp(self):
        """Set up test data."""
        self.temp_dir = tempfile.mkdtemp()
        self.system_config = SystemConfiguration.objects.create(
            folder_configuration=self.temp_dir
        )
    
    def test_create_status(self):
        """Test creating service status."""
        status = DicomServiceStatus.objects.create(
            is_running=True,
            process_id=12345
        )
        
        self.assertTrue(status.is_running)
        self.assertEqual(status.process_id, 12345)
        self.assertEqual(status.total_connections, 0)
        self.assertEqual(status.total_files_received, 0)
    
    def test_increment_counters(self):
        """Test incrementing statistics counters."""
        status = DicomServiceStatus.objects.create(
            is_running=True
        )
        
        # Increment counters
        status.total_connections += 1
        status.total_files_received += 1
        status.total_bytes_received += 1024
        status.save()
        
        status.refresh_from_db()
        self.assertEqual(status.total_connections, 1)
        self.assertEqual(status.total_files_received, 1)
        self.assertEqual(status.total_bytes_received, 1024)
    
    def test_average_file_size_calculation(self):
        """Test average file size calculation."""
        status = DicomServiceStatus.objects.create(
            is_running=True,
            total_files_received=10,
            total_bytes_received=10485760  # 10 MB
        )
        
        avg_size = status.average_file_size_mb
        self.assertAlmostEqual(avg_size, 1.0, places=1)
    
    def test_average_file_size_zero_files(self):
        """Test average file size with zero files."""
        status = DicomServiceStatus.objects.create(
            is_running=True,
            total_files_received=0
        )
        
        avg_size = status.average_file_size_mb
        self.assertEqual(avg_size, 0)


class AllowedAETestCase(TestCase):
    """Test AllowedAETitle model."""
    
    def test_create_allowed_ae(self):
        """Test creating allowed AE title."""
        ae = AllowedAETitle.objects.create(
            ae_title='CT_SCANNER',
            description='CT Scanner Room 1',
            ip_address='192.168.1.100',
            is_active=True
        )
        
        self.assertEqual(ae.ae_title, 'CT_SCANNER')
        self.assertTrue(ae.is_active)
        self.assertIn('CT_SCANNER', str(ae))
    
    def test_ae_title_uniqueness(self):
        """Test that AE titles must be unique."""
        AllowedAETitle.objects.create(ae_title='TEST_AE')
        
        with self.assertRaises(Exception):
            AllowedAETitle.objects.create(ae_title='TEST_AE')
    
    def test_ae_title_validation(self):
        """Test AE title validation."""
        ae = AllowedAETitle(ae_title='VALID_AE')
        ae.full_clean()
        
        # Too long
        ae.ae_title = 'THIS_IS_TOO_LONG_AE_TITLE'
        with self.assertRaises(ValidationError):
            ae.full_clean()


class DicomTransactionTestCase(TestCase):
    """Test DicomTransaction model."""
    
    def setUp(self):
        """Set up test data."""
        self.temp_dir = tempfile.mkdtemp()
        self.system_config = SystemConfiguration.objects.create(
            folder_configuration=self.temp_dir
        )
    
    def test_create_transaction(self):
        """Test creating a transaction log entry."""
        transaction = DicomTransaction.objects.create(
            transaction_type='C-STORE',
            calling_ae_title='CT_SCANNER',
            called_ae_title='DRAW_SCP',
            remote_ip='192.168.1.100',
            remote_port=11112,
            status='SUCCESS'
        )
        
        self.assertEqual(transaction.transaction_type, 'C-STORE')
        self.assertEqual(transaction.status, 'SUCCESS')
        self.assertIsNotNone(transaction.timestamp)
    
    def test_transaction_with_file_info(self):
        """Test transaction with file information."""
        transaction = DicomTransaction.objects.create(
            transaction_type='C-STORE',
            calling_ae_title='MR_SCANNER',
            called_ae_title='DRAW_SCP',
            remote_ip='192.168.1.101',
            remote_port=11112,
            status='SUCCESS',
            patient_id='PAT001',
            study_instance_uid='1.2.3.4.5',
            series_instance_uid='1.2.3.4.5.6',
            sop_instance_uid='1.2.3.4.5.6.7',
            file_size_bytes=1048576
        )
        
        self.assertEqual(transaction.patient_id, 'PAT001')
        self.assertEqual(transaction.file_size_bytes, 1048576)
    
    def test_transaction_ordering(self):
        """Test that transactions are ordered by timestamp descending."""
        t1 = DicomTransaction.objects.create(
            transaction_type='C-ECHO',
            calling_ae_title='TEST',
            called_ae_title='DRAW_SCP',
            remote_ip='127.0.0.1',
            remote_port=11112,
            status='SUCCESS'
        )
        t2 = DicomTransaction.objects.create(
            transaction_type='C-STORE',
            calling_ae_title='TEST',
            called_ae_title='DRAW_SCP',
            remote_ip='127.0.0.1',
            remote_port=11112,
            status='SUCCESS'
        )
        
        transactions = DicomTransaction.objects.all()
        self.assertEqual(transactions[0].transaction_id, t2.transaction_id)  # Most recent first
    
    def test_transaction_string_representation(self):
        """Test transaction string representation."""
        transaction = DicomTransaction.objects.create(
            transaction_type='C-STORE',
            calling_ae_title='TEST_AE',
            called_ae_title='DRAW_SCP',
            remote_ip='127.0.0.1',
            remote_port=11112,
            status='SUCCESS'
        )
        
        str_repr = str(transaction)
        self.assertIn('C-STORE', str_repr)
        self.assertIn('TEST_AE', str_repr)
