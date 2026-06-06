# Structure Generation Module

This module provides tools for generating derived structures from existing RTStruct ROIs using SimpleITK.

## Overview

The module enables:
- Loading CT series and RTStruct data
- Converting contours to 3D binary masks
- Performing operations (margins, boolean operations, smoothing)
- Chaining operations in pipelines
- Converting results back to RTStruct contours

All operations work in **physical space (millimeters)**, not voxel space, ensuring consistent results regardless of image resolution.

## Quick Start

### Basic Example: Create PTV from CTV

```python
from dicom_handler.utils.structure_generation import (
    load_ct_series_as_sitk_image,
    rtstruct_roi_to_sitk_mask,
    apply_uniform_margin,
    add_sitk_mask_to_rtstruct
)
from rt_utils import RTStructBuilder

# 1. Load CT series
ct_image = load_ct_series_as_sitk_image(series_data)

# 2. Extract CTV from RTStruct
ctv_mask = rtstruct_roi_to_sitk_mask(
    rtstruct_path="/path/to/rtstruct.dcm",
    ct_image=ct_image,
    roi_name="CTV",
    dicom_series_path="/path/to/ct/series"
)

# 3. Expand by 5mm to create PTV
ptv_mask = apply_uniform_margin(ctv_mask, margin_mm=5.0)

# 4. Add back to RTStruct
rtstruct = RTStructBuilder.create_from(
    dicom_series_path="/path/to/ct/series",
    rt_struct_path="/path/to/rtstruct.dcm"
)
add_sitk_mask_to_rtstruct(rtstruct, ptv_mask, "PTV", [255, 0, 0])
rtstruct.save("/path/to/output.dcm")
```

## Available Operations

### Margin Operations

```python
from dicom_handler.utils.structure_generation import (
    apply_uniform_margin,
    apply_anisotropic_margin
)

# Uniform expansion
expanded = apply_uniform_margin(mask, margin_mm=5.0)

# Uniform contraction
contracted = apply_uniform_margin(mask, margin_mm=-3.0)

# Anisotropic margin (different in each direction)
anisotropic = apply_anisotropic_margin(
    mask,
    margin_x_mm=5.0,  # Left-right
    margin_y_mm=3.0,  # Anterior-posterior
    margin_z_mm=2.0   # Superior-inferior
)
```

### Boolean Operations

```python
from dicom_handler.utils.structure_generation import (
    boolean_union,
    boolean_intersection,
    boolean_subtraction,
    crop_to_boundary
)

# Combine structures
combined = boolean_union(left_parotid, right_parotid)

# Find overlap
overlap = boolean_intersection(ptv_mask, oar_mask)

# Remove one structure from another
ptv_safe = boolean_subtraction(ptv_mask, spinal_cord)

# Crop to boundary (e.g., keep PTV within body)
ptv_cropped = crop_to_boundary(ptv_mask, body_mask)
```

### Advanced Operations

```python
from dicom_handler.utils.structure_generation import (
    smooth_structure,
    fill_holes,
    remove_small_components,
    keep_largest_component
)

# Smooth jagged contours
smoothed = smooth_structure(mask, smoothing_mm=2.0, iterations=2)

# Fill internal holes
solid = fill_holes(mask)

# Remove small disconnected pieces
cleaned = remove_small_components(mask, min_size_mm3=100.0)

# Keep only main structure
main = keep_largest_component(mask)
```

## Using Pipelines

For complex multi-step operations, use the pipeline system:

### Example 1: PTV with Safety Margin

```python
from dicom_handler.utils.structure_generation import OperationPipeline

# Create pipeline
pipeline = OperationPipeline()
pipeline.add_operation("expand", {"margin_mm": 5.0})
pipeline.add_operation("crop_to_boundary", {"boundary_roi": "Body"})
pipeline.add_operation("subtract", {"other_roi": "SpinalCord", "margin_mm": 3.0})
pipeline.add_operation("smooth", {"smoothing_mm": 2.0})

# Execute pipeline
context = {
    "Body": body_mask,
    "SpinalCord": cord_mask
}
ptv_mask = pipeline.execute(ctv_mask, context=context)
```

### Example 2: JSON Pipeline Definition

```python
import json
from dicom_handler.utils.structure_generation import OperationPipeline

# Define pipeline in JSON (can be stored in database)
pipeline_json = '''
{
    "operations": [
        {
            "type": "expand",
            "parameters": {"margin_mm": 5.0}
        },
        {
            "type": "crop_to_boundary",
            "parameters": {"boundary_roi": "Body"}
        },
        {
            "type": "smooth",
            "parameters": {"smoothing_mm": 2.0}
        }
    ]
}
'''

# Load and execute
pipeline = OperationPipeline.from_json(pipeline_json)
result = pipeline.execute(input_mask, context={"Body": body_mask})
```

## Integration with task2_reidentify_rtstruct.py

Here's how to integrate structure generation into the existing RTStruct workflow:

