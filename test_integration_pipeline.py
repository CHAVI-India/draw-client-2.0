#!/usr/bin/env python
"""
Integration test for the complete DICOM processing pipeline.
Runs Task1 → Task2 → Task3 in sequence using the same test database.
Tests the path validation fix in Task3.
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

# Import models
from dicom_handler.models import (
    SystemConfiguration, Patient, DICOMStudy, DICOMSeries, DICOMInstance,
    ProcessingStatus, RuleSet, Rule, DICOMTagType, OperatorType, 
    RuleCombinationType, RuleGroup, AutosegmentationTemplate, AutosegmentationModel,
    AutosegmentationStructure, DICOMFileExport
)
from django.test.utils import setup_test_environment, teardown_test_environment
from django.db import connections
from django.conf import settings

# Import task functions
from dicom_handler.export_services.task1_read_dicom_from_storage import read_dicom_from_storage
from dicom_handler.export_services.task2_match_autosegmentation_template import match_autosegmentation_template
from dicom_handler.export_services.task3_deidentify_series import deidentify_series

import tempfile
import pydicom
from datetime import datetime, timedelta
from django.utils import timezone

# Global variable to track test database
_test_db_name = None

def create_test_database():
    """Create a separate test database for testing"""
    global _test_db_name
    
    print("\n" + "="*70)
    print("CREATING INTEGRATION TEST DATABASE")
    print("="*70)
    
    setup_test_environment()
    connection = connections['default']
    _test_db_name = connection.creation.create_test_db(
        verbosity=1, autoclobber=True, keepdb=False
    )
    
    print(f"✓ Test database created: {_test_db_name}")
    print("="*70)
    
    return _test_db_name

def destroy_test_database():
    """Destroy the test database after testing"""
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
    print("="*70)

def create_mock_dicom_data(base_dir):
    """Create mock DICOM files for testing"""
    print("\n" + "="*50)
    print("CREATING MOCK DICOM DATA")
    print("="*50)
    
    # Create test directories
    headneck_dir = os.path.join(base_dir, "HeadNeck_CT")
    os.makedirs(headneck_dir, exist_ok=True)
    
    # Create a mock DICOM file
    file_path = os.path.join(headneck_dir, "CT.1.2.840.113619.2.55.3.279720729.182.1743555176.422.10.dcm")
    
    # Create a simple DICOM dataset
    ds = pydicom.Dataset()
    ds.PatientName = "Test Patient"
    ds.PatientID = "TEST001"
    ds.Modality = "CT"
    ds.BodyPartExamined = "HEADNECK"
    ds.SliceThickness = 2.5
    ds.StudyDescription = "CT Head and Neck Study"
    ds.SeriesDescription = "CT Head and Neck Series"
    ds.StudyInstanceUID = "1.2.840.113619.2.55.3.279720729.182.1743555176.422"
    ds.SeriesInstanceUID = "1.2.840.113619.2.55.3.279720729.182.1743555176.422.10"
    ds.SOPInstanceUID = "1.2.840.113619.2.55.3.279720729.182.1743555176.422.10.1"
    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    ds.Rows = 512
    ds.Columns = 512
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.PixelRepresentation = 0
    ds.StudyDate = "20240115"
    ds.SeriesDate = "20240115"
    ds.ContentDate = "20240115"
    ds.StudyTime = "120000"
    ds.SeriesTime = "120000"
    ds.ContentTime = "120000"
    
    # Add required file meta info
    ds.file_meta = pydicom.dataset.FileMetaDataset()
    ds.file_meta.MediaStorageSOPClassUID = ds.SOPClassUID
    ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
    ds.file_meta.TransferSyntaxUID = "1.2.840.10008.1.2"
    ds.file_meta.ImplementationClassUID = "1.2.826.0.1.3680043.9.5432.1"
    
    # Create minimal pixel data
    ds.PixelData = b'\x00' * (512 * 512 * 2)
    
    # Save the file
    ds.save_as(file_path)
    print(f"✓ Created mock DICOM: {file_path}")
    
    # Set file modification time to 15 minutes ago so Task1 will process it
    # (Task1 skips files modified in the last 10 minutes)
    old_time = datetime.now() - timedelta(minutes=15)
    old_timestamp = old_time.timestamp()
    os.utime(file_path, (old_timestamp, old_timestamp))
    print(f"✓ Set file timestamp to 15 minutes ago: {old_time}")
    
    return base_dir

def create_test_templates_and_rules():
    """Create test templates, models, structures, and rules"""
    print("\n" + "="*50)
    print("CREATING TEST TEMPLATES AND RULES")
    print("="*50)
    
    # Create DICOM tag types
    modality_tag, _ = DICOMTagType.objects.get_or_create(
        tag_id="(0008,0060)",
        defaults={'tag_name': 'Modality', 'value_representation': 'CS'}
    )
    body_part_tag, _ = DICOMTagType.objects.get_or_create(
        tag_id="(0018,0015)",
        defaults={'tag_name': 'BodyPartExamined', 'value_representation': 'CS'}
    )
    slice_thickness_tag, _ = DICOMTagType.objects.get_or_create(
        tag_id="(0018,0050)",
        defaults={'tag_name': 'SliceThickness', 'value_representation': 'DS'}
    )
    print("✓ Created DICOM tag types")
    
    # Create autosegmentation template
    template, _ = AutosegmentationTemplate.objects.get_or_create(
        template_name="HeadNeck Template",
        defaults={
            'template_description': 'Test template for head and neck'
        }
    )
    print(f"✓ Created template: {template.template_name}")
    
    # Create model
    model, _ = AutosegmentationModel.objects.get_or_create(
        autosegmentation_template_name=template,
        model_id=1,
        defaults={
            'name': 'Head and Neck OAR Model',
            'config': '{}',
            'trainer_name': 'TestTrainer',
            'postprocess': '{}'
        }
    )
    print(f"✓ Created model: {model.name}")
    
    # Create structure
    structure, _ = AutosegmentationStructure.objects.get_or_create(
        autosegmentation_model=model,
        map_id=1,
        defaults={'name': 'Parotid_L'}
    )
    print(f"✓ Created structure: {structure.name}")
    
    # Create rulegroup
    rulegroup, _ = RuleGroup.objects.get_or_create(
        rulegroup_name="HeadNeck RuleGroup",
        defaults={
            'associated_autosegmentation_template': template
        }
    )
    print(f"✓ Created rulegroup: {rulegroup.rulegroup_name}")
    
    # Create ruleset
    ruleset, _ = RuleSet.objects.get_or_create(
        rulegroup=rulegroup,
        ruleset_name="HeadNeck Ruleset",
        defaults={
            'ruleset_description': 'Rules for head and neck CT',
            'ruleset_combination_type': RuleCombinationType.AND,
            'associated_autosegmentation_template': template,
            'rulset_order': 1
        }
    )
    print(f"✓ Created ruleset: {ruleset.ruleset_name}")
    
    # Create rules
    Rule.objects.get_or_create(
        ruleset=ruleset,
        dicom_tag_type=modality_tag,
        defaults={
            'operator_type': OperatorType.CASE_SENSITIVE_STRING_EXACT_MATCH,
            'tag_value_to_evaluate': 'CT',
            'rule_combination_type': RuleCombinationType.AND,
            'rule_order': 1
        }
    )
    Rule.objects.get_or_create(
        ruleset=ruleset,
        dicom_tag_type=body_part_tag,
        defaults={
            'operator_type': OperatorType.CASE_INSENSITIVE_STRING_CONTAINS,
            'tag_value_to_evaluate': 'head',
            'rule_combination_type': RuleCombinationType.AND,
            'rule_order': 2
        }
    )
    print("✓ Created rules")
    
    return template

def run_task1(storage_path):
    """Run Task1: Read DICOM from storage"""
    print("\n" + "="*70)
    print("TASK 1: READING DICOM FROM STORAGE")
    print("="*70)
    
    # Configure SystemConfiguration with test storage path
    # Set data_pull_start_datetime to 7 days ago so files will be processed
    seven_days_ago = timezone.now() - timedelta(days=7)
    
    config, _ = SystemConfiguration.objects.get_or_create(
        id=1,  # Use default ID
        defaults={
            'folder_configuration': storage_path,
            'draw_base_url': 'http://test.example.com/',
            'data_pull_start_datetime': seven_days_ago
        }
    )
    # Update the path and datetime if config already existed
    config.folder_configuration = storage_path
    config.data_pull_start_datetime = seven_days_ago
    config.save()
    print(f"✓ Configured storage path: {storage_path}")
    print(f"✓ Configured data_pull_start_datetime: {seven_days_ago}")
    
    result = read_dicom_from_storage()
    
    print(f"Status: {result.get('status')}")
    print(f"Studies found: {result.get('studies_found', 0)}")
    print(f"Series found: {result.get('series_found', 0)}")
    print(f"Instances found: {result.get('instances_found', 0)}")
    
    if result.get('status') != 'success':
        print(f"Error: {result.get('message')}")
        return None
    
    return result

def run_task2(task1_output):
    """Run Task2: Match autosegmentation templates"""
    print("\n" + "="*70)
    print("TASK 2: MATCHING AUTOSEGMENTATION TEMPLATES")
    print("="*70)
    
    result = match_autosegmentation_template(task1_output)
    
    print(f"Status: {result.get('status')}")
    print(f"Processed series: {result.get('processed_series', 0)}")
    print(f"Total matches: {result.get('total_matches', 0)}")
    
    if result.get('status') != 'success':
        print(f"Error: {result.get('message')}")
        return None
    
    # Show matched series
    for match in result.get('matched_series', []):
        print(f"\n  Matched Series:")
        print(f"    Series UID: {match.get('series_instance_uid', 'N/A')[:30]}...")
        print(f"    Template: {match.get('associated_template_name', 'N/A')}")
        print(f"    Path: {match.get('series_root_path', 'N/A')}")
    
    return result

def run_task3(task2_output):
    """Run Task3: Deidentify series"""
    print("\n" + "="*70)
    print("TASK 3: DEIDENTIFYING SERIES")
    print("="*70)
    
    result = deidentify_series(task2_output)
    
    print(f"Status: {result.get('status')}")
    print(f"Processed series: {result.get('processed_series', 0)}")
    print(f"Successful deidentifications: {result.get('successful_deidentifications', 0)}")
    
    if result.get('status') != 'success':
        print(f"Error: {result.get('message')}")
        return None
    
    # Show deidentified series
    for item in result.get('deidentified_series', []):
        print(f"\n  Deidentified Series:")
        print(f"    Original UID: {item.get('original_series_uid', 'N/A')[:30]}...")
        print(f"    New UID: {item.get('deidentified_series_uid', 'N/A')[:30]}...")
        print(f"    ZIP file: {item.get('zip_file_path', 'N/A')}")
        print(f"    Template: {item.get('template_name', 'N/A')}")
        print(f"    Files: {item.get('file_count', 0)}")
    
    return result

def verify_results():
    """Verify the final state of the database"""
    print("\n" + "="*70)
    print("VERIFYING RESULTS")
    print("="*70)
    
    # Check series status
    series_list = DICOMSeries.objects.all()
    print(f"\nTotal series in database: {series_list.count()}")
    
    for series in series_list:
        print(f"\n  Series: {series.series_instance_uid[:40]}...")
        print(f"    Status: {series.series_processsing_status}")
        print(f"    Deidentified UID: {series.deidentified_series_instance_uid[:40] if series.deidentified_series_instance_uid else 'N/A'}...")
        
        # Check if matched to templates
        templates = list(series.matched_templates.all())
        if templates:
            print(f"    Matched templates: {[t.template_name for t in templates]}")
        
        # Check file export
        try:
            export = DICOMFileExport.objects.get(deidentified_series_instance_uid=series)
            print(f"    Export ZIP: {export.deidentified_zip_file_path}")
            print(f"    Transfer status: {export.deidentified_zip_file_transfer_status}")
        except DICOMFileExport.DoesNotExist:
            print(f"    No export record")
    
    # Count by status
    status_counts = {}
    for status in ProcessingStatus:
        count = DICOMSeries.objects.filter(series_processsing_status=status).count()
        if count > 0:
            status_counts[status] = count
    
    print(f"\nSeries by status:")
    for status, count in status_counts.items():
        print(f"  {status}: {count}")

def main():
    """Main integration test function"""
    print("="*70)
    print("INTEGRATION TEST: DICOM PROCESSING PIPELINE")
    print("Task1 → Task2 → Task3")
    print("="*70)
    
    temp_dir = None
    
    try:
        # Create test database
        create_test_database()
        
        # Create temporary directory for mock DICOM data
        temp_dir = tempfile.mkdtemp(prefix="dicom_integration_test_")
        print(f"\nUsing temp directory: {temp_dir}")
        
        # Create mock data
        storage_path = create_mock_dicom_data(temp_dir)
        
        # Create templates and rules
        create_test_templates_and_rules()
        
        # ========== TASK 1 ==========
        task1_output = run_task1(storage_path)
        if not task1_output:
            print("\n❌ Task1 failed!")
            return False
        print("\n✅ Task1 completed successfully")
        
        # ========== TASK 2 ==========
        task2_output = run_task2(task1_output)
        if not task2_output:
            print("\n❌ Task2 failed!")
            return False
        print("\n✅ Task2 completed successfully")
        
        # ========== TASK 3 ==========
        task3_output = run_task3(task2_output)
        if not task3_output:
            print("\n❌ Task3 failed!")
            return False
        print("\n✅ Task3 completed successfully")
        
        # Verify results
        verify_results()
        
        # Check if deidentification actually worked
        deidentified_count = DICOMSeries.objects.filter(
            series_processsing_status=ProcessingStatus.DEIDENTIFIED_SUCCESSFULLY
        ).count()
        
        if deidentified_count > 0:
            print(f"\n✅ SUCCESS: {deidentified_count} series deidentified successfully!")
            print("Path validation fix is working correctly.")
            return True
        else:
            print("\n❌ No series were deidentified")
            return False
        
    except Exception as e:
        print(f"\n❌ Integration test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        # Cleanup
        if temp_dir and os.path.exists(temp_dir):
            import shutil
            shutil.rmtree(temp_dir)
            print(f"\n✓ Cleaned up temp directory: {temp_dir}")
        
        destroy_test_database()
        
        print("\n" + "="*70)
        print("INTEGRATION TEST COMPLETED")
        print("="*70)

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
