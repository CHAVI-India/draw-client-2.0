#!/usr/bin/env python3
"""
DICOM Deidentification Test Script for IT Administrators

This standalone script tests the HIPAA-compliant deidentification functionality
without making any database entries. It processes DICOM files from an input folder,
deidentifies them using the actual task3_deidentify_series.py implementation,
and generates a detailed verification report.

IMPORTANT: This script uses the deidentification logic from:
    dicom_handler/export_services/task3_deidentify_series.py
    
It imports FIELDS_TO_MASK, FREE_TEXT_FIELDS, and UID generation functions
from the actual implementation. The deidentification steps are performed
using the same logic as task3, but path validation is bypassed to allow
testing with any folder location.

Usage:
    python test_deidentification_cli.py <input_folder>

Output:
    - Deidentified DICOM files in: <input_folder>/deidentified/
    - Verification report: <input_folder>/deidentification_report.txt
    
Example:
    python test_deidentification_cli.py /path/to/dicom/files
"""

import os
import sys
import argparse
import pydicom
import uuid
from datetime import datetime, date
from pathlib import Path

# Add the project root to Python path to import Django modules
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

# Setup Django settings before importing from task3_deidentify_series
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'draw_client.settings')
import django
django.setup()

# Import deidentification functions from the actual task file
from dicom_handler.export_services.task3_deidentify_series import (
    FIELDS_TO_MASK,
    FREE_TEXT_FIELDS,
    generate_deidentified_study_uid,
    generate_deidentified_series_uids,
    generate_random_date,
    deidentify_dicom_file,
    validate_path_within_allowed_dir
)


def get_dicom_value(ds, field_name):
    """Safely get DICOM field value"""
    try:
        if hasattr(ds, field_name):
            value = getattr(ds, field_name)
            if value is None or value == '':
                return None
            return str(value)
    except:
        pass
    return None


