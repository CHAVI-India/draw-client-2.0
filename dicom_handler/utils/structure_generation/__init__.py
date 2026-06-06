"""
Structure generation utilities for creating derived ROIs from existing structures.

This module provides tools to:
- Load CT series and RTStruct data as SimpleITK images
- Convert between RTStruct contours and SimpleITK masks
- Perform structure operations (margins, boolean operations, smoothing)
- Chain operations together in pipelines
- Convert results back to RTStruct contours

Example usage:
    from dicom_handler.utils.structure_generation import (
        load_ct_series_as_sitk_image,
        rtstruct_roi_to_sitk_mask,
        apply_uniform_margin,
        boolean_intersection,
        add_sitk_mask_to_rtstruct,
        OperationPipeline
    )
    
    # Load CT and extract ROI
    ct_image = load_ct_series_as_sitk_image(series_data)
    ctv_mask = rtstruct_roi_to_sitk_mask(rtstruct_path, ct_image, "CTV", series_path)
    
    # Generate PTV with 5mm margin
    ptv_mask = apply_uniform_margin(ctv_mask, margin_mm=5.0)
    
    # Crop to body
    body_mask = rtstruct_roi_to_sitk_mask(rtstruct_path, ct_image, "Body", series_path)
    ptv_mask = boolean_intersection(ptv_mask, body_mask)
    
    # Add back to RTStruct
    rtstruct = RTStructBuilder.create_from(series_path, rtstruct_path)
    add_sitk_mask_to_rtstruct(rtstruct, ptv_mask, "PTV", [255, 0, 0])
    
    # Or use a pipeline:
    pipeline = OperationPipeline()
    pipeline.add_operation("expand", {"margin_mm": 5.0})
    pipeline.add_operation("crop_to_boundary", {"boundary_roi": "Body"})
    pipeline.add_operation("smooth", {"smoothing_mm": 2.0})
    result = pipeline.execute(ctv_mask, context={"Body": body_mask})
"""

# Geometry utilities
from .geometry import (
    load_ct_series_as_sitk_image,
    get_ct_geometry_info,
    validate_mask_geometry,
    calculate_voxel_volume,
    calculate_structure_volume,
    get_structure_bounding_box
)

# Converters
from .converters import (
    rtstruct_roi_to_sitk_mask,
    sitk_mask_to_numpy,
    numpy_to_sitk_mask,
    add_sitk_mask_to_rtstruct,
    load_multiple_rois_as_masks,
    create_empty_mask_like,
    resample_mask_to_reference,
    get_roi_names_from_rtstruct
)

# Core operations
from .operations import (
    apply_uniform_margin,
    apply_anisotropic_margin,
    boolean_union,
    boolean_intersection,
    boolean_subtraction,
    boolean_xor,
    crop_to_boundary,
    expand_and_crop,
    subtract_with_margin
)

# Advanced operations
from .advanced_operations import (
    smooth_structure,
    gaussian_smooth,
    fill_holes,
    remove_small_components,
    keep_largest_component,
    keep_n_largest_components,
    close_gaps,
    remove_protrusions,
    distance_map
)

# Pipeline
from .pipeline import (
    OperationDefinition,
    OperationPipeline,
    create_simple_pipeline,
    parse_operation_string
)

__all__ = [
    # Geometry
    'load_ct_series_as_sitk_image',
    'get_ct_geometry_info',
    'validate_mask_geometry',
    'calculate_voxel_volume',
    'calculate_structure_volume',
    'get_structure_bounding_box',
    
    # Converters
    'rtstruct_roi_to_sitk_mask',
    'sitk_mask_to_numpy',
    'numpy_to_sitk_mask',
    'add_sitk_mask_to_rtstruct',
    'load_multiple_rois_as_masks',
    'create_empty_mask_like',
    'resample_mask_to_reference',
    'get_roi_names_from_rtstruct',
    
    # Core operations
    'apply_uniform_margin',
    'apply_anisotropic_margin',
    'boolean_union',
    'boolean_intersection',
    'boolean_subtraction',
    'boolean_xor',
    'crop_to_boundary',
    'expand_and_crop',
    'subtract_with_margin',
    
    # Advanced operations
    'smooth_structure',
    'gaussian_smooth',
    'fill_holes',
    'remove_small_components',
    'keep_largest_component',
    'keep_n_largest_components',
    'close_gaps',
    'remove_protrusions',
    'distance_map',
    
    # Pipeline
    'OperationDefinition',
    'OperationPipeline',
    'create_simple_pipeline',
    'parse_operation_string',
]

__version__ = '1.0.0'
