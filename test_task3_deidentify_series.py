#!/usr/bin/env python
"""
Test script for task3_deidentify_series.py
This script tests the DICOM deidentification functionality.
Runs after the template matching test to use matched series data.
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
from dicom_handler.models import (
    SystemConfiguration, Patient, DICOMStudy, DICOMSeries, DICOMInstance,
    ProcessingStatus, RuleSet, Rule, DICOMTagType, OperatorType, 
    RuleCombinationType, AutosegmentationTemplate, AutosegmentationModel,
    AutosegmentationStructure, DICOMFileExport, DICOMFileTransferStatus
)
from dicom_handler.export_services.task3_deidentify_series import (
    deidentify_series, generate_deidentified_uids, generate_random_date,
    create_autosegmentation_template_yaml, create_zip_file
)
import json
import shutil
from datetime import datetime
from django.utils import timezone

def check_matched_series():
    """
    Check if there are matched series from task2 to test with
    """
    print("Checking existing matched DICOM series data...")
    
    matched_series = DICOMSeries.objects.filter(
        series_processsing_status__in=[
            ProcessingStatus.RULE_MATCHED,
            ProcessingStatus.MULTIPLE_RULES_MATCHED
        ]
    )
    
    if not matched_series.exists():
        print("✗ No matched series found. Please run task2 test first.")
        return False
    
    print(f"✓ Found {matched_series.count()} matched series")
    for series in matched_series[:3]:  # Show first 3
        print(f"  - Series UID: {series.series_instance_uid[:30]}...")
        print(f"    Status: {series.series_processsing_status}")
        rulesets = series.matched_rule_sets.all()
        templates = series.matched_templates.all()
        print(f"    Rulesets: {[rs.ruleset_name for rs in rulesets]}")
        print(f"    Templates: {[t.template_name for t in templates]}")
    
    if matched_series.count() > 3:
        print(f"  ... and {matched_series.count() - 3} more series")
    
    return True

def create_test_models_and_structures():
    """
    Create test autosegmentation models and structures for YAML generation
    """
    print("Creating test autosegmentation models and structures...")
    
    # Clear existing models and structures
    AutosegmentationStructure.objects.all().delete()
    AutosegmentationModel.objects.all().delete()
    
    # Get existing templates
    templates = AutosegmentationTemplate.objects.all()
    if not templates.exists():
        print("✗ No templates found. Please run task2 test first.")
        return False
    
    models_created = 0
    structures_created = 0
    
    for template in templates:
        # Create 2 models per template
        for i in range(1, 3):
            model = AutosegmentationModel.objects.create(
                autosegmentation_template_name=template,
                model_id=100 + models_created,
                name=f"Model_{template.template_name.replace(' ', '_')}_{i}",
                config=f"config_{i}.json",
                trainer_name=f"trainer_{i}",
                postprocess=f"postprocess_{i}.py"
            )
            models_created += 1
            
            # Create 3 structures per model
            for j in range(1, 4):
                AutosegmentationStructure.objects.create(
                    autosegmentation_model=model,
                    map_id=1000 + structures_created,
                    name=f"Structure_{j}_{template.template_name.replace(' ', '_')}"
                )
                structures_created += 1
    
    print(f"✓ Created {models_created} models and {structures_created} structures")
    return True

def test_uid_generation():
    """
    Test UID generation functions
    """
    print("\n" + "="*50)
    print("TESTING UID GENERATION")
    print("="*50)
    
    # Test UID generation
    original_study_uid = "1.2.3.4.5.6.7.8.9"
    uids = generate_deidentified_uids(original_study_uid, 1)
    
    print("Generated UIDs:")
    print(f"  Study UID: {uids['study_instance_uid']}")
    print(f"  Series UID: {uids['series_instance_uid']}")
    print(f"  Frame of Ref UID: {uids['frame_of_reference_uid']}")
    
    # Verify UID format
    org_prefix = "1.2.826.0.1.3680043.10.1561"
    if uids['study_instance_uid'].startswith(org_prefix):
        print("✓ Study UID has correct organization prefix")
    else:
        print("✗ Study UID missing organization prefix")
    
    if uids['series_instance_uid'].startswith(uids['study_instance_uid']):
        print("✓ Series UID is based on Study UID")
    else:
        print("✗ Series UID not based on Study UID")
    
    if uids['frame_of_reference_uid'].startswith(uids['series_instance_uid']):
        print("✓ Frame of Reference UID is based on Series UID")
    else:
        print("✗ Frame of Reference UID not based on Series UID")

def test_date_generation():
    """
    Test random date generation
    """
    print("\n" + "="*50)
    print("TESTING DATE GENERATION")
    print("="*50)
    
    # Generate multiple dates to test range
    dates = [generate_random_date() for _ in range(5)]
    
    print("Generated dates:")
    for i, date in enumerate(dates, 1):
        print(f"  Date {i}: {date}")
    
    # Verify date range (should be between 2000-2020)
    from datetime import date as date_class
    min_date = date_class(2000, 1, 1)
    max_date = date_class(2020, 12, 31)
    
    all_in_range = all(min_date <= d <= max_date for d in dates)
    if all_in_range:
        print("✓ All dates are within expected range (2000-2020)")
    else:
        print("✗ Some dates are outside expected range")

def test_yaml_creation():
    """
    Test autosegmentation template YAML creation
    """
    print("\n" + "="*50)
    print("TESTING YAML CREATION")
    print("="*50)
    
    # Get a template with models and structures
    template = AutosegmentationTemplate.objects.first()
    if not template:
        print("✗ No template found for testing")
        return False
    
    # Create test directory
    test_dir = "test_yaml_output"
    os.makedirs(test_dir, exist_ok=True)
    
    try:
        template_info = {
            'template_id': str(template.id),
            'template_name': template.template_name
        }
        
        yaml_path = create_autosegmentation_template_yaml(template_info, test_dir)
        
        if yaml_path and os.path.exists(yaml_path):
            print(f"✓ YAML file created: {yaml_path}")
            
            # Read and display YAML content
            with open(yaml_path, 'r') as f:
                yaml_content = f.read()
            
            print("YAML content preview:")
            print(yaml_content[:500] + "..." if len(yaml_content) > 500 else yaml_content)
            
            return True
        else:
            print("✗ YAML file creation failed")
            return False
    
    finally:
        # Clean up test directory
        if os.path.exists(test_dir):
            shutil.rmtree(test_dir)

def simulate_task2_output():
    """
    Create simulated task2 output using existing matched series data
    """
    print("Creating simulated task2 output...")
    
    matched_series = DICOMSeries.objects.filter(
        series_processsing_status__in=[
            ProcessingStatus.RULE_MATCHED,
            ProcessingStatus.MULTIPLE_RULES_MATCHED
        ]
    )
    
    matched_series_data = []
    for series in matched_series:
        # Get associated rulesets and templates
        rulesets = series.matched_rule_sets.all()
        templates = series.matched_templates.all()
        
        # Create entries for each ruleset (as task2 would do)
        for ruleset in rulesets:
            template = ruleset.associated_autosegmentation_template
            matched_series_data.append({
                'series_instance_uid': series.series_instance_uid,
                'series_root_path': series.series_root_path,
                'matched_ruleset_id': str(ruleset.id),
                'matched_ruleset_name': ruleset.ruleset_name,
                'associated_template_id': str(template.id) if template else None,
                'associated_template_name': template.template_name if template else None,
                'instance_count': series.instance_count or 0
            })
    
    task2_output = {
        "status": "success",
        "processed_series": matched_series.count(),
        "total_matches": len(matched_series_data),
        "matched_series": matched_series_data
    }
    
    print(f"✓ Created simulated task2 output with {len(matched_series_data)} matched series")
    return task2_output

def test_complete_workflow():
    """
    Test the complete task3 workflow
    """
    print("\n" + "="*50)
    print("TESTING COMPLETE TASK3 WORKFLOW")
    print("="*50)
    
    # Create simulated task2 output
    task2_output = simulate_task2_output()
    
    if not task2_output['matched_series']:
        print("✗ No matched series available for testing")
        return False
    
    # Clean up any existing deidentified data
    cleanup_deidentified_data()
    
    # Run task3
    print("Running deidentify_series()...")
    start_time = datetime.now()
    result = deidentify_series(task2_output)
    end_time = datetime.now()
    
    processing_time = (end_time - start_time).total_seconds()
    
    # Display results
    print(f"\nProcessing time: {processing_time:.2f} seconds")
    print(f"Status: {result.get('status', 'Unknown')}")
    print(f"Processed series: {result.get('processed_series', 0)}")
    print(f"Successful deidentifications: {result.get('successful_deidentifications', 0)}")
    print(f"Deidentified series count: {len(result.get('deidentified_series', []))}")
    
    if result.get('status') == 'error':
        print(f"Error message: {result.get('message', 'No message')}")
        return False
    
    # Show deidentified series details
    deidentified_series = result.get('deidentified_series', [])
    if deidentified_series:
        print(f"\nDeidentified series details:")
        for i, series in enumerate(deidentified_series[:3]):  # Show first 3
            print(f"  Series {i+1}:")
            print(f"    Original UID: {series['original_series_uid'][:30]}...")
            print(f"    Deidentified UID: {series['deidentified_series_uid'][:30]}...")
            print(f"    ZIP file: {series['zip_file_path']}")
            print(f"    Template: {series['template_name']}")
            print(f"    File count: {series['file_count']}")
        
        if len(deidentified_series) > 3:
            print(f"  ... and {len(deidentified_series) - 3} more series")
    
    # Check if ZIP files were created
    print(f"\nChecking created ZIP files:")
    for series in deidentified_series[:3]:
        zip_path = series['zip_file_path']
        if os.path.exists(zip_path):
            file_size = os.path.getsize(zip_path) / 1024  # KB
            print(f"  ✓ {os.path.basename(zip_path)} ({file_size:.1f} KB)")
        else:
            print(f"  ✗ {os.path.basename(zip_path)} (not found)")
    
    return True

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

def print_database_summary():
    """
    Print summary of series status and deidentified data after processing
    """
    print("\n" + "="*50)
    print("DATABASE SUMMARY AFTER PROCESSING")
    print("="*50)
    
    # Series status summary
    series_by_status = {}
    for status in ProcessingStatus.choices:
        count = DICOMSeries.objects.filter(series_processsing_status=status[0]).count()
        if count > 0:
            series_by_status[status[1]] = count
    
    print("Series by processing status:")
    for status_name, count in series_by_status.items():
        print(f"  {status_name}: {count}")
    
    # Deidentified data summary
    deidentified_series = DICOMSeries.objects.filter(
        series_processsing_status=ProcessingStatus.DEIDENTIFIED_SUCCESSFULLY
    )
    
    if deidentified_series.exists():
        print(f"\nDeidentified series details:")
        for series in deidentified_series[:3]:  # Show first 3
            print(f"  Series: {series.series_instance_uid[:30]}...")
            deidentified_uid = series.deidentified_series_instance_uid
            frame_ref_uid = series.deidentified_frame_of_reference_uid
            print(f"    Deidentified UID: {deidentified_uid[:30] + '...' if deidentified_uid else 'None'}")
            print(f"    Deidentified Frame Ref: {frame_ref_uid[:30] + '...' if frame_ref_uid else 'None'}")
            
            # Check for export record
            try:
                export_record = DICOMFileExport.objects.get(deidentified_series_instance_uid=series)
                print(f"    ZIP file: {export_record.deidentified_zip_file_path}")
                print(f"    Transfer status: {export_record.deidentified_zip_file_transfer_status}")
            except DICOMFileExport.DoesNotExist:
                print(f"    No export record found")
    
    # Patient and study deidentification summary
    patients_with_deidentified = Patient.objects.exclude(deidentified_patient_id__isnull=True)
    studies_with_deidentified = DICOMStudy.objects.exclude(deidentified_study_instance_uid__isnull=True)
    
    print(f"\nDeidentification summary:")
    print(f"  Patients with deidentified IDs: {patients_with_deidentified.count()}")
    print(f"  Studies with deidentified UIDs: {studies_with_deidentified.count()}")
    print(f"  Series with deidentified UIDs: {deidentified_series.count()}")

def cleanup_deidentified_data():
    """
    Clean up any existing deidentified data and files
    """
    print("Cleaning up existing deidentified data...")
    
    # Remove deidentified_dicom directory if it exists
    if os.path.exists("deidentified_dicom"):
        shutil.rmtree("deidentified_dicom")
        print("✓ Removed existing deidentified_dicom directory")
    
    # Reset series processing status for testing
    DICOMSeries.objects.filter(
        series_processsing_status__in=[
            ProcessingStatus.DEIDENTIFIED_SUCCESSFULLY,
            ProcessingStatus.DEIDENTIFICATION_FAILED
        ]
    ).update(series_processsing_status=ProcessingStatus.RULE_MATCHED)
    
    # Clear export records
    DICOMFileExport.objects.all().delete()
    
    print("✓ Reset series status and cleared export records")

def main():
    """
    Main test function
    """
    print("="*60)
    print("TESTING DICOM DEIDENTIFICATION - task3")
    print("="*60)
    
    try:
        # Check if we have matched series data from task2
        if not check_matched_series():
            print("Please run the task2 test first to create matched series data.")
            return
        
        # Create test models and structures for YAML generation
        if not create_test_models_and_structures():
            return
        
        # Test individual functions
        test_uid_generation()
        test_date_generation()
        
        # Test YAML creation
        if not test_yaml_creation():
            print("YAML creation test failed")
            return
        
        # Test complete workflow
        if not test_complete_workflow():
            print("Complete workflow test failed")
            return
        
        # Get final result for serialization test
        task2_output = simulate_task2_output()
        final_result = deidentify_series(task2_output)
        
        # Test JSON serialization
        test_json_serialization(final_result)
        
        # Show database summary
        print_database_summary()
        
        print(f"\n" + "="*60)
        print("TASK3 TEST COMPLETED SUCCESSFULLY")
        print("="*60)
        print("The deidentified series are now ready for task4 (API export)")
        
    except Exception as e:
        print(f"\n✗ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # Ask if user wants to keep deidentified files
        keep_files = input("\nKeep deidentified files for inspection? (y/N): ").strip().lower()
        if keep_files not in ['y', 'yes']:
            cleanup_deidentified_data()
            print("✓ Cleaned up deidentified files")

if __name__ == "__main__":
    main()
