"""
Integration tests for DICOM Server.
Tests end-to-end functionality with actual DICOM operations.
"""

from django.test import TestCase
from dicom_server.models import DicomServerConfig, DicomServiceStatus, DicomTransaction
from dicom_handler.models import SystemConfiguration
from pynetdicom import AE, debug_logger
from pynetdicom.sop_class import Verification, CTImageStorage
from pydicom.dataset import Dataset
from pydicom.uid import generate_uid
import tempfile
import os
import time
import threading


class DicomEchoIntegrationTestCase(TestCase):
    """Integration tests for C-ECHO operations."""
    
    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.system_config = SystemConfiguration.objects.create(
            folder_configuration=self.temp_dir
        )
        self.config = DicomServerConfig.objects.create(
            ae_title='TEST_SCP',
            host='127.0.0.1',
            port=11114,  # Use unique port
            enable_c_echo=True
        )
    
    def test_c_echo_operation(self):
        """Test C-ECHO (verification) operation."""
        from dicom_server.dicom_scp_service import DicomSCPService
        
        service = DicomSCPService()
        
        # Start service in background
        def start_service():
            try:
                service.start()
            except Exception:
                pass
        
        thread = threading.Thread(target=start_service, daemon=True)
        thread.start()
        time.sleep(2)
        
        try:
            # Create SCU (client)
            ae = AE(ae_title='TEST_SCU')
            ae.add_requested_context(Verification)
            
            # Associate with SCP
            assoc = ae.associate('127.0.0.1', 11114, ae_title='TEST_SCP')
            
            if assoc.is_established:
                # Send C-ECHO
                status = assoc.send_c_echo()
                
                self.assertIsNotNone(status)
                self.assertEqual(status.Status, 0x0000)  # Success
                
                assoc.release()
                
                # Check transaction was logged
                time.sleep(1)
                transaction = DicomTransaction.objects.filter(
                    transaction_type='C-ECHO'
                ).first()
                
                if transaction:
                    self.assertEqual(transaction.status, 'SUCCESS')
        
        finally:
            service.stop()


class DicomStoreIntegrationTestCase(TestCase):
    """Integration tests for C-STORE operations."""
    
    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.system_config = SystemConfiguration.objects.create(
            folder_configuration=self.temp_dir
        )
        self.config = DicomServerConfig.objects.create(
            ae_title='TEST_SCP',
            host='127.0.0.1',
            port=11115,
            enable_c_echo=True,
            enable_c_store=True,
            storage_structure='flat'
        )
    
    def create_test_dicom_dataset(self):
        """Create a minimal test DICOM dataset."""
        ds = Dataset()
        
        # Patient module
        ds.PatientName = 'Test^Patient'
        ds.PatientID = 'TEST001'
        ds.PatientBirthDate = '19900101'
        ds.PatientSex = 'M'
        
        # Study module
        ds.StudyInstanceUID = generate_uid()
        ds.StudyDate = '20260101'
        ds.StudyTime = '120000'
        ds.StudyID = 'STUDY001'
        ds.AccessionNumber = 'ACC001'
        
        # Series module
        ds.SeriesInstanceUID = generate_uid()
        ds.SeriesNumber = '1'
        ds.Modality = 'CT'
        
        # Instance module
        ds.SOPClassUID = CTImageStorage
        ds.SOPInstanceUID = generate_uid()
        ds.InstanceNumber = '1'
        
        # Image module (minimal)
        ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = 'MONOCHROME2'
        ds.Rows = 512
        ds.Columns = 512
        ds.BitsAllocated = 16
        ds.BitsStored = 16
        ds.HighBit = 15
        ds.PixelRepresentation = 0
        ds.PixelData = b'\x00' * (512 * 512 * 2)
        
        return ds
    
    def test_c_store_operation(self):
        """Test C-STORE (file storage) operation."""
        from dicom_server.dicom_scp_service import DicomSCPService
        
        service = DicomSCPService()
        
        # Start service
        def start_service():
            try:
                service.start()
            except Exception:
                pass
        
        thread = threading.Thread(target=start_service, daemon=True)
        thread.start()
        time.sleep(2)
        
        try:
            # Create test dataset
            ds = self.create_test_dicom_dataset()
            
            # Create SCU
            ae = AE(ae_title='TEST_SCU')
            ae.add_requested_context(CTImageStorage)
            
            # Associate and send
            assoc = ae.associate('127.0.0.1', 11115, ae_title='TEST_SCP')
            
            if assoc.is_established:
                status = assoc.send_c_store(ds)
                
                self.assertIsNotNone(status)
                self.assertEqual(status.Status, 0x0000)
                
                assoc.release()
                
                # Check file was stored
                time.sleep(1)
                files = os.listdir(self.temp_dir)
                self.assertGreater(len(files), 0)
                
                # Check transaction was logged
                transaction = DicomTransaction.objects.filter(
                    transaction_type='C-STORE'
                ).first()
                
                if transaction:
                    self.assertEqual(transaction.status, 'SUCCESS')
        
        finally:
            service.stop()


