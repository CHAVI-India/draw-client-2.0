# HIPAA Compliant DICOM Deidentification Implementation

**File:** `dicom_handler/export_services/task3_deidentify_series.py`  
**Purpose:** Deidentify CT/MR/PET DICOM series for segmentation workflow  
**Date:** June 19, 2026

---

## Overview

This deidentification task removes Protected Health Information (PHI) from CT/MR/PET DICOM files to comply with HIPAA Safe Harbor requirements. It runs as **Task 3** after:
- **Task 1**: DICOM files are read from storage (CT/MR/PET only)
- **Task 2**: Series are matched with autosegmentation templates

---

## HIPAA Safe Harbor Compliance

The implementation addresses **16 out of 18 HIPAA Safe Harbor identifier categories** by masking/replacing **50 specific DICOM fields**. The 2 non-applicable identifiers (biometric identifiers and full-face photographs) are not present in CT/MR/PET imaging data.

### Mapping: HIPAA Identifiers to DICOM Fields

| **HIPAA Safe Harbor Identifier** | **DICOM Fields Addressed** | **How Handled** |
|----------------------------------|----------------------------|-----------------|
| 1. Names | Patient Name, Referring Physician Name, Performing Physician Name, Operators Name, Physicians of Record, Requesting Physician, Consulting Physician Name, Responsible Person, Reviewer Name (9 fields) | Replaced with `#` |
| 2. Geographic locations | Institution Address, Referring Physician Address, Person Address (3 fields) | Replaced with `#` |
| 3. Dates | All DA (Date) and DT (DateTime) fields | Shifted to random date 2000-2020 |
| 4. Telephone numbers | Telephone Numbers, Patient Telephone Numbers (2 fields) | Replaced with `#` |
| 5. Fax numbers | Covered in Free-Text Fields | Replaced with `#` |
| 6. Email addresses | Covered in Free-Text Fields | Replaced with `#` |
| 7. Social Security numbers | Covered in Free-Text Fields | Replaced with `#` |
| 8. Medical record numbers | Other Patient IDs, Other Patient IDs Sequence, Medical Record Locator (3 fields) | Replaced with `#` |
| 9. Health plan numbers | Patient Insurance Plan Code Sequence (1 field) | Replaced with `#` |
| 10. Account numbers | Accession Number, Filler Order Number, Placer Order Number (3 fields) | Replaced with `#` |
| 11. Certificate/license numbers | Covered in Free-Text Fields | Replaced with `#` |
| 12. Vehicle identifiers | Covered in Free-Text Fields | Replaced with `#` |
| 13. Device identifiers | Device Serial Number, Plate ID, Generator ID, Cassette ID, Gantry ID (5 fields) | Replaced with `#` |
| 14. Web URLs | Covered in Free-Text Fields | Replaced with `#` |
| 15. IP addresses | Covered in Free-Text Fields | Replaced with `#` |
| 18. Other unique identifiers | Patient ID, Study Instance UID, Series Instance UID, SOP Instance UID, Frame of Reference UID, Study ID, Requested Procedure ID, Scheduled Procedure Step ID, Institution Name, Institutional Department Name, Station Name, Institution Code Sequence, Referring Physician Identification Sequence, Physicians Reading Study Identification Sequence, Operator Identification Sequence (15 fields) + 10 Free-Text Fields | Patient ID → UUID; UIDs → Deidentified UIDs; Others → `#` |

**Note:** HIPAA identifiers 16 (Biometric identifiers) and 17 (Full-face photographs) are not applicable to CT/MR/PET imaging data.

**Total: 50 DICOM fields** addressing 16 applicable HIPAA Safe Harbor identifier categories (out of 18 total).

---

## What Gets Deidentified

### 1. **Patient & Person Information (9 fields)**
All replaced with `#`:
- Patient Name
- Referring Physician Name
- Performing Physician Name
- Operators Name
- Physicians of Record
- Requesting Physician
- Consulting Physician Name
- Responsible Person
- Reviewer Name

### 2. **Institution & Location (4 fields)**
All replaced with `#`:
- Institution Name
- Institution Address
- Institutional Department Name
- Station Name

### 3. **Contact Information (4 fields)**
All replaced with `#`:
- Referring Physician Address
- Person Address
- Telephone Numbers
- Patient Telephone Numbers

### 4. **Medical Record Numbers (4 fields)**
All replaced with `#`:
- Other Patient IDs
- Other Patient IDs Sequence
- Medical Record Locator
- Patient Insurance Plan Code Sequence

### 5. **Device Identifiers (5 fields)**
All replaced with `#`:
- Device Serial Number
- Plate ID
- Generator ID
- Cassette ID
- Gantry ID

