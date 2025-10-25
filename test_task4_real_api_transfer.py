#!/usr/bin/env python
"""
Real API Transfer Test for task4_export_series_to_api.py
This script tests actual file transfer to a real DRAW API server.
Configure the API endpoints and tokens in SystemConfiguration before running.

IMPORTANT: This test uses a SEPARATE TEST DATABASE that is automatically created
and destroyed. Your production database will NOT be affected.
"""

import os
import sys
import django
import tempfile
import zipfile
import json
from pathlib import Path
from datetime import timedelta

# Add the project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'draw_client.settings')
django.setup()

# Now import Django models and the function to test
from dicom_handler.models import (
    SystemConfiguration, Patient, DICOMStudy, DICOMSeries, DICOMInstance,
    ProcessingStatus, DICOMFileExport, DICOMFileTransferStatus
)
from dicom_handler.export_services.task4_export_series_to_api import (
    export_series_to_api, check_api_health, calculate_file_checksum,
    upload_file_to_api
)
from dicom_handler.utils.proxy_configuration import get_session_with_proxy
from django.utils import timezone
from django.db import transaction
from django.test.utils import setup_test_environment, teardown_test_environment
from django.db import connections
from django.conf import settings

# Global variable to track test database
_test_db_name = None

def create_test_database():
    """
    Create a separate test database for testing
    Returns the test database name
    """
    global _test_db_name
    
    print("\n" + "="*70)
    print("CREATING SEPARATE TEST DATABASE")
    print("="*70)
    
    setup_test_environment()
    connection = connections['default']
    _test_db_name = connection.creation.create_test_db(
        verbosity=1,
        autoclobber=True,
        keepdb=False
    )
    
    print(f"✓ Test database created: {_test_db_name}")
    print(f"✓ Production database is safe and untouched")
    print("="*70)
    
    return _test_db_name

def destroy_test_database():
    """
    Destroy the test database after testing
    """
    global _test_db_name
    
    if _test_db_name is None:
        return
    
    print("\n" + "="*70)
    print("DESTROYING TEST DATABASE")
    print("="*70)
    
    connection = connections['default']
    connection.creation.destroy_test_db(_test_db_name, verbosity=1)
    teardown_test_environment()
    
    print(f"✓ Test database destroyed: {_test_db_name}")
    print(f"✓ Production database remains unchanged")
    print("="*70)
    
    _test_db_name = None

def create_test_zip_file():
    """
    Create a test ZIP file with sample DICOM-like content
    Returns: Path to the created ZIP file
    """
    # Create a temporary directory and ZIP file
    temp_dir = tempfile.mkdtemp()
    zip_path = os.path.join(temp_dir, "real_test_series.zip")
    
    # Create sample files to simulate a deidentified DICOM series
    test_files = {
        "CT001.dcm": b"DICM\x00\x00\x00\x00" + b"Sample DICOM content for CT slice 1" * 100,
        "CT002.dcm": b"DICM\x00\x00\x00\x00" + b"Sample DICOM content for CT slice 2" * 100,
        "CT003.dcm": b"DICM\x00\x00\x00\x00" + b"Sample DICOM content for CT slice 3" * 100,
        "autosegmentation_template.yml": b"""
name: "Test Template"
protocol: "DRAW"
models:
  1:
    name: "Test Model"
    config: "test_config"
    trainer_name: "test_trainer"
    postprocess: "test_postprocess"
    map:
      1: "Structure1"
      2: "Structure2"
"""
    }
    
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for filename, content in test_files.items():
            zipf.writestr(filename, content)
    
    file_size = os.path.getsize(zip_path)
    print(f"Created test ZIP file: {zip_path}")
    print(f"File size: {file_size:,} bytes")
    return zip_path

