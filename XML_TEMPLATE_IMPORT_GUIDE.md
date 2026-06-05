# XML Template Import Wizard - User Guide

## Overview

The XML Template Import Wizard allows you to bulk import structure properties from predefined XML template files (e.g., Varian Eclipse format) into your autosegmentation templates. This feature automatically maps XML structures to autosegmentation structures and populates the `StructureProperties` model with ROI labels, colors, and types.

## Features

- **XML Parsing**: Supports Varian Eclipse XML format and similar structure template files
- **Auto-Mapping**: Automatically suggests structure mappings based on name matching
- **Bulk Import**: Import multiple structure properties in one workflow
- **Additional Structures**: Import unmapped structures as additional contours
- **Color Conversion**: Automatically converts various color formats to DICOM RGB format
- **Validation**: Validates ROI labels (TG263 standard), color values, and duplicate names
- **Duplicate Prevention**: Ensures no duplicate ROI names within a template
- **Review Step**: Review all mappings before saving to database
- **4-Step Wizard**: Upload → Map → Review → Additional Structures

## Workflow

### Step 1: Upload XML Template

1. Navigate to the template detail page
2. Click **"Import XML Template"** button
3. Select the autosegmentation template you want to map to
4. Upload your XML file (max 10MB)
5. Click **"Next: Map Structures"**

**Note**: Only Varian Eclipse XML format is currently supported.

### Step 2: Map Structures

The wizard will:
- Parse the XML file and extract all structures
- Auto-suggest mappings based on structure name matching (highlighted in green)
- Display structure information from the XML (name, type, color)

For each structure, you can:
- **Select Autosegmentation Structure**: Choose which autosegmentation structure to map to
- **Edit ROI Label**: Modify the preferred ROI label (max 16 characters per TG263 standard)
- **Select RT ROI Type**: Choose the structure type (ORGAN, OAR, PTV, CTV, etc.)
- **Edit Color**: Modify the DICOM color in R\G\B format (e.g., 255\0\0 for red)
- **Skip Structure**: Check to skip importing this structure

Click **"Next: Review Mappings"** when done.

### Step 3: Review Mappings

- Review all mapped structures in a summary table
- Verify ROI labels, types, and colors
- Check for any validation warnings
- Click **"Next: Additional Structures"** to proceed

### Step 4: Select Additional Structures

This step shows **unmapped structures** from the XML file that weren't matched to autosegmentation structures.

You can:
- **Select structures** to import as `AdditionalStructures`
- These will be included in the DICOM RT Structure Set but won't have AI segmentation
- Useful for support structures, reference contours, or planning structures
- Preview structure details (name, type, color) before selecting

Click **"Save All"** to complete the import.

The wizard will:
- Create new `StructureProperties` entries for mapped structures
- Update existing properties if they already exist
- Create `AdditionalStructures` entries for selected unmapped structures
- **Validate for duplicate names** across all structure types
- Display a success message with counts of created/updated entries

## Supported XML Formats

### Varian Eclipse Structure Templates

The parser supports Varian Eclipse XML structure template format with the following elements:

```xml
<StructureTemplate>
  <Preview ID="..." Diagnosis="..." TreatmentSite="..." Description="..."/>
  <Structures>
    <Structure ID="..." Name="...">
      <Identification>
        <VolumeType>Organ</VolumeType>
      </Identification>
      <ColorAndStyle>Yellow</ColorAndStyle>
    </Structure>
  </Structures>
</StructureTemplate>
```

### Supported Color Formats

The parser automatically converts these color formats to DICOM RGB:

- **Named colors**: `Yellow`, `Cyan`, `Red`, `Green`, `Blue`, etc.
- **Segment format**: `Segment - Cyan`
- **RGB format**: `RGB 255 0 0`
- **Concatenated RGB**: `RGB255228181` (parsed as RGB components)
- **Special formats**: `Skin Rendering` (converted to skin color)

### Volume Type Mapping

XML volume types are automatically mapped to DICOM RT ROI Interpreted Types:

| XML Volume Type | RT ROI Interpreted Type |
|----------------|------------------------|
| ORGAN          | ORGAN                  |
| OAR            | OAR                    |
| PTV            | PTV                    |
| CTV            | CTV                    |
| GTV            | GTV                    |
| EXTERNAL/BODY  | EXTERNAL               |
| AVOIDANCE      | AVOIDANCE              |
| CONTROL        | CONTROL                |

## File Structure

### New Files Created

1. **`dicom_handler/xml_template_parser.py`**
   - XML parsing utility
   - Color conversion functions
   - Validation functions

2. **`dicom_handler/xml_template_views.py`**
   - Wizard views (upload, map, review, save, cancel)
   - AJAX search endpoint for structures

3. **`dicom_handler/forms.py`** (updated)
   - `XMLTemplateUploadForm`: File upload form
   - `StructureMappingForm`: Structure mapping form

4. **Templates**:
   - `templates/dicom_handler/xml_template_wizard_upload.html`
   - `templates/dicom_handler/xml_template_wizard_map.html`
   - `templates/dicom_handler/xml_template_wizard_review.html`
   - `templates/dicom_handler/xml_template_wizard_additional.html` (NEW)

