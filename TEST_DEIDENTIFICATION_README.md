# DICOM Deidentification Test Script

## Overview

The `test_deidentification_cli.py` script is a standalone CLI tool for IT administrators to independently verify that the DICOM deidentification functionality works correctly.

## Key Features

✅ **Tests the actual implementation** - Imports and uses functions from `dicom_handler/export_services/task3_deidentify_series.py`  
✅ **No database required** - Runs without making any database entries  
✅ **Detailed verification report** - Shows original vs deidentified values for all files  
✅ **HIPAA compliance checklist** - Verifies all 18 Safe Harbor identifiers are addressed  

## Usage

```bash
python test_deidentification_cli.py <input_folder>
```

### Example

```bash
python test_deidentification_cli.py /path/to/dicom/files
```

## What It Does

1. **Scans input folder** - Recursively finds all DICOM files
2. **Generates consistent UIDs** - Creates deidentified UIDs for patient, study, series
3. **Processes each file** - Calls the actual `deidentify_dicom_file()` function from task3
4. **Saves deidentified files** - Outputs to `<input_folder>/deidentified/`
5. **Generates report** - Creates detailed verification report

## Output

### Deidentified Files
- **Location**: `<input_folder>/deidentified/`
- **Format**: Same structure as input folder
- **Content**: Fully deidentified DICOM files

### Verification Report
- **Location**: `<input_folder>/deidentification_report.txt`
- **Content**:
  - Summary of files processed
  - Verification checks (all PHI masked, all UIDs replaced, all dates shifted)
  - Detailed results for each file showing original vs deidentified values
  - HIPAA Safe Harbor compliance checklist

## Report Example

```
================================================================================
DICOM DEIDENTIFICATION VERIFICATION REPORT
================================================================================
Generated: 2026-06-19 11:15:30
Total files processed: 5

Implementation tested:
  dicom_handler/export_services/task3_deidentify_series.py
================================================================================

SUMMARY
--------------------------------------------------------------------------------
Files deidentified: 5
All PHI fields masked: ✓ YES
All UIDs replaced: ✓ YES
All dates shifted: ✓ YES

DETAILED RESULTS
================================================================================

File 1: CT_001.dcm
--------------------------------------------------------------------------------

[PATIENT INFORMATION]
  Patient ID:
    Original:      12345
    Deidentified:  a1b2c3d4-e5f6-7890-1234-567890abcdef
  Patient Name:
    Original:      Doe^John
    Deidentified:  #
  Birth Date:
    Original:      19800520
    Deidentified:  20150810 (same as study date)

[UNIQUE IDENTIFIERS]
  Study Instance UID:
    Original:      1.2.840.113619.2.55.3.12345
    Deidentified:  1.2.826.0.1.3680043.10.1561.123.45.678
  Series Instance UID:
    Original:      1.2.840.113619.2.55.3.12345.1
    Deidentified:  1.2.826.0.1.3680043.10.1561.123.45.678.1
  SOP Instance UID:
    Original:      1.2.840.113619.2.55.3.12345.1.1
    Deidentified:  1.2.826.0.1.3680043.10.1561.123.45.678.1.1234567.890

[DATES]
  Study Date:
    Original:      20240315
    Deidentified:  20150810

[INSTITUTION & FREE TEXT]
  Institution Name:
    Original:      General Hospital
    Deidentified:  #
  Study Description:
    Original:      CT Chest with Contrast
    Deidentified:  #

[VERIFICATION]
  Patient Name masked            ✓ PASS
  Institution masked             ✓ PASS
  Study Description masked       ✓ PASS
  Patient ID replaced            ✓ PASS
  Study UID replaced             ✓ PASS
  Study date shifted             ✓ PASS

================================================================================

HIPAA SAFE HARBOR COMPLIANCE CHECKLIST
================================================================================

 1. Names                         - Replaced with #
 2. Geographic locations          - Replaced with #
 3. Dates                         - Shifted to random (2000-2020)
 4. Telephone numbers             - Replaced with #
 5. Fax numbers                   - Replaced with # (free-text)
 6. Email addresses               - Replaced with # (free-text)
 7. Social Security numbers       - Replaced with # (free-text)
 8. Medical record numbers        - Replaced with #
 9. Health plan numbers           - Replaced with #
10. Account numbers               - Replaced with #
11. Certificate/license numbers   - Replaced with # (free-text)
12. Vehicle identifiers           - Replaced with # (free-text)
13. Device identifiers            - Replaced with #
14. Web URLs                      - Replaced with # (free-text)
15. IP addresses                  - Replaced with # (free-text)
16. Biometric identifiers         - Not in CT/MR/PET data
17. Full-face photographs         - Not in CT/MR/PET data
18. Other unique identifiers      - All UIDs replaced

================================================================================
END OF REPORT
================================================================================
```

## What Gets Tested

The script verifies that the actual `task3_deidentify_series.py` implementation:

### ✅ Removes 50 DICOM Fields
- 9 person names
- 4 institution/location fields
- 4 contact information fields
- 4 medical record numbers
- 5 device identifiers
- 6 study/order numbers
- 4 sequences
- 10 free-text fields
- 4 additional identifiers

### ✅ Replaces All UIDs
- Patient ID → Random UUID
- Study Instance UID → Deidentified UID
- Series Instance UID → Deidentified UID
- SOP Instance UID → Deidentified UID
- Frame of Reference UID → Deidentified UID

### ✅ Shifts All Dates
- All DA/DT fields shifted to random date (2000-2020)
- Consistent per study

### ✅ Removes Private Tags
- All vendor-specific private tags removed

## Requirements

- Python 3.6+
- pydicom
- Access to `dicom_handler/export_services/task3_deidentify_series.py`

## Important Notes

1. **This is a true test** - The script imports and uses the actual production deidentification functions
2. **No database entries** - Safe to run without affecting the database
3. **Preserves folder structure** - Deidentified files maintain the same folder structure as input
4. **Consistent UIDs** - All files in a test run get the same patient/study/series UIDs
5. **Read-only on input** - Original files are never modified

## Troubleshooting

### Import Error
If you get an import error, make sure you're running the script from the project root:
```bash
cd /home/santam/draw-client-2.0
python test_deidentification_cli.py <input_folder>
```

### Path Validation Error
The deidentification function validates output paths. If you get a path validation error, ensure the output folder is within the allowed directory structure.

### No DICOM Files Found
The script only processes valid DICOM files. If no files are found, check that your input folder contains DICOM files (not just images with .dcm extension).

## For IT Administrators

This script allows you to:

1. **Verify deidentification works** before deploying to production
2. **Test with sample data** without affecting the database
3. **Generate compliance reports** for auditing purposes
4. **Validate HIPAA compliance** against Safe Harbor requirements

The generated report can be used as evidence of HIPAA compliance testing.