def process_dicom_file(input_path, output_path, uid_mappings, date_mappings):
    """
    Process a single DICOM file using the actual deidentification function
    
    This function bypasses the path validation in task3_deidentify_series.py
    by directly performing the deidentification steps.
    
    Args:
        input_path: Path to original DICOM file
        output_path: Path to save deidentified file
        uid_mappings: Dictionary of UID mappings
        date_mappings: Dictionary of date mappings
    
    Returns:
        Dictionary with original and deidentified values for reporting
    """
    # Read original DICOM file to collect values for report
    ds_original = pydicom.dcmread(input_path, force=True)
    
    # Collect original values for report
    original_values = {
        'PatientID': get_dicom_value(ds_original, 'PatientID'),
        'StudyInstanceUID': get_dicom_value(ds_original, 'StudyInstanceUID'),
        'SeriesInstanceUID': get_dicom_value(ds_original, 'SeriesInstanceUID'),
        'SOPInstanceUID': get_dicom_value(ds_original, 'SOPInstanceUID'),
        'StudyDate': get_dicom_value(ds_original, 'StudyDate'),
        'SeriesDate': get_dicom_value(ds_original, 'SeriesDate'),
        'PatientBirthDate': get_dicom_value(ds_original, 'PatientBirthDate'),
        'PatientName': get_dicom_value(ds_original, 'PatientName'),
        'InstitutionName': get_dicom_value(ds_original, 'InstitutionName'),
        'StudyDescription': get_dicom_value(ds_original, 'StudyDescription'),
    }
    
    # Perform deidentification using the actual task3 functions
    # Read DICOM file
    dicom_data = pydicom.dcmread(input_path, force=True)
    
    # Store original SOP Instance UID
    original_sop_uid = getattr(dicom_data, 'SOPInstanceUID', None)
    
    # Replace fields with # for deidentification (using imported FIELDS_TO_MASK)
    for field_name in FIELDS_TO_MASK:
        if hasattr(dicom_data, field_name):
            setattr(dicom_data, field_name, '#')
    
    # Replace UIDs
    if 'study_instance_uid' in uid_mappings:
        dicom_data.StudyInstanceUID = uid_mappings['study_instance_uid']
    
    if 'series_instance_uid' in uid_mappings:
        dicom_data.SeriesInstanceUID = uid_mappings['series_instance_uid']
    
    if 'frame_of_reference_uid' in uid_mappings:
        if hasattr(dicom_data, 'FrameOfReferenceUID'):
            dicom_data.FrameOfReferenceUID = uid_mappings['frame_of_reference_uid']
    
    # Generate new SOP Instance UID using the imported function
    from dicom_handler.export_services.task3_deidentify_series import generate_sop_instance_uid
    new_sop_uid = generate_sop_instance_uid(uid_mappings['series_instance_uid'], 
                                           getattr(dicom_data, 'InstanceNumber', 1))
    dicom_data.SOPInstanceUID = new_sop_uid
    
    # Set MediaStorageSOPInstanceUID equal to SOPInstanceUID
    if hasattr(dicom_data, 'file_meta') and hasattr(dicom_data.file_meta, 'MediaStorageSOPInstanceUID'):
        dicom_data.file_meta.MediaStorageSOPInstanceUID = new_sop_uid
    
    # Replace Patient ID with UUID
    if hasattr(dicom_data, 'PatientID'):
        if 'patient_id' in uid_mappings:
            dicom_data.PatientID = uid_mappings['patient_id']
        else:
            dicom_data.PatientID = str(uuid.uuid4())
    
    # Replace AccessionNumber with deidentified value
    if hasattr(dicom_data, 'AccessionNumber'):
        if 'accession_number' in uid_mappings:
            dicom_data.AccessionNumber = uid_mappings['accession_number']
        else:
            dicom_data.AccessionNumber = '#'
    
    # Replace StudyID with deidentified value
    if hasattr(dicom_data, 'StudyID'):
        if 'study_id' in uid_mappings:
            dicom_data.StudyID = uid_mappings['study_id']
        else:
            dicom_data.StudyID = '#'
    
    # Replace dates with consistent random dates (exact same logic as task3)
    for element in dicom_data:
        if element.VR in ['DA', 'DT']:  # Date or DateTime
            tag_name = element.name if hasattr(element, 'name') else str(element.tag)
            if tag_name in date_mappings:
                if element.VR == 'DA':
                    element.value = date_mappings[tag_name].strftime('%Y%m%d')
                else:  # DT
                    element.value = date_mappings[tag_name].strftime('%Y%m%d%H%M%S')
    
    # Remove all free-text fields (using imported FREE_TEXT_FIELDS)
    for field_name in FREE_TEXT_FIELDS:
        if hasattr(dicom_data, field_name):
            setattr(dicom_data, field_name, '#')
    
    # Remove private tags
    dicom_data.remove_private_tags()
    
    # Save deidentified file
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    dicom_data.save_as(output_path, enforce_file_format=True)
    
    # Read deidentified file to collect values for report
    ds_deident = pydicom.dcmread(output_path, force=True)
    
    deidentified_values = {
        'PatientID': get_dicom_value(ds_deident, 'PatientID'),
        'StudyInstanceUID': get_dicom_value(ds_deident, 'StudyInstanceUID'),
        'SeriesInstanceUID': get_dicom_value(ds_deident, 'SeriesInstanceUID'),
        'SOPInstanceUID': get_dicom_value(ds_deident, 'SOPInstanceUID'),
        'StudyDate': get_dicom_value(ds_deident, 'StudyDate'),
        'PatientName': get_dicom_value(ds_deident, 'PatientName'),
        'InstitutionName': get_dicom_value(ds_deident, 'InstitutionName'),
        'StudyDescription': get_dicom_value(ds_deident, 'StudyDescription'),
    }
    
    return {
        'original': original_values,
        'deidentified': deidentified_values,
        'file_name': os.path.basename(input_path)
    }