def check_configuration():
    """
    Check if the system configuration has valid API settings
    Returns: SystemConfiguration object or None
    """
    print("Checking existing system configuration...")
    
    config = SystemConfiguration.get_singleton()
    if not config:
        print("❌ No system configuration found")
        return None
    
    print(f"Using existing configuration:")
    print(f"  - Base URL: {config.draw_base_url}")
    print(f"  - Upload Endpoint: {config.draw_upload_endpoint}")
    print(f"  - Bearer Token: {'✅ Present' if config.draw_bearer_token else '❌ Missing'}")
    print(f"  - Refresh Token: {'✅ Present' if config.draw_refresh_token else '❌ Missing'}")
    print(f"  - Token Validity: {config.draw_bearer_token_validaty}")
    
    if not config.draw_base_url:
        print("❌ Base URL not configured")
        return None
    
    if not config.draw_bearer_token:
        print("❌ Bearer token not configured")
        return None
    
    print("✅ Configuration validation passed - using your configured settings")
    return config

def test_real_api_health_check():
    """
    Test the actual API health check endpoint
    """
    print("\n=== Testing Real API Health Check ===")
    
    config = check_configuration()
    if not config:
        return False
    
    session = get_session_with_proxy()
    
    try:
        result = check_api_health(config.draw_base_url, session)
        if result:
            print("✅ API health check passed - server is ready")
            return True
        else:
            print("❌ API health check failed - server not ready")
            return False
    except Exception as e:
        print(f"❌ API health check error: {str(e)}")
        return False

def test_real_file_upload():
    """
    Test actual file upload to the real API
    """
    print("\n=== Testing Real File Upload ===")
    
    config = check_configuration()
    if not config:
        return False
    
    # Create test ZIP file
    test_zip = create_test_zip_file()
    
    try:
        # Calculate checksum
        checksum = calculate_file_checksum(test_zip)
        if not checksum:
            print("❌ Failed to calculate file checksum")
            return False
        
        print(f"File checksum: {checksum}")
        
        # Create session with proxy configuration
        session = get_session_with_proxy()
        
        # Attempt upload
        print("Attempting file upload to real API...")
        result = upload_file_to_api(test_zip, checksum, config, session)
        
        if result['success']:
            print(f"✅ File upload successful!")
            print(f"Task ID: {result['task_id']}")
            print(f"Response data: {result.get('response_data', {})}")
            return True
        else:
            print(f"❌ File upload failed: {result.get('error', 'Unknown error')}")
            if 'response' in result:
                print(f"Server response: {result['response']}")
            return False
            
    except Exception as e:
        print(f"❌ Upload test error: {str(e)}")
        return False
    finally:
        # Cleanup test file
        if os.path.exists(test_zip):
            os.remove(test_zip)
            os.rmdir(os.path.dirname(test_zip))

def create_test_database_records():
    """
    Create minimal test database records for full workflow test
    """
    print("Creating test database records...")
    
    with transaction.atomic():
        # Create patient
        patient = Patient.objects.create(
            patient_id="REAL_TEST_PATIENT_001",
            patient_name="Real Test Patient",
            patient_gender="F"
        )
        
        # Create study
        study = DICOMStudy.objects.create(
            patient=patient,
            study_instance_uid="1.2.3.4.5.6.7.8.9.10.11.12.13.14.100",
            study_description="Real Test Study"
        )
        
        # Create series
        series = DICOMSeries.objects.create(
            study=study,
            series_instance_uid="1.2.3.4.5.6.7.8.9.10.11.12.13.14.101",
            deidentified_series_instance_uid="1.2.826.0.1.3680043.10.1561.999.88.777.1",
            series_processsing_status=ProcessingStatus.DEIDENTIFIED_SUCCESSFULLY
        )
        
        # Create export record (will be updated with real ZIP path)
        export_record = DICOMFileExport.objects.create(
            deidentified_series_instance_uid=series,
            deidentified_zip_file_transfer_status=DICOMFileTransferStatus.PENDING
        )
    
    return {
        'patient': patient,
        'study': study,
        'series': series,
        'export_record': export_record
    }