```python
def _generate_additional_structures(
    ds: pydicom.Dataset,
    series_data: Dict[str, Any],
    rtstruct_path: str
) -> None:
    """
    Generate additional structures from existing autosegmented structures.
    """
    from dicom_handler.utils.structure_generation import (
        load_ct_series_as_sitk_image,
        rtstruct_roi_to_sitk_mask,
        OperationPipeline
    )
    from rt_utils import RTStructBuilder
    
    # Load CT series
    ct_image = load_ct_series_as_sitk_image(series_data)
    
    # Get series path
    series = series_data['series']
    series_path = series.series_root_path
    
    # Load RTStruct
    rtstruct = RTStructBuilder.create_from(
        dicom_series_path=series_path,
        rt_struct_path=rtstruct_path
    )
    
    # Get matched templates
    matched_templates = series.matched_templates.all()
    
    for template in matched_templates:
        # Get additional structures for this template
        additional_structures = AdditionalStructures.objects.filter(
            autosegmentation_template=template
        )
        
        for add_struct in additional_structures:
            if not add_struct.roi_generation_logic:
                continue
            
            try:
                # Parse generation logic (JSON format)
                pipeline = OperationPipeline.from_json(add_struct.roi_generation_logic)
                
                # Load source ROI (if specified in pipeline)
                # For now, assume source is in context
                context = {}
                # TODO: Load required source ROIs into context
                
                # Execute pipeline
                result_mask = pipeline.execute(input_mask, context=context)
                
                # Add to RTStruct
                color = [255, 0, 0]  # Parse from add_struct.roi_display_color
                add_sitk_mask_to_rtstruct(
                    rtstruct,
                    result_mask,
                    add_struct.roi_label,
                    color,
                    add_struct.rt_roi_interpreted_type or "ORGAN"
                )
                
                logger.info(f"Generated structure: {add_struct.roi_label}")
                
            except Exception as e:
                logger.error(f"Failed to generate {add_struct.roi_label}: {str(e)}")
                continue
    
    # Save updated RTStruct
    rtstruct.save(rtstruct_path)
```

## Pipeline JSON Format for Database Storage

Store in `AdditionalStructures.roi_generation_logic` field:

```json
{
    "source_roi": "CTV",
    "operations": [
        {
            "type": "expand",
            "parameters": {"margin_mm": 5.0}
        },
        {
            "type": "crop_to_boundary",
            "parameters": {"boundary_roi": "Body"}
        },
        {
            "type": "subtract",
            "parameters": {
                "other_roi": "SpinalCord",
                "margin_mm": 3.0
            }
        },
        {
            "type": "smooth",
            "parameters": {"smoothing_mm": 2.0}
        }
    ]
}
```

## Common Use Cases

### 1. Planning Target Volume (PTV) from Clinical Target Volume (CTV)

```python
# PTV = CTV + 5mm margin, cropped to body
pipeline = OperationPipeline()
pipeline.add_operation("expand", {"margin_mm": 5.0})
pipeline.add_operation("crop_to_boundary", {"boundary_roi": "Body"})
ptv = pipeline.execute(ctv_mask, context={"Body": body_mask})
```

### 2. Organ at Risk (OAR) with Safety Margin

```python
# SpinalCord_PRV = SpinalCord + 3mm margin
prv_mask = apply_uniform_margin(cord_mask, margin_mm=3.0)
```

### 3. Combined Parotid Glands

```python
# Parotids = Left_Parotid + Right_Parotid
parotids = boolean_union(left_parotid, right_parotid)
```

### 4. PTV Avoiding Critical Structure

```python
# PTV_Safe = PTV - (SpinalCord + 5mm)
pipeline = OperationPipeline()
pipeline.add_operation("subtract", {
    "other_roi": "SpinalCord",
    "margin_mm": 5.0
})
ptv_safe = pipeline.execute(ptv_mask, context={"SpinalCord": cord_mask})
```

### 5. Body Contour Minus Internal Structures

```python
# External = Body - (Lungs + Heart)
pipeline = OperationPipeline()
pipeline.add_operation("subtract", {"other_roi": "Lungs"})
pipeline.add_operation("subtract", {"other_roi": "Heart"})
external = pipeline.execute(body_mask, context={"Lungs": lungs, "Heart": heart})
```

## Error Handling

All functions include proper error handling and logging:

```python
import logging

logger = logging.getLogger(__name__)

try:
    result = apply_uniform_margin(mask, margin_mm=5.0)
except Exception as e:
    logger.error(f"Margin operation failed: {str(e)}")
    # Handle error appropriately
```

## Performance Considerations

- **Memory**: Operations work on 3D volumes in memory. For large CT series, ensure sufficient RAM.
- **Speed**: SimpleITK operations are optimized and fast. Most operations complete in < 1 second.
- **Caching**: Consider caching loaded CT images and frequently used masks.

## Testing

Test with known structures:

```python
# Verify expansion
original_volume = calculate_structure_volume(mask)
expanded = apply_uniform_margin(mask, margin_mm=5.0)
expanded_volume = calculate_structure_volume(expanded)
assert expanded_volume > original_volume

# Verify boolean operations
union = boolean_union(mask1, mask2)
union_volume = calculate_structure_volume(union)
assert union_volume >= max(
    calculate_structure_volume(mask1),
    calculate_structure_volume(mask2)
)
```

## Future Enhancements

Potential additions:
- Directional margins based on anatomical orientation
- Dose-based structure generation (isodose contours)
- Machine learning-based refinement
- Parallel processing for multiple structures
- Undo/redo for interactive editing
