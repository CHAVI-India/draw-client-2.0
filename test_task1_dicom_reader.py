#!/usr/bin/env python
"""
Test script for task1_read_dicom_from_storage.py
This script tests the DICOM file reading functionality.
"""

import os
import sys
import django
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'draw_client.settings')
django.setup()

# Now import Django models and the function to test
from dicom_handler.models import SystemConfiguration, Patient, DICOMStudy, DICOMSeries, DICOMInstance
from dicom_handler.export_services.task1_read_dicom_from_storage import read_dicom_from_storage
import json
from datetime import datetime
from django.utils import timezone

def check_system_configuration():
    """
    Check existing system configuration
    """
    print("Checking existing system configuration...")
    
    # Get existing system configuration
    config = SystemConfiguration.get_singleton()
    if not config:
        print("✗ No system configuration found")
        return None
    
    if not config.folder_configuration:
        print("✗ No folder path configured in system configuration")
        return None
    
    print(f"✓ Found configured folder: {config.folder_configuration}")
    print(f"✓ Date filter: {config.data_pull_start_datetime}")
    return config

def clear_test_data():
    """
    Clear existing test data from database
    """
    print("Clearing existing test data...")
    
    # Delete in reverse order of dependencies
    DICOMInstance.objects.all().delete()
    DICOMSeries.objects.all().delete()
    DICOMStudy.objects.all().delete()
    Patient.objects.all().delete()
    
    print("✓ Test data cleared")

def print_database_summary():
    """
    Print summary of what was created in the database
    """
    print("\n" + "="*50)
    print("DATABASE SUMMARY")
    print("="*50)
    
    patients = Patient.objects.all()
    studies = DICOMStudy.objects.all()
    series = DICOMSeries.objects.all()
    instances = DICOMInstance.objects.all()
    
    print(f"Patients created: {patients.count()}")
    for patient in patients:
        print(f"  - Patient ID: {patient.patient_id[:10]}... Name: {str(patient.patient_name)[:20]}...")
    
    print(f"Studies created: {studies.count()}")
    for study in studies:
        print(f"  - Study UID: {study.study_instance_uid[:20]}... Modality: {study.study_modality}")
    
    print(f"Series created: {series.count()}")
    for s in series:
        print(f"  - Series UID: {s.series_instance_uid[:20]}... Status: {s.series_processsing_status}")
        print(f"    Root path: {s.series_root_path}")
        print(f"    Instance count: {s.instance_count}")
        print(f"    ⭐ Fully loaded: {s.series_files_fully_read}")
        if s.series_files_fully_read:
            print(f"    ⭐ Loaded at: {s.series_files_fully_read_datetime}")
    
    print(f"Instances created: {instances.count()}")
    for instance in instances[:5]:  # Show first 5 instances
        print(f"  - SOP UID: {instance.sop_instance_uid[:20]}...")
        print(f"    Path: {instance.instance_path}")
    
    if instances.count() > 5:
        print(f"  ... and {instances.count() - 5} more instances")

def validate_series_completeness():
    """
    Validate that all series are properly marked as complete
    Checks for instance count mismatches
    """
    print("\n" + "="*50)
    print("SERIES COMPLETENESS VALIDATION")
    print("="*50)
    
    series_list = DICOMSeries.objects.all()
    
    if not series_list.exists():
        print("No series found in database")
        return True
    
    all_valid = True
    
    for series in series_list:
        # Count actual instances in database
        actual_count = DICOMInstance.objects.filter(series_instance_uid=series).count()
        recorded_count = series.instance_count or 0
        
        print(f"\nSeries: {series.series_instance_uid[:30]}...")
        print(f"  Recorded count: {recorded_count}")
        print(f"  Actual count: {actual_count}")
        print(f"  Fully loaded flag: {series.series_files_fully_read}")
        
        if actual_count != recorded_count:
            print(f"  ⚠️  WARNING: Instance count mismatch! Difference: {abs(actual_count - recorded_count)}")
            all_valid = False
        else:
            print(f"  ✅ Instance count matches")
        
        if not series.series_files_fully_read:
            print(f"  ⚠️  WARNING: Series not marked as fully loaded!")
            all_valid = False
        else:
            print(f"  ✅ Series marked as fully loaded")
    
    print("\n" + "-"*50)
    if all_valid:
        print("✅ All series are complete and valid")
    else:
        print("⚠️  Some series have issues - see warnings above")
    print("="*50)
    
    return all_valid