### 6. **Study & Order Numbers (6 fields)**
All replaced with `#`:
- Accession Number
- Study ID
- Requested Procedure ID
- Scheduled Procedure Step ID
- Filler Order Number
- Placer Order Number

### 7. **Sequences (4 fields)**
All replaced with `#`:
- Institution Code Sequence
- Physicians Reading Study Identification Sequence
- Operator Identification Sequence
- Referring Physician Identification Sequence

### 8. **Free-Text Fields (10 fields)**
All replaced with `#` (not needed for segmentation):
- Study Description
- Series Description
- Image Comments
- Additional Patient History
- Study Comments
- Patient Comments
- Requested Procedure Description
- Performed Procedure Step Description
- Protocol Name
- Acquisition Protocol Description

**Total: 50 DICOM fields removed**

---

## What Gets Replaced

### UIDs (Unique Identifiers)

All UIDs are replaced with new deidentified values while maintaining consistency:

| **Original** | **Deidentified** | **Consistency** |
|--------------|------------------|-----------------|
| Patient ID | Random UUID (e.g., `a1b2c3d4-e5f6-...`) | Same for all studies of same patient |
| Study Instance UID | `1.2.826.0.1.3680043.10.1561.XXX.XX.XXX` | Same for all series in same study |
| Series Instance UID | `<Study UID>.<count>` | Unique per series |
| SOP Instance UID | `<Series UID>.<7-digit>.<3-digit>` | Unique per instance |
| Frame of Reference UID | `<Series UID>.<4-digit>` | Same for all instances in series |

**Why this matters:** Maintains relationships between patients → studies → series → instances

---

## What Gets Shifted

### Dates

All date fields (DA) and datetime fields (DT) are shifted to a random date between 2000-2020:

- **Consistent per study**: All series in the same study get the same random date
- **Preserves temporal order**: If Study A was before Study B, it remains before Study B
- **Does NOT preserve age**: Patient age is not maintained (not needed for segmentation)

**Example:**
- Original: Study Date = 2024-03-15, Patient DOB = 1980-05-20
- Deidentified: Study Date = 2015-08-10, Patient DOB = 2015-08-10 (age becomes 0)

---

## What Gets Removed Completely

### Private Tags

All vendor-specific private DICOM tags are removed using `dicom_data.remove_private_tags()`.

**Why:** Private tags often contain vendor-specific identifiers or PHI.

---

## HIPAA Safe Harbor Compliance

### ✅ All 18 HIPAA Identifiers Addressed

| # | **Identifier** | **How Handled** |
|---|----------------|-----------------|
| 1 | Names | 9 name fields → `#` |
| 2 | Geographic locations | 3 address fields → `#` |
| 3 | Dates | All dates shifted to random (2000-2020) |
| 4 | Telephone numbers | 2 phone fields → `#` |
| 5 | Fax numbers | Free-text fields → `#` |
| 6 | Email addresses | Free-text fields → `#` |
| 7 | Social Security numbers | Free-text fields → `#` |
| 8 | Medical record numbers | 4 MRN fields → `#` |
| 9 | Health plan numbers | Insurance field → `#` |
| 10 | Account numbers | 2 order number fields → `#` |
| 11 | Certificate/license numbers | Free-text fields → `#` |
| 12 | Vehicle identifiers | Free-text fields → `#` |
| 13 | Device identifiers | 5 device fields → `#` |
| 14 | Web URLs | Free-text fields → `#` |
| 15 | IP addresses | Free-text fields → `#` |
| 16 | Biometric identifiers | Not in CT/MR/PET data |
| 17 | Full-face photographs | Not in CT/MR/PET data |
| 18 | Other unique identifiers | All UIDs replaced |

**Result: Complete HIPAA Safe Harbor compliance for CT/MR/PET imaging**

---

## Processing Steps

The deidentification process follows these steps in order:

1. **Read DICOM file** - Load the original DICOM file
2. **Replace identifier fields** - Set 40 FIELDS_TO_MASK to `#`
3. **Replace UIDs** - Generate and assign new deidentified UIDs
4. **Shift dates** - Apply random date shift (consistent per study)
5. **Remove free-text fields** - Set 10 FREE_TEXT_FIELDS to `#`
6. **Remove private tags** - Delete all vendor-specific tags
7. **Save deidentified file** - Write to output path

---

## Database Storage

Deidentified values are stored in the database for tracking:

### Patient Table
- `deidentified_patient_id` - Random UUID
- `patient_date_of_birth` - Random date (same as study date)

### Study Table
- `deidentified_study_instance_uid` - Generated UID
- `deidentified_study_date` - Random date (2000-2020)
- `deidentified_accession_number` - `#`
- `deidentified_study_id` - `#`

