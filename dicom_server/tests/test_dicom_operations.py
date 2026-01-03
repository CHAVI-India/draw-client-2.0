"""
Test suite for actual DICOM file operations.
Tests real DICOM file handling, parsing, storage, and retrieval.
"""

from django.test import TestCase
from dicom_server.models import DicomServerConfig, DicomTransaction
from dicom_handler.models import SystemConfiguration
from pydicom.dataset import Dataset, FileDataset
from pydicom.uid import generate_uid, CTImageStorage, MRImageStorage
from pydicom import dcmwrite, dcmread
import tempfile
import os
import datetime


class DicomFileCreationTestCase(TestCase):
    """Test DICOM file creation and validation."""
    
    def setUp(self):
        """Set up test data."""
        self.temp_dir = tempfile.mkdtemp()
        self.system_config = SystemConfiguration.objects.create(
            folder_configuration=self.temp_dir
        )
    
    def create_valid_ct_dicom(self, filename):
        """Create a valid CT DICOM file for testing."""
        # Create file meta information
        file_meta = Dataset()
        file_meta.MediaStorageSOPClassUID = CTImageStorage
        file_meta.MediaStorageSOPInstanceUID = generate_uid()
        file_meta.TransferSyntaxUID = '1.2.840.10008.1.2.1'  # Explicit VR Little Endian
        file_meta.ImplementationClassUID = generate_uid()
        
        # Create the FileDataset instance
        ds = FileDataset(filename, {}, file_meta=file_meta, preamble=b"\0" * 128)
        
        # Add required DICOM elements
        ds.PatientName = 'Test^Patient^CT'
        ds.PatientID = 'CT12345'
        ds.PatientBirthDate = '19850315'
        ds.PatientSex = 'F'
        ds.PatientAge = '038Y'
        
        ds.StudyInstanceUID = generate_uid()
        ds.SeriesInstanceUID = generate_uid()
        ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
        ds.SOPClassUID = CTImageStorage
        
        ds.StudyDate = '20260103'
        ds.StudyTime = '120000'
        ds.SeriesDate = '20260103'
        ds.SeriesTime = '120500'
        ds.ContentDate = '20260103'
        ds.ContentTime = '120500'
        
        ds.AccessionNumber = 'ACC001'
        ds.StudyID = 'STUDY001'
        ds.SeriesNumber = '1'
        ds.InstanceNumber = '1'
        
        ds.Modality = 'CT'
        ds.Manufacturer = 'Test Manufacturer'
        ds.InstitutionName = 'Test Hospital'
        ds.StudyDescription = 'Test CT Study'
        ds.SeriesDescription = 'Test CT Series'
        
        # Image-specific attributes
        ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = 'MONOCHROME2'
        ds.Rows = 512
        ds.Columns = 512
        ds.BitsAllocated = 16
        ds.BitsStored = 16
        ds.HighBit = 15
        ds.PixelRepresentation = 0
        
        # Add pixel data (512x512x2 bytes = 524288 bytes)
        ds.PixelData = b'\x00' * (512 * 512 * 2)
        
        # Additional CT-specific tags
        ds.ImagePositionPatient = [0, 0, 0]
        ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
        ds.SliceThickness = '5.0'
        ds.PixelSpacing = [0.5, 0.5]
        
        return ds
    
    def create_valid_mr_dicom(self, filename):
        """Create a valid MR DICOM file for testing."""
        file_meta = Dataset()
        file_meta.MediaStorageSOPClassUID = MRImageStorage
        file_meta.MediaStorageSOPInstanceUID = generate_uid()
        file_meta.TransferSyntaxUID = '1.2.840.10008.1.2.1'
        file_meta.ImplementationClassUID = generate_uid()
        
        ds = FileDataset(filename, {}, file_meta=file_meta, preamble=b"\0" * 128)
        
        ds.PatientName = 'Test^Patient^MR'
        ds.PatientID = 'MR67890'
        ds.PatientBirthDate = '19920710'
        ds.PatientSex = 'M'
        ds.PatientAge = '033Y'
        
        ds.StudyInstanceUID = generate_uid()
        ds.SeriesInstanceUID = generate_uid()
        ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
        ds.SOPClassUID = MRImageStorage
        
        ds.StudyDate = '20260103'
        ds.StudyTime = '140000'
        ds.SeriesDate = '20260103'
        ds.SeriesTime = '140500'
        
        ds.AccessionNumber = 'ACC002'
        ds.StudyID = 'STUDY002'
        ds.SeriesNumber = '2'
        ds.InstanceNumber = '1'
        
        ds.Modality = 'MR'
        ds.Manufacturer = 'Test MR Manufacturer'
        ds.InstitutionName = 'Test Hospital'
        ds.StudyDescription = 'Test MR Study'
        ds.SeriesDescription = 'Test MR Series'
        
        ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = 'MONOCHROME2'
        ds.Rows = 256
        ds.Columns = 256
        ds.BitsAllocated = 16
        ds.BitsStored = 16
        ds.HighBit = 15
        ds.PixelRepresentation = 0
        ds.PixelData = b'\x00' * (256 * 256 * 2)
        
        # MR-specific tags
        ds.ImagePositionPatient = [0, 0, 0]
        ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
        ds.SliceThickness = '3.0'
        ds.PixelSpacing = [0.8, 0.8]
        ds.EchoTime = '30'
        ds.RepetitionTime = '500'
        ds.MagneticFieldStrength = '1.5'
        
        return ds
    
    def test_create_ct_dicom_file(self):
        """Test creating a valid CT DICOM file."""
        filepath = os.path.join(self.temp_dir, 'test_ct.dcm')
        ds = self.create_valid_ct_dicom(filepath)
        
        # Write to file
        dcmwrite(filepath, ds)
        
        # Verify file exists
        self.assertTrue(os.path.exists(filepath))
        
        # Read back and verify
        ds_read = dcmread(filepath)
        self.assertEqual(ds_read.PatientID, 'CT12345')
        self.assertEqual(ds_read.Modality, 'CT')
        self.assertEqual(ds_read.Rows, 512)
        self.assertEqual(ds_read.Columns, 512)
    
    def test_create_mr_dicom_file(self):
        """Test creating a valid MR DICOM file."""
        filepath = os.path.join(self.temp_dir, 'test_mr.dcm')
        ds = self.create_valid_mr_dicom(filepath)
        
        dcmwrite(filepath, ds)
        
        self.assertTrue(os.path.exists(filepath))
        
        ds_read = dcmread(filepath)
        self.assertEqual(ds_read.PatientID, 'MR67890')
        self.assertEqual(ds_read.Modality, 'MR')
        self.assertEqual(ds_read.Rows, 256)
        self.assertEqual(ds_read.Columns, 256)
    
    def test_dicom_file_validation(self):
        """Test DICOM file validation."""
        filepath = os.path.join(self.temp_dir, 'test_validation.dcm')
        ds = self.create_valid_ct_dicom(filepath)
        dcmwrite(filepath, ds)
        
        # Read and validate required tags
        ds_read = dcmread(filepath)
        
        # Patient module
        self.assertIsNotNone(ds_read.PatientName)
        self.assertIsNotNone(ds_read.PatientID)
        
        # Study module
        self.assertIsNotNone(ds_read.StudyInstanceUID)
        self.assertIsNotNone(ds_read.StudyDate)
        
        # Series module
        self.assertIsNotNone(ds_read.SeriesInstanceUID)
        self.assertIsNotNone(ds_read.Modality)
        
        # Instance module
        self.assertIsNotNone(ds_read.SOPInstanceUID)
        self.assertIsNotNone(ds_read.SOPClassUID)
        self.assertIsNotNone(ds_read.InstanceNumber)


