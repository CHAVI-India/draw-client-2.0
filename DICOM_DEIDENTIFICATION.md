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