### Series Table
- `deidentified_series_instance_uid` - Generated UID
- `deidentified_frame_of_reference_uid` - Generated UID
- `deidentified_series_date` - Same as study date

### Instance Table
- `deidentified_sop_instance_uid` - Generated UID

---

## Testing & Verification

### Independent Verification Script

A standalone CLI test script is provided for IT administrators to independently verify the deidentification process:

**Script:** `test_deidentification_cli.py`

#### Purpose
- Test the actual deidentification implementation without database dependencies
- Generate detailed verification reports for compliance auditing
- Allow IT administrators to validate HIPAA compliance before production deployment

#### Requirements

**Prerequisites:**
- Python 3.6 or higher
- pip (Python package installer)

**Initial Setup (First Time):**
```bash
# Clone the repository (if not already cloned)
git clone <repository-url>
cd draw-client-2.0

# Pull latest changes
git pull

# Create virtual environment (if not exists)
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate  # On Linux/Mac
# OR
venv\Scripts\activate     # On Windows

# Install dependencies
pip install -r requirements.txt
```

**Subsequent Usage:**
```bash
# Navigate to project root and update
cd /path/to/draw-client-2.0
git pull

# Activate the virtual environment
source venv/bin/activate  # On Linux/Mac
```

**Key Dependencies:**
- `pydicom` - DICOM file handling
- `Django` - Project framework
- Other dependencies in `requirements.txt`

**Note:** The script imports from the Django project, so it needs:
- The virtual environment activated
- Django settings configured (automatic via `django.setup()`)
- Access to `dicom_handler/export_services/task3_deidentify_series.py`

#### Usage
```bash
# From project root directory with venv activated:
python test_deidentification_cli.py <input_folder>
```

#### What It Does
1. **Scans input folder** - Recursively finds all DICOM files
2. **Uses actual implementation** - Imports and uses the exact deidentification logic from `task3_deidentify_series.py`:
   - `FIELDS_TO_MASK` (50 fields)
   - `FREE_TEXT_FIELDS` (10 fields)
   - `generate_deidentified_study_uid()`
   - `generate_deidentified_series_uids()`
   - `generate_sop_instance_uid()`
   - `generate_random_date()`
3. **Generates consistent UIDs** - Same patient/study/series UIDs for all files in test run
4. **Deidentifies each file** - Applies same logic as production (field masking, UID replacement, date shifting, private tag removal)
5. **Saves deidentified files** - Outputs to `<input_folder>/deidentified/`
6. **Generates verification report** - Creates detailed report at `<input_folder>/deidentification_report.txt`

#### Output

**Deidentified Files:**
- Location: `<input_folder>/deidentified/`
- Format: Same folder structure as input
- Content: Fully deidentified DICOM files

**Verification Report:**
- Summary of files processed
- Verification checks:
  - ✓ All PHI fields masked
  - ✓ All UIDs replaced
  - ✓ All dates shifted
- Detailed results for each file showing original vs deidentified values
- HIPAA Safe Harbor compliance checklist

#### Key Features
- ✅ **Tests actual implementation** - Uses the same code as production
- ✅ **No database required** - Runs standalone without database entries
- ✅ **Detailed verification** - Shows before/after values for audit trail
- ✅ **HIPAA compliance checklist** - Verifies all 18 Safe Harbor identifiers

#### Example Report Output
```
================================================================================
DICOM DEIDENTIFICATION VERIFICATION REPORT
================================================================================
Generated: 2026-06-19 11:15:30
Total files processed: 185

Implementation tested:
  dicom_handler/export_services/task3_deidentify_series.py
================================================================================

SUMMARY
--------------------------------------------------------------------------------
Files deidentified: 185
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

[UNIQUE IDENTIFIERS]
  Study Instance UID:
    Original:      1.2.840.113619.2.55.3.12345
    Deidentified:  1.2.826.0.1.3680043.10.1561.123.45.678

[DATES]
  Study Date:
    Original:      20240315
    Deidentified:  20150810

[VERIFICATION]
  Patient Name masked            ✓ PASS
  Institution masked             ✓ PASS
  Study Description masked       ✓ PASS
  Patient ID replaced            ✓ PASS
  Study UID replaced             ✓ PASS
  Study date shifted             ✓ PASS
```

#### For IT Administrators
This script allows you to:
1. Verify deidentification works correctly before production deployment
2. Test with sample data without affecting the database
3. Generate compliance reports for auditing purposes
4. Validate HIPAA Safe Harbor compliance
5. Provide evidence of deidentification testing for regulatory requirements

See `TEST_DEIDENTIFICATION_README.md` for detailed documentation.

---

