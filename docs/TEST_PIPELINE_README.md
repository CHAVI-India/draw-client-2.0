# ROI Generation Pipeline Testing

This directory contains tools to test the ROI generation pipeline operations with real CT and RT Structure Set data.

## Quick Start

### 1. Prepare Your Data

You need:
- **CT Series**: A directory containing CT DICOM files
- **RT Structure Set**: A DICOM RT Structure Set file with existing structures

### 2. Create a Pipeline JSON

Define the operations you want to test in a JSON file. See `example_pipelines/` for examples.

**Basic Structure:**
```json
{
  "operations": [
    {
      "type": "expand",
      "structures": ["CTV"],
      "parameters": {
        "margin_mm": 5.0,
        "kernel_type": "ball"
      }
    }
  ]
}
```

### 3. Run the Test Script

```bash
# Activate virtual environment
source venv/bin/activate

# Run the test
python test_pipeline_operations.py \
    --ct-dir /path/to/ct/series \
    --rtstruct /path/to/original_rtstruct.dcm \
    --pipeline example_pipeline.json \
    --output output_rtstruct.dcm \
    --structure-name "PTV_Generated" \
    --color "255,0,0"
```

### 4. Visualize the Result

The output RT Structure Set will contain:
- **All original structures** (unchanged)
- **New generated structure** with the name you specified

You can open it in any DICOM viewer (3D Slicer, MIM, Eclipse, etc.) to verify the operations worked correctly.

## Available Operations

### Operations Requiring Structure Selection

#### **expand**
Expand a structure by a specified margin.
```json
{
  "type": "expand",
  "structures": ["CTV"],
  "parameters": {
    "margin_mm": 5.0,
    "kernel_type": "ball"  // Options: ball, box, cross
  }
}
```

#### **contract**
Contract (shrink) a structure by a specified margin.
```json
{
  "type": "contract",
  "structures": ["GTV"],
  "parameters": {
    "margin_mm": 3.0,
    "kernel_type": "ball"
  }
}
```

#### **union**
Combine multiple structures into one.
```json
{
  "type": "union",
  "structures": ["Parotid_L", "Parotid_R", "Submandibular_L"]
}
```

#### **intersection**
Keep only the overlapping region of multiple structures.
```json
{
  "type": "intersection",
  "structures": ["PTV_High", "PTV_Low"]
}
```

#### **subtract**
Remove structures from the first structure.
```json
{
  "type": "subtract",
  "structures": ["PTV", "Brainstem", "SpinalCord"],
  "parameters": {
    "margin_mm": 2.0  // Optional: expand structures before subtracting
  }
}
```

#### **crop_to_boundary**
Limit the current result to a boundary structure.
```json
{
  "type": "crop_to_boundary",
  "structures": ["Body"]
}
```

### Operations Applied to Current Result

These operations work on the result of previous operations and don't require structure selection.

#### **smooth**
Smooth the surface of the structure.
```json
{
  "type": "smooth",
  "parameters": {
    "smoothing_mm": 2.0,
    "iterations": 1
  }
}
```

#### **fill_holes**
Fill internal cavities in the structure.
```json
{
  "type": "fill_holes"
}
```

#### **remove_small_components**
Remove small disconnected pieces.
```json
{
  "type": "remove_small_components",
  "parameters": {
    "min_size_mm3": 100.0
  }
}
```

#### **keep_largest**
Keep only the largest connected component.
```json
{
  "type": "keep_largest"
}
```

## Example Pipelines

### Example 1: Create PTV from CTV
```json
{
  "operations": [
    {
      "type": "expand",
      "structures": ["CTV"],
      "parameters": {
        "margin_mm": 5.0,
        "kernel_type": "ball"
      }
    },
    {
      "type": "smooth",
      "parameters": {
        "smoothing_mm": 2.0
      }
    }
  ]
}
```

### Example 2: Combine Bilateral Organs
```json
{
  "operations": [
    {
      "type": "union",
      "structures": ["Parotid_L", "Parotid_R"]
    },
    {
      "type": "smooth",
      "parameters": {
        "smoothing_mm": 2.0
      }
    }
  ]
}
```

### Example 3: Complex Avoidance Structure
```json
{
  "operations": [
    {
      "type": "expand",
      "structures": ["Lung_L"],
      "parameters": {
        "margin_mm": 3.0,
        "kernel_type": "ball"
      }
    },
    {
      "type": "expand",
      "structures": ["Lung_R"],
      "parameters": {
        "margin_mm": 3.0,
        "kernel_type": "ball"
      }
    },
    {
      "type": "union",
      "structures": ["Lung_L", "Lung_R", "Heart"]
    },
    {
      "type": "smooth",
      "parameters": {
        "smoothing_mm": 2.5,
        "iterations": 2
      }
    },
    {
      "type": "fill_holes"
    }
  ]
}
```

## Command Line Options

```
--ct-dir PATH           Path to CT DICOM series directory (required)
--rtstruct PATH         Path to RT Structure Set file (required)
--pipeline PATH         Path to pipeline JSON file (required)
--output PATH           Path to save output RT Structure Set (required)
--structure-name NAME   Name for generated structure (default: Generated_Structure)
--color R,G,B          RGB color for structure (default: 255,0,0)
--verbose              Enable verbose logging
```

## Troubleshooting

### Structure Not Found
```
ValueError: Structure 'CTV' not found in RT Structure Set
```
**Solution**: Check the exact structure names in your RT Structure Set. Names are case-sensitive.

### Operation Requires Previous Result
```
ValueError: Smooth operation requires a previous result
```
**Solution**: Operations like `smooth`, `fill_holes`, etc. must come after operations that select structures (like `expand`, `union`, etc.)

### Invalid JSON
```
Failed to load pipeline JSON: ...
```
**Solution**: Validate your JSON syntax. Use a JSON validator or check for missing commas, brackets, etc.

## Tips for Testing

1. **Start Simple**: Test with a single `expand` operation first
2. **Check Structure Names**: List structures in your RT Struct before creating the pipeline
3. **Visualize Each Step**: Create separate pipelines for each operation to see intermediate results
4. **Use Verbose Mode**: Add `--verbose` flag to see detailed execution logs
5. **Compare Results**: Open original and generated RT Struct side-by-side in a viewer

## Integration with Frontend

Once you've verified operations work correctly with the test script, the same JSON format is used in the web interface:

1. Navigate to template detail page
2. Click "Add Structure"
3. Use the visual pipeline builder
4. The generated JSON matches the format used in these test scripts

This ensures what you test here will work exactly the same in production!
