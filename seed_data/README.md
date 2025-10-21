# Seed Data

This directory contains seed data fixtures that are automatically loaded when the application is initialized.

## Autosegmentation Templates

**File:** `autosegmentation_templates.json`

This fixture contains example autosegmentation templates including:
- Example Breast Template
- Example Head Neck Template
- Example Prostate Template
- Example Lung Template
- Example Rectum Template
- Example CNS Template
- Example Gyn Template

Each template includes associated models and structures from the DRAW API.

### Automatic Loading

The templates are automatically loaded via Django migration `0031_load_autosegmentation_templates.py` when you run:

```bash
python manage.py migrate
```

**Note:** The migration will only load the templates if the database is empty (no existing templates). This prevents duplicate data on subsequent migrations.

### Manual Loading

If you need to manually load or reload the fixtures:

```bash
# Load the fixtures
python manage.py loaddata seed_data/autosegmentation_templates.json

# Or use the full path
python manage.py loaddata autosegmentation_templates
```

### Updating Seed Data

If you need to update the seed data with new templates from your database:

```bash
# Export current templates to fixture file
python manage.py dumpdata dicom_handler.AutosegmentationTemplate dicom_handler.AutosegmentationModel dicom_handler.AutosegmentationStructure --indent 2 --output seed_data/autosegmentation_templates.json
```

## Other Seed Data

### Contour Modification Types

**File:** `contour_modification_types_list.csv`

This CSV file contains predefined contour modification types that are loaded via migration `0027_contour_modification_type_migration.py`.

### DICOM Dictionary

**File:** `dicom_dictionary.csv`

This CSV file contains DICOM tag definitions according to DICOM standards.

## Migration Behavior

- **First-time setup:** All seed data is loaded automatically when running migrations on a fresh database
- **Existing database:** The autosegmentation templates migration checks if templates already exist and skips loading to avoid duplicates
- **Rollback:** Running `python manage.py migrate dicom_handler 0030` will remove all loaded templates

## Notes

- The autosegmentation templates use UUIDs as primary keys, which are preserved from the fixture file
- Templates maintain relationships with their models and structures through foreign keys
- The seed data represents example templates for common cancer treatment sites