def test_json_serialization(result):
    """
    Test if the result can be JSON serialized (required for Celery)
    """
    print("\n" + "="*50)
    print("JSON SERIALIZATION TEST")
    print("="*50)
    
    try:
        json_str = json.dumps(result, indent=2)
        print("✓ Result is JSON serializable")
        print("Sample serialized data:")
        print(json_str[:500] + "..." if len(json_str) > 500 else json_str)
        return True
    except Exception as e:
        print(f"✗ JSON serialization failed: {e}")
        return False

def test_folder_structure(folder_path):
    """
    Display the folder structure being tested
    """
    print(f"\n" + "="*50)
    print(f"FOLDER STRUCTURE: {folder_path}")
    print("="*50)
    
    if not os.path.exists(folder_path):
        print(f"✗ Folder does not exist: {folder_path}")
        return False
    
    file_count = 0
    for root, dirs, files in os.walk(folder_path):
        level = root.replace(folder_path, '').count(os.sep)
        indent = ' ' * 2 * level
        print(f"{indent}{os.path.basename(root)}/")
        
        subindent = ' ' * 2 * (level + 1)
        for file in files:
            print(f"{subindent}{file}")
            file_count += 1
    
    print(f"\nTotal files found: {file_count}")
    return file_count > 0

def main():
    """
    Main test function
    """
    print("="*60)
    print("TESTING DICOM FILE READER - task1_read_dicom_from_storage")
    print("="*60)
    
    try:
        # Check existing system configuration
        config = check_system_configuration()
        if not config:
            print("Please configure the system with a folder path first.")
            return
        
        folder_path = config.folder_configuration
        
        # Test folder structure
        if not test_folder_structure(folder_path):
            print("No files found in the configured folder. Please add some DICOM files and try again.")
            return
        
        # Ask if user wants to clear existing data
        clear_data = input("Clear existing DICOM data from database? (y/N): ").strip().lower()
        if clear_data in ['y', 'yes']:
            clear_test_data()
        
        # Run the function
        print(f"\n" + "="*50)
        print("RUNNING read_dicom_from_storage()")
        print("="*50)
        
        start_time = datetime.now()
        result = read_dicom_from_storage()
        end_time = datetime.now()
        
        processing_time = (end_time - start_time).total_seconds()
        
        # Display results
        print(f"\n" + "="*50)
        print("FUNCTION RESULTS")
        print("="*50)
        print(f"Processing time: {processing_time:.2f} seconds")
        print(f"Status: {result.get('status', 'Unknown')}")
        print(f"Processed files: {result.get('processed_files', 0)}")
        print(f"Skipped files: {result.get('skipped_files', 0)}")
        print(f"Error files: {result.get('error_files', 0)}")
        print(f"Series found: {len(result.get('series_data', []))}")
        
        if result.get('status') == 'error':
            print(f"Error message: {result.get('message', 'No message')}")
        
        # Show series data
        if result.get('series_data'):
            print(f"\nSeries data for next task:")
            for i, series in enumerate(result['series_data'][:3]):  # Show first 3
                print(f"  Series {i+1}:")
                print(f"    UID: {series['series_instance_uid'][:30]}...")
                print(f"    Root path: {series['series_root_path']}")
                print(f"    First instance: {series['first_instance_path']}")
                print(f"    Instance count: {series['instance_count']}")
            
            if len(result['series_data']) > 3:
                print(f"  ... and {len(result['series_data']) - 3} more series")
        
        # Test JSON serialization
        test_json_serialization(result)
        
        # Show database summary
        print_database_summary()
        
        # Validate series completeness
        validate_series_completeness()
        
        print(f"\n" + "="*60)
        print("TEST COMPLETED SUCCESSFULLY")
        print("="*60)
        
    except Exception as e:
        print(f"\n✗ Test failed with error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