def test_full_real_workflow():
    """
    Test the complete export workflow with real API
    """
    print("\n=== Testing Full Real Workflow ===")
    
    config = check_configuration()
    if not config:
        return False
    
    # Create test records
    test_records = create_test_database_records()
    
    # Create test ZIP file
    test_zip = create_test_zip_file()
    
    try:
        # Update export record with real ZIP path
        export_record = test_records['export_record']
        export_record.deidentified_zip_file_path = test_zip
        export_record.save()
        
        # Prepare task3 output format
        task3_output = {
            "status": "success",
            "processed_series": 1,
            "successful_deidentifications": 1,
            "deidentified_series": [{
                'original_series_uid': test_records['series'].series_instance_uid,
                'deidentified_series_uid': test_records['series'].deidentified_series_instance_uid,
                'zip_file_path': test_zip,
                'template_id': None,
                'template_name': "Real Test Template",
                'file_count': 4
            }]
        }
        
        print("Running full export workflow with real API...")
        result = export_series_to_api(task3_output)
        
        if result['status'] == 'success' and result['successful_exports'] > 0:
            print("✅ Full workflow completed successfully!")
            print(f"Processed series: {result['processed_series']}")
            print(f"Successful exports: {result['successful_exports']}")
            
            # Check database updates
            test_records['series'].refresh_from_db()
            export_record.refresh_from_db()
            
            print(f"Series status: {test_records['series'].series_processsing_status}")
            print(f"Export status: {export_record.deidentified_zip_file_transfer_status}")
            print(f"Task ID: {export_record.task_id}")
            
            # Check if ZIP file was cleaned up
            if not os.path.exists(test_zip):
                print("✅ ZIP file cleaned up successfully")
            else:
                print("⚠️  ZIP file still exists (cleanup may have failed)")
            
            return True
        else:
            print("❌ Full workflow failed")
            print(f"Result: {result}")
            return False
            
    except Exception as e:
        print(f"❌ Workflow test error: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        # Cleanup
        if os.path.exists(test_zip):
            os.remove(test_zip)
            os.rmdir(os.path.dirname(test_zip))
        
        # Cleanup test records
        try:
            with transaction.atomic():
                export_record.delete()
                test_records['series'].delete()
                test_records['study'].delete()
                test_records['patient'].delete()
        except:
            pass  # Records may have been cleaned up already

def main():
    """
    Main function to run real API transfer tests
    """
    print("🚀 Starting Real API Transfer Tests")
    print("Using SEPARATE TEST DATABASE (production DB is safe)")
    print("=" * 60)
    
    # Create test database
    test_db_name = None
    try:
        test_db_name = create_test_database()
        
        # Check configuration first
        config = check_configuration()
        if not config:
            print("\n❌ Configuration check failed. Please ensure:")
            print("1. SystemConfiguration has draw_base_url set")
            print("2. Bearer token (draw_bearer_token) is configured")
            print("3. Refresh token (draw_refresh_token) is configured")
            print("\nExample configuration:")
            print("config = SystemConfiguration.load()")
            print("config.draw_base_url = 'https://your-api-server.com'")
            print("config.draw_bearer_token = 'your_bearer_token'")
            print("config.draw_refresh_token = 'your_refresh_token'")
            print("config.save()")
            return
        
        print("\n✅ Configuration check passed")
        
        # Run tests
        tests_passed = 0
        total_tests = 3
        
        # Test 1: API Health Check
        if test_real_api_health_check():
            tests_passed += 1
        
        # Test 2: File Upload
        if test_real_file_upload():
            tests_passed += 1
        
        # Test 3: Full Workflow
        if test_full_real_workflow():
            tests_passed += 1
        
        print("\n" + "=" * 60)
        print(f"Real API Transfer Tests Results: {tests_passed}/{total_tests} passed")
        
        if tests_passed == total_tests:
            print("✅ All real API transfer tests passed!")
            print("The functionality is working correctly with the real API server.")
        else:
            print("⚠️  Some tests failed. Check the API server configuration and network connectivity.")
    
    except Exception as e:
        print(f"\n❌ Test execution failed with error: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        # Always destroy test database
        if test_db_name:
            destroy_test_database()
        
        print("\n" + "="*70)
        print("TEST COMPLETED")
        print("Your production database was NOT modified")
        print("="*70)

if __name__ == "__main__":
    main()