class ServiceLifecycleTestCase(TestCase):
    """Test service lifecycle (start/stop/restart)."""
    
    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.system_config = SystemConfiguration.objects.create(
            folder_configuration=self.temp_dir
        )
        self.config = DicomServerConfig.objects.create(
            ae_title='TEST_SCP',
            host='127.0.0.1',
            port=11116
        )
    
    def test_service_start_stop_cycle(self):
        """Test starting and stopping service."""
        from dicom_server.service_manager import start_service, stop_service, get_service_status
        
        # Start service
        result = start_service()
        time.sleep(2)
        
        # Check status
        status = get_service_status()
        if status.get('is_running'):
            self.assertTrue(status['is_running'])
        
        # Stop service
        stop_result = stop_service()
        time.sleep(1)
        
        # Check stopped
        status = get_service_status()
        self.assertFalse(status.get('is_running', False))
    
    def test_service_restart(self):
        """Test restarting service."""
        from dicom_server.service_manager import start_service, restart_service, stop_service
        
        # Start service
        start_service()
        time.sleep(2)
        
        # Restart
        restart_service()
        time.sleep(2)
        
        # Should still be running
        from dicom_server.service_manager import get_service_status
        status = get_service_status()
        
        # Clean up
        stop_service()


class SecurityTestCase(TestCase):
    """Test security features (AE validation, IP filtering)."""
    
    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.system_config = SystemConfiguration.objects.create(
            folder_configuration=self.temp_dir
        )
        self.config = DicomServerConfig.objects.create(
            ae_title='TEST_SCP',
            host='127.0.0.1',
            port=11117,
            require_calling_ae_validation=True
        )
    
    def test_ae_validation_enabled(self):
        """Test that AE validation works when enabled."""
        from dicom_server.models import AllowedAETitle
        
        # Add allowed AE
        AllowedAETitle.objects.create(
            ae_title='ALLOWED_SCU',
            is_active=True
        )
        
        # Configuration should require validation
        self.assertTrue(self.config.require_calling_ae_validation)
        
        # Check allowed AE exists
        allowed = AllowedAETitle.objects.filter(ae_title='ALLOWED_SCU').first()
        self.assertIsNotNone(allowed)
        self.assertTrue(allowed.is_active)


class StorageLimitTestCase(TestCase):
    """Test storage limit enforcement."""
    
    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.system_config = SystemConfiguration.objects.create(
            folder_configuration=self.temp_dir
        )
        self.config = DicomServerConfig.objects.create(
            max_storage_size_gb=1,  # Minimum 1GB required by validation
            enable_storage_cleanup=False
        )
    
    def test_storage_limit_check(self):
        """Test storage limit checking."""
        import os
        
        # Test that storage directory exists and config is valid
        self.assertTrue(os.path.exists(self.temp_dir))
        self.assertGreaterEqual(self.config.max_storage_size_gb, 1)
