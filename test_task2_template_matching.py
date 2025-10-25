#!/usr/bin/env python
"""
Test script for task2_match_autosegmentation_template.py
This script tests the autosegmentation template matching functionality.
Runs after the DICOM reader test to use existing series data.

IMPORTANT: This test uses a SEPARATE TEST DATABASE that is automatically created
and destroyed. Your production database will NOT be affected.
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
    RuleCombinationType, AutosegmentationTemplate
)
from dicom_handler.export_services.task2_match_autosegmentation_template import (
    match_autosegmentation_template, get_all_rulesets_and_rules, 
    read_dicom_metadata, evaluate_rule, evaluate_ruleset
)
import json
from datetime import datetime, timedelta
from django.utils import timezone
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
    
    # Setup test environment
    setup_test_environment()
    
    # Get the default database connection
    connection = connections['default']
    
    # Create test database
    _test_db_name = connection.creation.create_test_db(
        verbosity=1,
        autoclobber=True,  # Automatically remove old test database if exists
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
    
    # Get the default database connection
    connection = connections['default']
    
    # Destroy test database
    connection.creation.destroy_test_db(_test_db_name, verbosity=1)
    
    # Teardown test environment
    teardown_test_environment()
    
    print(f"✓ Test database destroyed: {_test_db_name}")
    print(f"✓ Production database remains unchanged")
    print("="*70)
    
    _test_db_name = None

def check_existing_series():
    """
    Check if there are existing series from task1 to test with
    """
    print("Checking existing DICOM series data...")
    
    unprocessed_series = DICOMSeries.objects.filter(
        series_processsing_status=ProcessingStatus.UNPROCESSED
    )
    
    if not unprocessed_series.exists():
        print("✗ No unprocessed series found. Please run task1 test first.")
        return False
    
    print(f"✓ Found {unprocessed_series.count()} unprocessed series")
    for series in unprocessed_series[:3]:  # Show first 3
        print(f"  - Series UID: {series.series_instance_uid[:30]}...")
        print(f"    Root path: {series.series_root_path}")
        print(f"    Instance count: {series.instance_count}")
    
    if unprocessed_series.count() > 3:
        print(f"  ... and {unprocessed_series.count() - 3} more series")
    
    return True

def create_test_templates():
    """
    Create test autosegmentation templates
    """
    print("Creating test autosegmentation templates...")
    
    # Clear existing templates and rulesets
    Rule.objects.all().delete()
    RuleSet.objects.all().delete()
    AutosegmentationTemplate.objects.all().delete()
    
    # Create templates
    template1 = AutosegmentationTemplate.objects.create(
        template_name="Breast Template",
        template_description="Template for Breast scans"
    )
    
    template2 = AutosegmentationTemplate.objects.create(
        template_name="Head Neck Template", 
        template_description="Template for Head Neck scans"
    )
    
    template3 = AutosegmentationTemplate.objects.create(
        template_name="Gyne Template",
        template_description="Template for Gynecological scans"
    )
    
    print(f"✓ Created {AutosegmentationTemplate.objects.count()} templates")
    return template1, template2, template3

def create_test_dicom_tags():
    """
    Create test DICOM tag types
    """
    print("Creating test DICOM tag types...")
    
    # Clear existing tags
    DICOMTagType.objects.all().delete()
    
    # Create common DICOM tags
    modality_tag = DICOMTagType.objects.create(
        tag_name="Modality",
        tag_id="(0008,0060)",
        tag_description="Modality of the image",
        value_representation="CS"
    )
    
    protocol_tag = DICOMTagType.objects.create(
        tag_name="Protocol Name",
        tag_id="(0018,1030)",
        tag_description="Protocol name for the scan",
        value_representation="LO"
    )
    
    body_part_tag = DICOMTagType.objects.create(
        tag_name="Body Part Examined",
        tag_id="(0018,0015)",
        tag_description="Body part examined",
        value_representation="CS"
    )
    
    slice_thickness_tag = DICOMTagType.objects.create(
        tag_name="Slice Thickness",
        tag_id="(0018,0050)",
        tag_description="Slice thickness in mm",
        value_representation="DS"
    )
    
    study_description_tag = DICOMTagType.objects.create(
        tag_name="Study Description",
        tag_id="(0008,1030)",
        tag_description="Description of the study",
        value_representation="LO"
    )
    
    print(f"✓ Created {DICOMTagType.objects.count()} DICOM tag types")
    return modality_tag, protocol_tag, slice_thickness_tag, study_description_tag

def create_test_rulesets(templates, tags):
    """
    Create test rulesets with various rule combinations
    """
    print("Creating test rulesets and rules...")
    
    template1, template2, template3 = templates
    modality_tag, protocol_tag, slice_thickness_tag, study_description_tag = tags
    
    # Ruleset 1: CT Head (AND combination)
    ruleset1 = RuleSet.objects.create(
        ruleset_name="Breast Ruleset",
        ruleset_description="Rules for Breast Scans",
        rule_combination_type=RuleCombinationType.AND,
        associated_autosegmentation_template=template1
    )
    
    # Rules for CT Head
    Rule.objects.create(
        ruleset=ruleset1,
        dicom_tag_type=modality_tag,
        operator_type=OperatorType.CASE_SENSITIVE_STRING_EXACT_MATCH,
        tag_value_to_evaluate="CT"
    )
    
    Rule.objects.create(
        ruleset=ruleset1,
        dicom_tag_type=protocol_tag,
        operator_type=OperatorType.CASE_INSENSITIVE_STRING_CONTAINS,
        tag_value_to_evaluate="Breast"
    )
    
    # Ruleset 2: MR Head (OR combination)
    ruleset2 = RuleSet.objects.create(
        ruleset_name="Head Neck Rule Set",
        ruleset_description="Rules for Head Neck Scans",
        rule_combination_type=RuleCombinationType.AND,
        associated_autosegmentation_template=template2
    )
    
    # Rules for CT Head
    Rule.objects.create(
        ruleset=ruleset2,
        dicom_tag_type=modality_tag,
        operator_type=OperatorType.CASE_SENSITIVE_STRING_EXACT_MATCH,
        tag_value_to_evaluate="CT"
    )
    
    Rule.objects.create(
        ruleset=ruleset2,
        dicom_tag_type=study_description_tag,
        operator_type=OperatorType.CASE_INSENSITIVE_STRING_CONTAINS,
        tag_value_to_evaluate="HEAD"
    )
    
    # Ruleset 3: Gyn CT Scan
    ruleset3 = RuleSet.objects.create(
        ruleset_name="Gyn CT Scan",
        ruleset_description="Gyn CT Scans",
        rule_combination_type=RuleCombinationType.AND,
        associated_autosegmentation_template=template3
    )
    
    # Rules for Thick Slice CT
    Rule.objects.create(
        ruleset=ruleset3,
        dicom_tag_type=modality_tag,
        operator_type=OperatorType.CASE_SENSITIVE_STRING_EXACT_MATCH,
        tag_value_to_evaluate="CT"
    )
    
    Rule.objects.create(
        ruleset=ruleset3,
        dicom_tag_type=protocol_tag,
        operator_type=OperatorType.CASE_INSENSITIVE_STRING_CONTAINS,
        tag_value_to_evaluate="Gyn"
    )
    
    print(f"✓ Created {RuleSet.objects.count()} rulesets with {Rule.objects.count()} rules")
    return ruleset1, ruleset2, ruleset3

def test_rule_evaluation_functions():
    """
    Test individual rule evaluation functions
    """
    print("\n" + "="*50)
    print("TESTING RULE EVALUATION FUNCTIONS")
    print("="*50)
    
    # Test metadata dictionary
    test_metadata = {
        "Modality": "CT",
        "Body Part Examined": "HEAD",
        "Slice Thickness": "3.0",
        "Study Description": "CT HEAD WITHOUT CONTRAST",
        "(0008,0060)": "CT",
        "(0018,0015)": "HEAD"
    }
    
    # Test rule data
    test_rules = [
        {
            'dicom_tag_name': 'Modality',
            'dicom_tag_id': '(0008,0060)',
            'operator_type': OperatorType.CASE_SENSITIVE_STRING_EXACT_MATCH,
            'tag_value_to_evaluate': 'CT'
        },
        {
            'dicom_tag_name': 'Body Part Examined',
            'dicom_tag_id': '(0018,0015)',
            'operator_type': OperatorType.CASE_INSENSITIVE_STRING_CONTAINS,
            'tag_value_to_evaluate': 'head'
        },
        {
            'dicom_tag_name': 'Slice Thickness',
            'dicom_tag_id': '(0018,0050)',
            'operator_type': OperatorType.LESS_THAN,
            'tag_value_to_evaluate': '5.0'
        }
    ]
    
    print("Testing individual rule evaluations:")
    for i, rule in enumerate(test_rules, 1):
        result = evaluate_rule(rule, test_metadata)
        print(f"  Rule {i}: {rule['dicom_tag_name']} {rule['operator_type']} {rule['tag_value_to_evaluate']} → {result}")
    
    # Test ruleset evaluation
    test_ruleset_and = {
        'name': 'Test AND Ruleset',
        'combination_type': RuleCombinationType.AND,
        'rules': test_rules
    }
    
    test_ruleset_or = {
        'name': 'Test OR Ruleset', 
        'combination_type': RuleCombinationType.OR,
        'rules': test_rules
    }
    
    print("\nTesting ruleset evaluations:")
    and_result = evaluate_ruleset(test_ruleset_and, test_metadata)
    or_result = evaluate_ruleset(test_ruleset_or, test_metadata)
    print(f"  AND Ruleset result: {and_result}")
    print(f"  OR Ruleset result: {or_result}")

def test_dicom_metadata_reading():
    """
    Test DICOM metadata reading from actual files
    """
    print("\n" + "="*50)
    print("TESTING DICOM METADATA READING")
    print("="*50)
    
    # Get a sample instance from existing data
    sample_instance = DICOMInstance.objects.first()
    if not sample_instance:
        print("✗ No DICOM instances found for testing")
        return False
    
    file_path = sample_instance.instance_path
    print(f"Testing metadata reading from: {file_path[:50]}...")
    
    if not os.path.exists(file_path):
        print(f"✗ File not found: {file_path}")
        return False
    
    metadata = read_dicom_metadata(file_path)
    if not metadata:
        print("✗ Failed to read metadata")
        return False
    
    print(f"✓ Successfully read {len(metadata)} DICOM tags")
    print("Sample metadata:")
    
    # Show some common tags
    common_tags = ['Modality', 'Study Description', 'Series Description', 'Body Part Examined']
    for tag in common_tags:
        if tag in metadata:
            print(f"  {tag}: {metadata[tag]}")
    
    return True

def simulate_task1_output():
    """
    Create simulated task1 output using existing series data
    """
    print("Creating simulated task1 output...")
    
    unprocessed_series = DICOMSeries.objects.filter(
        series_processsing_status=ProcessingStatus.UNPROCESSED
    )
    
    series_data = []
    for series in unprocessed_series:
        # Get first instance for this series
        first_instance = DICOMInstance.objects.filter(
            series_instance_uid=series
        ).first()
        
        if first_instance:
            series_data.append({
                'series_instance_uid': series.series_instance_uid,
                'series_root_path': series.series_root_path,
                'first_instance_path': first_instance.instance_path,
                'instance_count': series.instance_count or 0
            })
    
    task1_output = {
        "status": "success",
        "processed_files": len(series_data) * 10,  # Simulated
        "skipped_files": 5,  # Simulated
        "error_files": 0,
        "series_data": series_data
    }
    
    print(f"✓ Created simulated task1 output with {len(series_data)} series")
    return task1_output

def test_complete_workflow():
    """
    Test the complete task2 workflow
    """
    print("\n" + "="*50)
    print("TESTING COMPLETE TASK2 WORKFLOW")
    print("="*50)
    
    # Create simulated task1 output
    task1_output = simulate_task1_output()
    
    # Run task2
    print("Running match_autosegmentation_template()...")
    start_time = datetime.now()
    result = match_autosegmentation_template(task1_output)
    end_time = datetime.now()
    
    processing_time = (end_time - start_time).total_seconds()
    
    # Display results
    print(f"\nProcessing time: {processing_time:.2f} seconds")
    print(f"Status: {result.get('status', 'Unknown')}")
    print(f"Processed series: {result.get('processed_series', 0)}")
    print(f"Total matches: {result.get('total_matches', 0)}")
    print(f"Matched series count: {len(result.get('matched_series', []))}")
    
    if result.get('status') == 'error':
        print(f"Error message: {result.get('message', 'No message')}")
        return False
    
    # Show matched series details
    matched_series = result.get('matched_series', [])
    if matched_series:
        print(f"\nMatched series details:")
        for i, match in enumerate(matched_series[:5]):  # Show first 5
            print(f"  Match {i+1}:")
            print(f"    Series UID: {match['series_instance_uid'][:30]}...")
            print(f"    Ruleset: {match['matched_ruleset_name']}")
            print(f"    Template: {match['associated_template_name']}")
        
        if len(matched_series) > 5:
            print(f"  ... and {len(matched_series) - 5} more matches")
    
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
    Print summary of series status after processing
    """
    print("\n" + "="*50)
    print("DATABASE SUMMARY AFTER PROCESSING")
    print("="*50)
    
    series_by_status = {}
    for status in ProcessingStatus.choices:
        count = DICOMSeries.objects.filter(series_processsing_status=status[0]).count()
        if count > 0:
            series_by_status[status[1]] = count
    
    print("Series by processing status:")
    for status_name, count in series_by_status.items():
        print(f"  {status_name}: {count}")
    
    # Show matched series details
    matched_series = DICOMSeries.objects.exclude(
        series_processsing_status=ProcessingStatus.UNPROCESSED
    ).exclude(
        series_processsing_status=ProcessingStatus.RULE_NOT_MATCHED
    )
    
    if matched_series.exists():
        print(f"\nMatched series details:")
        for series in matched_series[:3]:  # Show first 3
            rulesets = series.matched_rule_sets.all()
            templates = series.matched_templates.all()
            print(f"  Series: {series.series_instance_uid[:30]}...")
            print(f"    Status: {series.series_processsing_status}")
            print(f"    Matched rulesets: {[rs.ruleset_name for rs in rulesets]}")
            print(f"    Associated templates: {[t.template_name for t in templates]}")