5. **`dicom_handler/additional_structure_views.py`** (NEW)
   - CRUD views for AdditionalStructures
   - Add, edit, delete operations

6. **`test_xml_parser.py`**
   - Test script for XML parser functionality

### Updated Files

1. **`dicom_handler/urls.py`**
   - Added wizard URL patterns

2. **`templates/dicom_handler/template_detail.html`**
   - Added "Import XML Template" button

## Usage Examples

### Example 1: Head & Neck Template

```bash
# XML file: HN.xml
# Contains structures like: THYROID, SPINAL CORD, PAROTID_R, etc.
```

1. Upload `HN.xml` for your Head & Neck autosegmentation template
2. The wizard auto-matches structures like "PAROTID_R" → "Parotid_R"
3. Review and adjust ROI labels to meet TG263 standards
4. Save to populate structure properties

### Example 2: Prostate Template

```bash
# XML file: URO_Prostate_SBRT.xml
# Contains structures like: BODY, Rectum, Bladder, PTV, etc.
```

1. Upload `URO_Prostate_SBRT.xml` for your Prostate template
2. Map structures to corresponding autosegmentation structures
3. Colors are automatically converted to DICOM format
4. Save to import all properties at once

## Testing

Run the test script to verify XML parsing:

```bash
./venv/bin/python test_xml_parser.py
```

This tests:
- XML file parsing (HN.xml and URO_Prostate_SBRT.xml)
- Color format conversion
- ROI label validation
- DICOM color validation

## Validation Rules

### ROI Label (TG263 Standard)
- Maximum 16 characters
- Cannot be empty
- Automatically truncated if needed

### DICOM Color Format
- Must be in format: `R\G\B`
- Each value must be 0-255
- Example: `255\0\0` for red

### Duplicate Name Validation (NEW)

**Prevents duplicate ROI names within the same template:**

The system validates that ROI names are unique across:
1. **AdditionalStructures**: No duplicate additional structure names
2. **StructureProperties.roi_label**: No conflict with mapped structure labels
3. **AutosegmentationStructure.name**: No conflict with autosegmentation structure names

**Validation is:**
- **Case-insensitive**: "Liver", "liver", and "LIVER" are considered duplicates
- **Template-scoped**: Same name allowed in different templates
- **Applied during**:
  - XML import (Step 4: Additional Structures)
  - Manual add/edit via UI
  - All database saves

**Example Error Messages:**
- `"An additional structure with the name 'Bladder' already exists in this template."`
- `"A structure with the name 'Liver' already exists in this template (from mapped structures)."`
- `"A structure with the name 'Heart' already exists in this template (autosegmentation structure)."`

**Why This Matters:**
- Ensures DICOM RT Structure Sets have unique ROI names
- Prevents confusion during treatment planning
- Maintains data integrity across the system

## Permissions Required

- `dicom_handler.add_structureproperties`: Required to access the wizard

## API Endpoints

- `GET /dicom_handler/xml-template-wizard/start/`: Start wizard
- `POST /dicom_handler/xml-template-wizard/start/`: Upload XML file
- `GET /dicom_handler/xml-template-wizard/map/`: Display mapping form
- `POST /dicom_handler/xml-template-wizard/map/`: Submit mappings
- `GET /dicom_handler/xml-template-wizard/review/`: Review mappings
- `GET /dicom_handler/xml-template-wizard/additional/`: Select additional structures (NEW)
- `POST /dicom_handler/xml-template-wizard/additional/`: Save all structures (NEW)
- `GET /dicom_handler/xml-template-wizard/cancel/`: Cancel wizard
- `GET /dicom_handler/api/xml-template/search-structures/`: AJAX structure search

## Troubleshooting

### Issue: XML parsing fails
- **Solution**: Verify XML file is valid and follows supported format
- Check XML structure matches Varian Eclipse format

### Issue: Colors not displaying correctly
- **Solution**: Ensure colors are in supported format
- Use named colors or `RGB R G B` format

### Issue: ROI label validation error
- **Solution**: Ensure labels are 16 characters or less
- Edit labels in the mapping step

### Issue: No auto-matches found
- **Solution**: Structure names in XML don't match autosegmentation structure names
- Manually map each structure in Step 2

### Issue: Duplicate name validation error during import
- **Error**: `"A structure with the name 'X' already exists in this template"`
- **Solution**: 
  - Check if the structure name conflicts with existing mapped structures
  - Check if it conflicts with autosegmentation structure names
  - Rename the structure in the XML file before import, or
  - Deselect the conflicting structure in Step 4 (Additional Structures)
  - Note: Validation is case-insensitive ("Liver" = "liver")

## Notes

- The wizard stores data in session between steps (4 steps total)
- Canceling the wizard clears all session data
- Existing structure properties are updated, not duplicated
- Session data is automatically cleared after successful save
- **Duplicate name validation** is enforced at model level and during import
- Additional structures can be managed from the template detail page after import
- Color picker with presets available for manual add/edit operations

## Future Enhancements

Potential improvements:
- Support for additional XML formats (RayStation, Pinnacle, etc.)
- Bulk edit capabilities in mapping step
- Import history and rollback functionality
- Template-to-template copying
- CSV export/import as alternative to XML