class DicomFileStorageTestCase(TestCase):
    """Test DICOM file storage operations."""
    
    def setUp(self):
        """Set up test data."""
        self.temp_dir = tempfile.mkdtemp()
        self.system_config = SystemConfiguration.objects.create(
            folder_configuration=self.temp_dir
        )
        self.config = DicomServerConfig.objects.create(
            storage_structure='series',
            file_naming_convention='sop_uid'
        )
    
    def test_storage_structure_flat(self):
        """Test flat storage structure."""
        self.config.storage_structure = 'flat'
        self.config.save()
        
        # Verify storage structure
        self.assertEqual(self.config.storage_structure, 'flat')
    
    def test_storage_structure_series(self):
        """Test series-based storage structure."""
        self.config.storage_structure = 'series'
        self.config.save()
        
        self.assertEqual(self.config.storage_structure, 'series')
    
    def test_file_naming_sop_uid(self):
        """Test SOP UID file naming."""
        self.config.file_naming_convention = 'sop_uid'
        self.config.save()
        
        self.assertEqual(self.config.file_naming_convention, 'sop_uid')
    
    def test_file_naming_instance_number(self):
        """Test instance number file naming."""
        self.config.file_naming_convention = 'instance_number'
        self.config.save()
        
        self.assertEqual(self.config.file_naming_convention, 'instance_number')