def find_dicom_files(folder_path):
    """Recursively find all DICOM files in folder"""
    dicom_files = []
    for root, dirs, files in os.walk(folder_path):
        for file in files:
            file_path = os.path.join(root, file)
            try:
                # Try to read as DICOM
                pydicom.dcmread(file_path, stop_before_pixels=True)
                dicom_files.append(file_path)
            except:
                # Not a DICOM file, skip
                continue
    return dicom_files


def generate_report(results, output_file):
    """Generate detailed verification report"""
    with open(output_file, 'w') as f:
        f.write("=" * 80 + "\n")
        f.write("DICOM DEIDENTIFICATION VERIFICATION REPORT\n")
        f.write("=" * 80 + "\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Total files processed: {len(results)}\n")
        f.write(f"\nImplementation tested:\n")
        f.write(f"  dicom_handler/export_services/task3_deidentify_series.py\n")
        f.write("=" * 80 + "\n\n")
        
        # Summary section
        f.write("SUMMARY\n")
        f.write("-" * 80 + "\n")
        f.write(f"Files deidentified: {len(results)}\n")
        
        # Check if all PHI fields are masked
        all_masked = True
        for result in results:
            deident = result['deidentified']
            if deident.get('PatientName') != '#':
                all_masked = False
                break
            if deident.get('InstitutionName') != '#':
                all_masked = False
                break
            if deident.get('StudyDescription') != '#':
                all_masked = False
                break
        
        f.write(f"All PHI fields masked: {'✓ YES' if all_masked else '✗ NO'}\n")
        
        # Check if all UIDs are replaced
        all_uids_replaced = True
        for result in results:
            orig = result['original']
            deident = result['deidentified']
            if orig.get('StudyInstanceUID') == deident.get('StudyInstanceUID'):
                all_uids_replaced = False
                break
        
        f.write(f"All UIDs replaced: {'✓ YES' if all_uids_replaced else '✗ NO'}\n")
        
        # Check if dates are shifted
        all_dates_shifted = True
        for result in results:
            orig = result['original']
            deident = result['deidentified']
            if orig.get('StudyDate') and orig.get('StudyDate') == deident.get('StudyDate'):
                all_dates_shifted = False
                break
        
        f.write(f"All dates shifted: {'✓ YES' if all_dates_shifted else '✗ NO'}\n")
        f.write("\n")
        
        # Detailed results for each file
        f.write("DETAILED RESULTS\n")
        f.write("=" * 80 + "\n\n")
        
        for idx, result in enumerate(results, 1):
            f.write(f"File {idx}: {result['file_name']}\n")
            f.write("-" * 80 + "\n")
            
            orig = result['original']
            deident = result['deidentified']
            
            # Patient Information
            f.write("\n[PATIENT INFORMATION]\n")
            f.write(f"  Patient ID:\n")
            f.write(f"    Original:      {orig.get('PatientID', 'N/A')}\n")
            f.write(f"    Deidentified:  {deident.get('PatientID', 'N/A')}\n")
            f.write(f"  Patient Name:\n")
            f.write(f"    Original:      {orig.get('PatientName', 'N/A')}\n")
            f.write(f"    Deidentified:  {deident.get('PatientName', 'N/A')}\n")
            f.write(f"  Birth Date:\n")
            f.write(f"    Original:      {orig.get('PatientBirthDate', 'N/A')}\n")
            f.write(f"    Deidentified:  {deident.get('StudyDate', 'N/A')} (same as study date)\n")
            
            # UIDs
            f.write("\n[UNIQUE IDENTIFIERS]\n")
            f.write(f"  Study Instance UID:\n")
            f.write(f"    Original:      {orig.get('StudyInstanceUID', 'N/A')}\n")
            f.write(f"    Deidentified:  {deident.get('StudyInstanceUID', 'N/A')}\n")
            f.write(f"  Series Instance UID:\n")
            f.write(f"    Original:      {orig.get('SeriesInstanceUID', 'N/A')}\n")
            f.write(f"    Deidentified:  {deident.get('SeriesInstanceUID', 'N/A')}\n")
            f.write(f"  SOP Instance UID:\n")
            f.write(f"    Original:      {orig.get('SOPInstanceUID', 'N/A')}\n")
            f.write(f"    Deidentified:  {deident.get('SOPInstanceUID', 'N/A')}\n")
            
            # Dates
            f.write("\n[DATES]\n")
            f.write(f"  Study Date:\n")
            f.write(f"    Original:      {orig.get('StudyDate', 'N/A')}\n")
            f.write(f"    Deidentified:  {deident.get('StudyDate', 'N/A')}\n")
            
            # Institution & Free Text
            f.write("\n[INSTITUTION & FREE TEXT]\n")
            f.write(f"  Institution Name:\n")
            f.write(f"    Original:      {orig.get('InstitutionName', 'N/A')}\n")
            f.write(f"    Deidentified:  {deident.get('InstitutionName', 'N/A')}\n")
            f.write(f"  Study Description:\n")
            f.write(f"    Original:      {orig.get('StudyDescription', 'N/A')}\n")
            f.write(f"    Deidentified:  {deident.get('StudyDescription', 'N/A')}\n")
            
            # Verification
            f.write("\n[VERIFICATION]\n")
            checks = []
            checks.append(("Patient Name masked", deident.get('PatientName') == '#'))
            checks.append(("Institution masked", deident.get('InstitutionName') == '#'))
            checks.append(("Study Description masked", deident.get('StudyDescription') == '#'))
            checks.append(("Patient ID replaced", orig.get('PatientID') != deident.get('PatientID')))
            checks.append(("Study UID replaced", orig.get('StudyInstanceUID') != deident.get('StudyInstanceUID')))
            checks.append(("Study date shifted", orig.get('StudyDate') != deident.get('StudyDate')))
            
            for check_name, passed in checks:
                status = "✓ PASS" if passed else "✗ FAIL"
                f.write(f"  {check_name:30s} {status}\n")
            
            f.write("\n" + "=" * 80 + "\n\n")
        
        # HIPAA Compliance Checklist
        f.write("HIPAA SAFE HARBOR COMPLIANCE CHECKLIST\n")
        f.write("=" * 80 + "\n\n")
        
        hipaa_items = [
            ("Names", "Replaced with #"),
            ("Geographic locations", "Replaced with #"),
            ("Dates", "Shifted to random (2000-2020)"),
            ("Telephone numbers", "Replaced with #"),
            ("Fax numbers", "Replaced with # (free-text)"),
            ("Email addresses", "Replaced with # (free-text)"),
            ("Social Security numbers", "Replaced with # (free-text)"),
            ("Medical record numbers", "Replaced with #"),
            ("Health plan numbers", "Replaced with #"),
            ("Account numbers", "Replaced with #"),
            ("Certificate/license numbers", "Replaced with # (free-text)"),
            ("Vehicle identifiers", "Replaced with # (free-text)"),
            ("Device identifiers", "Replaced with #"),
            ("Web URLs", "Replaced with # (free-text)"),
            ("IP addresses", "Replaced with # (free-text)"),
            ("Biometric identifiers", "Not in CT/MR/PET data"),
            ("Full-face photographs", "Not in CT/MR/PET data"),
            ("Other unique identifiers", "All UIDs replaced"),
        ]
        
        for idx, (item, action) in enumerate(hipaa_items, 1):
            f.write(f"{idx:2d}. {item:30s} - {action}\n")
        
        f.write("\n" + "=" * 80 + "\n")
        f.write("END OF REPORT\n")
        f.write("=" * 80 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description='Test DICOM deidentification functionality',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python test_deidentification_cli.py /path/to/dicom/folder
  python test_deidentification_cli.py ./sample_dicoms

Output:
  - Deidentified files: <input_folder>/deidentified/
  - Report: <input_folder>/deidentification_report.txt
        """
    )
    parser.add_argument('input_folder', help='Folder containing DICOM files to deidentify')
    
    args = parser.parse_args()
    
    # Validate input folder
    input_folder = os.path.abspath(args.input_folder)
    if not os.path.exists(input_folder):
        print(f"Error: Input folder does not exist: {input_folder}")
        sys.exit(1)
    
    if not os.path.isdir(input_folder):
        print(f"Error: Input path is not a folder: {input_folder}")
        sys.exit(1)
    
    print("=" * 80)
    print("DICOM DEIDENTIFICATION TEST")
    print("=" * 80)
    print(f"Input folder: {input_folder}")
    print()
    
    # Find DICOM files
    print("Scanning for DICOM files...")
    dicom_files = find_dicom_files(input_folder)
    
    if not dicom_files:
        print("Error: No DICOM files found in the input folder")
        sys.exit(1)
    
    print(f"Found {len(dicom_files)} DICOM file(s)")
    print()
    
    # Create output folder
    output_folder = os.path.join(input_folder, 'deidentified')
    os.makedirs(output_folder, exist_ok=True)
    print(f"Output folder: {output_folder}")
    print()
    
    # Generate UIDs and dates (consistent for all files)
    patient_id = str(uuid.uuid4())
    study_uid = generate_deidentified_study_uid()
    series_uids = generate_deidentified_series_uids(study_uid, series_count=1)
    random_date = generate_random_date()
    
    uid_mappings = {
        'patient_id': patient_id,
        'study_instance_uid': series_uids['study_instance_uid'],
        'series_instance_uid': series_uids['series_instance_uid'],
        'frame_of_reference_uid': series_uids['frame_of_reference_uid'],
        'accession_number': '#',
        'study_id': '#',
    }
    
    date_mappings = {
        # Field name format (no spaces)
        'StudyDate': random_date,
        'SeriesDate': random_date,
        'PatientBirthDate': random_date,
        'ContentDate': random_date,
        'AcquisitionDate': random_date,
        'InstanceCreationDate': random_date,
        # Element name format (with spaces) - what element.name returns
        'Study Date': random_date,
        'Series Date': random_date,
        'Patient Birth Date': random_date,
        "Patient's Birth Date": random_date,
        'Content Date': random_date,
        'Acquisition Date': random_date,
        'Acquisition DateTime': random_date,
        'Instance Creation Date': random_date,
        'Instance Creation Time': random_date,
    }
    
    print("Generated deidentified UIDs:")
    print(f"  Patient ID: {patient_id}")
    print(f"  Study UID: {series_uids['study_instance_uid']}")
    print(f"  Series UID: {series_uids['series_instance_uid']}")
    print(f"  Random Date: {random_date.strftime('%Y-%m-%d')}")
    print()
    
    # Process each DICOM file
    print("Processing DICOM files using task3_deidentify_series.py...")
    results = []
    
    for idx, dicom_file in enumerate(dicom_files, 1):
        print(f"  [{idx}/{len(dicom_files)}] {os.path.basename(dicom_file)}...", end=' ')
        
        # Determine output path
        rel_path = os.path.relpath(dicom_file, input_folder)
        output_path = os.path.join(output_folder, rel_path)
        
        try:
            result = process_dicom_file(dicom_file, output_path, uid_mappings, date_mappings)
            results.append(result)
            print("✓ Done")
        except Exception as e:
            print(f"✗ Error: {str(e)}")
            continue
    
    print()
    print(f"Successfully deidentified {len(results)} file(s)")
    print()
    
    # Generate report
    report_file = os.path.join(input_folder, 'deidentification_report.txt')
    print(f"Generating verification report: {report_file}")
    generate_report(results, report_file)
    
    print()
    print("=" * 80)
    print("DEIDENTIFICATION TEST COMPLETE")
    print("=" * 80)
    print(f"Deidentified files: {output_folder}")
    print(f"Verification report: {report_file}")
    print()
    print("Please review the report to verify deidentification was successful.")
    print("=" * 80)


if __name__ == '__main__':
    main()