def main():
    """
    Main test function
    """
    print("="*60)
    print("TESTING AUTOSEGMENTATION TEMPLATE MATCHING - task2")
    print("Using SEPARATE TEST DATABASE (production DB is safe)")
    print("="*60)
    
    # Create test database
    test_db_name = None
    try:
        test_db_name = create_test_database()
        # Check if we have existing series data from task1
        if not check_existing_series():
            print("Please run the task1 test first to create DICOM series data.")
            return
        
        # Create test data
        templates = create_test_templates()
        tags = create_test_dicom_tags()
        rulesets = create_test_rulesets(templates, tags)
        
        # Test individual functions
        test_rule_evaluation_functions()
        
        # Test DICOM metadata reading
        if not test_dicom_metadata_reading():
            print("DICOM metadata reading test failed")
            return
        
        # Test complete workflow
        if not test_complete_workflow():
            print("Complete workflow test failed")
            return
        
        # Get final result for serialization test
        task1_output = simulate_task1_output()
        final_result = match_autosegmentation_template(task1_output)
        
        # Test JSON serialization
        test_json_serialization(final_result)
        
        # Show database summary
        print_database_summary()
        
        print(f"\n" + "="*60)
        print("TASK2 TEST COMPLETED SUCCESSFULLY")
        print("="*60)
        print("The series are now ready for task3 (deidentification)")
        
    except Exception as e:
        print(f"\n✗ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Always destroy test database, even if test fails
        if test_db_name:
            destroy_test_database()
        
        print("\n" + "="*70)
        print("TEST COMPLETED")
        print("Your production database was NOT modified")
        print("="*70)

if __name__ == "__main__":
    main()
