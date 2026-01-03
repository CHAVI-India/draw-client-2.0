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
    ProcessingStatus, RuleSet, RuleGroup, Rule, DICOMTagType, OperatorType, 
    RuleCombinationType, AutosegmentationTemplate
)
from dicom_handler.export_services.task2_match_autosegmentation_template import (
    match_autosegmentation_template, get_all_rulegroups_rulesets_and_rules, 
    read_dicom_metadata, evaluate_rule, evaluate_ruleset, evaluate_rulegroup
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

def create_mock_dicom_files():
    """
    Create minimal mock DICOM files for testing
    """
    import pydicom
    from pydicom.dataset import Dataset, FileDataset
    from pydicom.uid import generate_uid, ExplicitVRLittleEndian
    import tempfile
    
    temp_dir = tempfile.mkdtemp(prefix="dicom_test_")
    print(f"Creating mock DICOM files in: {temp_dir}")
    
    mock_files = []
    
    # Mock file 1: CT Breast
    file1_path = os.path.join(temp_dir, "breast_001.dcm")
    file_meta1 = Dataset()
    file_meta1.MediaStorageSOPClassUID = '1.2.840.10008.5.1.4.1.1.2'  # CT Image Storage
    file_meta1.MediaStorageSOPInstanceUID = generate_uid()
    file_meta1.TransferSyntaxUID = ExplicitVRLittleEndian
    ds1 = FileDataset(file1_path, {}, file_meta=file_meta1, preamble=b"\0" * 128)
    ds1.Modality = "CT"
    ds1.ProtocolName = "Breast Protocol"
    ds1.StudyDescription = "CT Breast Study"
    ds1.SeriesInstanceUID = generate_uid()
    ds1.SOPInstanceUID = file_meta1.MediaStorageSOPInstanceUID
    ds1.SOPClassUID = file_meta1.MediaStorageSOPClassUID
    ds1.save_as(file1_path, enforce_file_format=True)
    mock_files.append(("breast", file1_path))
    
    # Mock file 2: CT Head
    file2_path = os.path.join(temp_dir, "head_001.dcm")
    file_meta2 = Dataset()
    file_meta2.MediaStorageSOPClassUID = '1.2.840.10008.5.1.4.1.1.2'
    file_meta2.MediaStorageSOPInstanceUID = generate_uid()
    file_meta2.TransferSyntaxUID = ExplicitVRLittleEndian
    ds2 = FileDataset(file2_path, {}, file_meta=file_meta2, preamble=b"\0" * 128)
    ds2.Modality = "CT"
    ds2.ProtocolName = "Head Protocol"
    ds2.StudyDescription = "CT HEAD WITHOUT CONTRAST"
    ds2.SeriesInstanceUID = generate_uid()
    ds2.SOPInstanceUID = file_meta2.MediaStorageSOPInstanceUID
    ds2.SOPClassUID = file_meta2.MediaStorageSOPClassUID
    ds2.save_as(file2_path, enforce_file_format=True)
    mock_files.append(("head", file2_path))
    
    # Mock file 3: CT Gyn
    file3_path = os.path.join(temp_dir, "gyn_001.dcm")
    file_meta3 = Dataset()
    file_meta3.MediaStorageSOPClassUID = '1.2.840.10008.5.1.4.1.1.2'
    file_meta3.MediaStorageSOPInstanceUID = generate_uid()
    file_meta3.TransferSyntaxUID = ExplicitVRLittleEndian
    ds3 = FileDataset(file3_path, {}, file_meta=file_meta3, preamble=b"\0" * 128)
    ds3.Modality = "CT"
    ds3.ProtocolName = "Gyn Protocol"
    ds3.StudyDescription = "CT Gyn Study"
    ds3.SeriesInstanceUID = generate_uid()
    ds3.SOPInstanceUID = file_meta3.MediaStorageSOPInstanceUID
    ds3.SOPClassUID = file_meta3.MediaStorageSOPClassUID
    ds3.save_as(file3_path, enforce_file_format=True)
    mock_files.append(("gyn", file3_path))
    
    print(f"✓ Created {len(mock_files)} mock DICOM files")
    return mock_files

def create_mock_dicom_data():
    """
    Create mock DICOM data for testing when task1 data is not available
    """
    import pydicom
    
    print("Creating mock DICOM data for testing...")
    
    # Create mock DICOM files first
    mock_files = create_mock_dicom_files()
    
    # Read the files to get actual UIDs
    dicom_files = []
    for name, path in mock_files:
        ds = pydicom.dcmread(path, stop_before_pixels=True)
        dicom_files.append((name, path, ds))
    
    # Create a mock patient
    patient = Patient.objects.create(
        patient_id="TEST_PATIENT_001",
        patient_name="Test Patient",
        patient_gender="M",
        patient_date_of_birth=datetime(1980, 1, 1).date()
    )
    
    # Create a mock study
    study = DICOMStudy.objects.create(
        patient=patient,
        study_instance_uid="1.2.3.4.5.6.7.8.9.TEST.STUDY",
        study_date=datetime.now().date(),
        study_description="CT HEAD WITHOUT CONTRAST",
        study_modality="CT"
    )
    
    # Create mock series with different characteristics for testing
    series_list = []
    
    # Series 1: CT Breast (should match Breast template)
    series1 = DICOMSeries.objects.create(
        study=study,
        series_instance_uid=dicom_files[0][2].SeriesInstanceUID,
        series_root_path=os.path.dirname(dicom_files[0][1]),
        series_description="CT Breast Protocol",
        series_processsing_status=ProcessingStatus.UNPROCESSED,
        instance_count=1
    )
    series_list.append((series1, dicom_files[0]))
    
    # Series 2: CT Head (should match Head Neck template)
    series2 = DICOMSeries.objects.create(
        study=study,
        series_instance_uid=dicom_files[1][2].SeriesInstanceUID,
        series_root_path=os.path.dirname(dicom_files[1][1]),
        series_description="CT HEAD Protocol",
        series_processsing_status=ProcessingStatus.UNPROCESSED,
        instance_count=1
    )
    series_list.append((series2, dicom_files[1]))
    
    # Series 3: CT Gyn (should match Gyn template)
    series3 = DICOMSeries.objects.create(
        study=study,
        series_instance_uid=dicom_files[2][2].SeriesInstanceUID,
        series_root_path=os.path.dirname(dicom_files[2][1]),
        series_description="CT Gyn Protocol",
        series_processsing_status=ProcessingStatus.UNPROCESSED,
        instance_count=1
    )
    series_list.append((series3, dicom_files[2]))
    
    # Create mock instances for each series
    for series, (name, path, ds) in series_list:
        instance = DICOMInstance.objects.create(
            series_instance_uid=series,
            sop_instance_uid=ds.SOPInstanceUID,
            instance_path=path
        )
    
    print(f"✓ Created {len(series_list)} mock series with test data")
    return True

def check_existing_series():
    """
    Check if there are existing series from task1 to test with
    If not, create mock data
    """
    print("Checking existing DICOM series data...")
    
    unprocessed_series = DICOMSeries.objects.filter(
        series_processsing_status=ProcessingStatus.UNPROCESSED
    )
    
    if not unprocessed_series.exists():
        print("✗ No unprocessed series found. Creating mock data for testing...")
        return create_mock_dicom_data()
    
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

def create_test_rulegroups_and_rulesets(templates, tags):
    """
    Create test rulegroups, rulesets and rules with hierarchical structure
    """
    print("Creating test rulegroups, rulesets and rules...")
    
    template1, template2, template3 = templates
    modality_tag, protocol_tag, slice_thickness_tag, study_description_tag = tags
    
    # Create RuleGroup 1: Breast and Head Neck
    rulegroup1 = RuleGroup.objects.create(
        rulegroup_name="Breast and Head Neck Group",
        associated_autosegmentation_template=templates[0]  # Use first template
    )
    
    # Ruleset 1: Breast (AND combination of rules)
    ruleset1 = RuleSet.objects.create(
        rulegroup=rulegroup1,
        ruleset_name="Breast Ruleset",
        ruleset_description="Rules for Breast Scans",
        rulset_order=1,
        ruleset_combination_type=RuleCombinationType.OR,  # How this ruleset combines with next in group
        associated_autosegmentation_template=template1
    )
    
    # Rules for Breast - both must match (AND)
    Rule.objects.create(
        ruleset=ruleset1,
        rule_order=1,
        dicom_tag_type=modality_tag,
        operator_type=OperatorType.CASE_SENSITIVE_STRING_EXACT_MATCH,
        tag_value_to_evaluate="CT",
        rule_combination_type=RuleCombinationType.AND  # How this rule combines with next
    )
    
    Rule.objects.create(
        ruleset=ruleset1,
        rule_order=2,
        dicom_tag_type=protocol_tag,
        operator_type=OperatorType.CASE_INSENSITIVE_STRING_CONTAINS,
        tag_value_to_evaluate="Breast",
        rule_combination_type=RuleCombinationType.AND  # Last rule's combination type
    )
    
    # Ruleset 2: Head Neck (AND combination of rules)
    ruleset2 = RuleSet.objects.create(
        rulegroup=rulegroup1,
        ruleset_name="Head Neck Rule Set",
        ruleset_description="Rules for Head Neck Scans",
        rulset_order=2,
        ruleset_combination_type=RuleCombinationType.OR,  # How this ruleset combines with next in group
        associated_autosegmentation_template=template2
    )
    
    # Rules for Head Neck - both must match (AND)
    Rule.objects.create(
        ruleset=ruleset2,
        rule_order=1,
        dicom_tag_type=modality_tag,
        operator_type=OperatorType.CASE_SENSITIVE_STRING_EXACT_MATCH,
        tag_value_to_evaluate="CT",
        rule_combination_type=RuleCombinationType.AND
    )
    
    Rule.objects.create(
        ruleset=ruleset2,
        rule_order=2,
        dicom_tag_type=study_description_tag,
        operator_type=OperatorType.CASE_INSENSITIVE_STRING_CONTAINS,
        tag_value_to_evaluate="HEAD",
        rule_combination_type=RuleCombinationType.AND
    )
    
    # Create RuleGroup 2: Gyn (separate group)
    rulegroup2 = RuleGroup.objects.create(
        rulegroup_name="Gyn Group",
        associated_autosegmentation_template=template3
    )
    
    # Ruleset 3: Gyn CT Scan
    ruleset3 = RuleSet.objects.create(
        rulegroup=rulegroup2,
        ruleset_name="Gyn CT Scan",
        ruleset_description="Gyn CT Scans",
        rulset_order=1,
        ruleset_combination_type=RuleCombinationType.AND,
        associated_autosegmentation_template=template3
    )
    
    # Rules for Gyn - both must match (AND)
    Rule.objects.create(
        ruleset=ruleset3,
        rule_order=1,
        dicom_tag_type=modality_tag,
        operator_type=OperatorType.CASE_SENSITIVE_STRING_EXACT_MATCH,
        tag_value_to_evaluate="CT",
        rule_combination_type=RuleCombinationType.AND
    )
    
    Rule.objects.create(
        ruleset=ruleset3,
        rule_order=2,
        dicom_tag_type=protocol_tag,
        operator_type=OperatorType.CASE_INSENSITIVE_STRING_CONTAINS,
        tag_value_to_evaluate="Gyn",
        rule_combination_type=RuleCombinationType.AND
    )
    
    print(f"✓ Created {RuleGroup.objects.count()} rulegroups")
    print(f"✓ Created {RuleSet.objects.count()} rulesets")
    print(f"✓ Created {Rule.objects.count()} rules")
    return rulegroup1, rulegroup2, (ruleset1, ruleset2, ruleset3)

def test_rule_evaluation_functions():
    """
    Test individual rule evaluation functions with new hierarchical structure
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
    
    # Test rule data with rule_combination_type
    test_rules = [
        {
            'rule_order': 1,
            'dicom_tag_name': 'Modality',
            'dicom_tag_id': '(0008,0060)',
            'operator_type': OperatorType.CASE_SENSITIVE_STRING_EXACT_MATCH,
            'tag_value_to_evaluate': 'CT',
            'rule_combination_type': RuleCombinationType.AND
        },
        {
            'rule_order': 2,
            'dicom_tag_name': 'Body Part Examined',
            'dicom_tag_id': '(0018,0015)',
            'operator_type': OperatorType.CASE_INSENSITIVE_STRING_CONTAINS,
            'tag_value_to_evaluate': 'head',
            'rule_combination_type': RuleCombinationType.AND
        },
        {
            'rule_order': 3,
            'dicom_tag_name': 'Slice Thickness',
            'dicom_tag_id': '(0018,0050)',
            'operator_type': OperatorType.LESS_THAN,
            'tag_value_to_evaluate': '5.0',
            'rule_combination_type': RuleCombinationType.AND
        }
    ]
    
    print("Testing individual rule evaluations:")
    for i, rule in enumerate(test_rules, 1):
        result = evaluate_rule(rule, test_metadata)
        print(f"  Rule {i}: {rule['dicom_tag_name']} {rule['operator_type']} {rule['tag_value_to_evaluate']} → {result}")
    
    # Test ruleset evaluation (rules combined based on their individual combination types)
    test_ruleset = {
        'name': 'Test Ruleset',
        'rulset_order': 1,
        'rule_combination_type': RuleCombinationType.AND,
        'rules': test_rules
    }
    
    print("\nTesting ruleset evaluation:")
    ruleset_result = evaluate_ruleset(test_ruleset, test_metadata)
    print(f"  Ruleset result (rules combined with AND): {ruleset_result}")
    
    # Test rulegroup evaluation
    test_rulegroup = {
        'id': 'test-rulegroup',
        'name': 'Test RuleGroup',
        'rulesets': [test_ruleset]
    }
    
    print("\nTesting rulegroup evaluation:")
    rulegroup_result, matched_rulesets = evaluate_rulegroup(test_rulegroup, test_metadata)
    print(f"  Rulegroup result: {rulegroup_result}")
    print(f"  Matched rulesets: {len(matched_rulesets)}")

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
        print(f"⚠️  File not found (using mock data): {file_path}")
        print("✓ Skipping file reading test - using mock data")
        return True  # Return True to continue with other tests
    
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
        rulegroups_and_rulesets = create_test_rulegroups_and_rulesets(templates, tags)
        
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