class DicomTransactionLoggingTestCase(TestCase):
    """Test DICOM transaction logging."""
    
    def setUp(self):
        """Set up test data."""
        self.temp_dir = tempfile.mkdtemp()
        self.system_config = SystemConfiguration.objects.create(
            folder_configuration=self.temp_dir
        )
        self.config = DicomServerConfig.objects.create()
    
    def test_log_c_store_transaction(self):
        """Test logging C-STORE transaction."""
        transaction = DicomTransaction.objects.create(
            transaction_type='C-STORE',
            calling_ae_title='CT_SCANNER',
            called_ae_title='DRAW_SCP',
            remote_ip='192.168.1.100',
            remote_port=11112,
            status='SUCCESS',
            patient_id='TEST001',
            study_instance_uid='1.2.3.4.5',
            series_instance_uid='1.2.3.4.5.6',
            sop_instance_uid='1.2.3.4.5.6.7',
            sop_class_uid=CTImageStorage,
            file_size_bytes=524288,
            file_path='/storage/test.dcm'
        )
        
        self.assertEqual(transaction.transaction_type, 'C-STORE')
        self.assertEqual(transaction.patient_id, 'TEST001')
        self.assertEqual(transaction.file_size_bytes, 524288)
        self.assertIsNotNone(transaction.timestamp)
    
    def test_transaction_query_by_patient(self):
        """Test querying transactions by patient ID."""
        DicomTransaction.objects.create(
            transaction_type='C-STORE',
            calling_ae_title='TEST',
            called_ae_title='DRAW_SCP',
            remote_ip='127.0.0.1',
            remote_port=11112,
            status='SUCCESS',
            patient_id='PATIENT001'
        )
        
        transactions = DicomTransaction.objects.filter(patient_id='PATIENT001')
        self.assertEqual(transactions.count(), 1)
        self.assertEqual(transactions.first().patient_id, 'PATIENT001')
    
    def test_transaction_query_by_modality(self):
        """Test querying transactions by SOP class (modality)."""
        DicomTransaction.objects.create(
            transaction_type='C-STORE',
            calling_ae_title='TEST',
            called_ae_title='DRAW_SCP',
            remote_ip='127.0.0.1',
            remote_port=11112,
            status='SUCCESS',
            sop_class_uid=CTImageStorage
        )
        
        transactions = DicomTransaction.objects.filter(sop_class_uid=CTImageStorage)
        self.assertEqual(transactions.count(), 1)


class DicomFileMetadataTestCase(TestCase):
    """Test DICOM file metadata extraction."""
    
    def setUp(self):
        """Set up test data."""
        self.temp_dir = tempfile.mkdtemp()
        self.system_config = SystemConfiguration.objects.create(
            folder_configuration=self.temp_dir
        )
    
    def test_extract_patient_info(self):
        """Test extracting patient information from DICOM."""
        ds = Dataset()
        ds.PatientName = 'Doe^John^A'
        ds.PatientID = 'PAT123'
        ds.PatientBirthDate = '19800515'
        ds.PatientSex = 'M'
        
        self.assertEqual(ds.PatientName, 'Doe^John^A')
        self.assertEqual(ds.PatientID, 'PAT123')
        self.assertEqual(ds.PatientBirthDate, '19800515')
        self.assertEqual(ds.PatientSex, 'M')
    
    def test_extract_study_info(self):
        """Test extracting study information from DICOM."""
        ds = Dataset()
        ds.StudyInstanceUID = '1.2.3.4.5'
        ds.StudyDate = '20260103'
        ds.StudyTime = '143000'
        ds.StudyDescription = 'CT Chest'
        ds.AccessionNumber = 'ACC123'
        
        self.assertEqual(ds.StudyInstanceUID, '1.2.3.4.5')
        self.assertEqual(ds.StudyDate, '20260103')
        self.assertEqual(ds.StudyDescription, 'CT Chest')
    
    def test_extract_series_info(self):
        """Test extracting series information from DICOM."""
        ds = Dataset()
        ds.SeriesInstanceUID = '1.2.3.4.5.6'
        ds.SeriesNumber = '1'
        ds.Modality = 'CT'
        ds.SeriesDescription = 'Axial CT'
        
        self.assertEqual(ds.SeriesInstanceUID, '1.2.3.4.5.6')
        self.assertEqual(ds.Modality, 'CT')
        self.assertEqual(ds.SeriesDescription, 'Axial CT')
