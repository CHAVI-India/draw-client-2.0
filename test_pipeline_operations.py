#!/usr/bin/env python3
"""
Test script for ROI generation pipeline operations.

This script loads a CT series and RT Structure Set, applies pipeline operations
defined in JSON format, generates new structures, and saves them to a new RT Structure Set.

Usage:
    python test_pipeline_operations.py --ct-dir /path/to/ct/series \\
                                        --rtstruct /path/to/rtstruct.dcm \\
                                        --pipeline pipeline.json \\
                                        --output output_rtstruct.dcm

Example pipeline.json:
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
      "type": "union",
      "structures": ["CTV", "GTV"]
    },
    {
      "type": "smooth",
      "parameters": {
        "smoothing_mm": 2.0
      }
    }
  ]
}
"""

import os
import sys
import json
import argparse
import logging
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Django setup
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'draw_client.settings')
import django
django.setup()

from dicom_handler.utils.structure_generation import (
    load_ct_series_as_sitk_image,
    get_ct_geometry_info,
    rtstruct_roi_to_sitk_mask,
    add_sitk_mask_to_rtstruct,
    apply_uniform_margin,
    apply_anisotropic_margin,
    boolean_union,
    boolean_intersection,
    boolean_subtraction,
    crop_to_boundary,
    smooth_structure,
    fill_holes,
    remove_small_components,
    keep_largest_component,
    OperationPipeline,
    load_multiple_rois_as_masks,
    get_roi_names_from_rtstruct
)

import SimpleITK as sitk
import pydicom
from rt_utils import RTStructBuilder
import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class PipelineExecutor:
    """Execute pipeline operations on RT structures."""
    
    def __init__(self, ct_dir, rtstruct_path):
        """
        Initialize executor with CT series and RT Structure Set.
        
        Args:
            ct_dir: Path to directory containing CT DICOM files
            rtstruct_path: Path to RT Structure Set DICOM file
        """
        logger.info(f"Loading CT series from: {ct_dir}")
        self.ct_dir = ct_dir
        self.rtstruct_path = rtstruct_path
        
        # Load CT as SimpleITK image using SimpleITK's reader
        self.ct_image = self._load_ct_with_sitk(ct_dir)
        self.geometry = get_ct_geometry_info(self.ct_image)
        
        logger.info(f"Loading RT Structure Set from: {rtstruct_path}")
        self.rtstruct = RTStructBuilder.create_from(
            dicom_series_path=ct_dir,
            rt_struct_path=rtstruct_path
        )
        
        # Store original structures
        self.original_structures = {}
        self.load_original_structures()
        
        # Store for intermediate results
        self.current_result = None
    
    def _load_ct_with_sitk(self, ct_dir):
        """Load CT DICOM series using SimpleITK's ImageSeriesReader."""
        reader = sitk.ImageSeriesReader()
        
        # Get DICOM series file names
        series_ids = reader.GetGDCMSeriesIDs(ct_dir)
        
        if not series_ids:
            raise ValueError(f"No DICOM series found in directory: {ct_dir}")
        
        # Use the first series (or you could let user choose if multiple)
        series_id = series_ids[0]
        if len(series_ids) > 1:
            logger.warning(f"Found {len(series_ids)} series, using first one: {series_id}")
        
        dicom_names = reader.GetGDCMSeriesFileNames(ct_dir, series_id)
        logger.info(f"Loading {len(dicom_names)} DICOM slices")
        
        reader.SetFileNames(dicom_names)
        reader.MetaDataDictionaryArrayUpdateOn()
        reader.LoadPrivateTagsOn()
        
        image = reader.Execute()
        logger.info(f"Loaded CT image: {image.GetSize()}, spacing: {image.GetSpacing()}")
        
        return image
        
    def load_original_structures(self):
        """Load all structures from the RT Structure Set as masks."""
        roi_names = self.rtstruct.get_roi_names()
        logger.info(f"Found {len(roi_names)} structures: {roi_names}")
        
        for roi_name in roi_names:
            try:
                # Get mask from rt-utils (returns numpy array in [x, y, z] order)
                mask_array = self.rtstruct.get_roi_mask_by_name(roi_name)
                
                # rt-utils returns mask in [x, y, z] order, but SimpleITK expects [z, y, x]
                # Transpose to match SimpleITK convention
                mask_array = np.transpose(mask_array, (2, 1, 0))
                
                # Convert to SimpleITK image
                mask = sitk.GetImageFromArray(mask_array.astype(np.uint8))
                
                # Copy geometry from CT image
                mask.SetSpacing(self.ct_image.GetSpacing())
                mask.SetOrigin(self.ct_image.GetOrigin())
                mask.SetDirection(self.ct_image.GetDirection())
                
                self.original_structures[roi_name] = mask
                logger.info(f"✓ Loaded structure: {roi_name} (shape: {mask.GetSize()})")
            except Exception as e:
                logger.warning(f"✗ Failed to load structure '{roi_name}': {e}")
    
    def execute_pipeline(self, pipeline_json):
        """
        Execute pipeline operations.
        
        Args:
            pipeline_json: Dict containing pipeline definition
            
        Returns:
            SimpleITK image of the final result
        """
        if 'operations' not in pipeline_json:
            raise ValueError("Pipeline JSON must contain 'operations' array")
        
        operations = pipeline_json['operations']
        logger.info(f"Executing pipeline with {len(operations)} operations")
        
        for idx, operation in enumerate(operations, 1):
            op_type = operation['type']
            structures = operation.get('structures', [])
            parameters = operation.get('parameters', {})
            
            logger.info(f"Operation {idx}/{len(operations)}: {op_type}")
            logger.info(f"  Structures: {structures}")
            logger.info(f"  Parameters: {parameters}")
            
            self.current_result = self.execute_operation(
                op_type, structures, parameters
            )
        
        return self.current_result
    
    def execute_operation(self, op_type, structures, parameters):
        """
        Execute a single operation.
        
        Args:
            op_type: Operation type (expand, union, etc.)
            structures: List of structure names to operate on
            parameters: Operation parameters
            
        Returns:
            SimpleITK image result
        """
        # Get input masks
        input_masks = []
        for struct_name in structures:
            if struct_name not in self.original_structures:
                raise ValueError(f"Structure '{struct_name}' not found in RT Structure Set")
            input_masks.append(self.original_structures[struct_name])
        
        # Execute operation based on type
        if op_type == 'expand':
            if len(input_masks) != 1:
                raise ValueError("Expand operation requires exactly 1 structure")
            margin_mm = parameters.get('margin_mm', 5.0)
            kernel_type = parameters.get('kernel_type', 'ball')
            result = apply_uniform_margin(
                input_masks[0], 
                margin_mm=margin_mm,
                kernel_type=kernel_type
            )
            
        elif op_type == 'contract':
            if len(input_masks) != 1:
                raise ValueError("Contract operation requires exactly 1 structure")
            margin_mm = parameters.get('margin_mm', 3.0)
            kernel_type = parameters.get('kernel_type', 'ball')
            result = apply_uniform_margin(
                input_masks[0], 
                margin_mm=-margin_mm,  # Negative for contraction
                kernel_type=kernel_type
            )
            
        elif op_type == 'union':
            if len(input_masks) < 2:
                raise ValueError("Union operation requires at least 2 structures")
            result = boolean_union(input_masks)
            
        elif op_type == 'intersection':
            if len(input_masks) < 2:
                raise ValueError("Intersection operation requires at least 2 structures")
            result = boolean_intersection(input_masks)
            
        elif op_type == 'subtract':
            if len(input_masks) < 2:
                raise ValueError("Subtract operation requires at least 2 structures")
            # Subtract all others from the first
            result = input_masks[0]
            for mask in input_masks[1:]:
                result = boolean_subtraction(result, mask)
            
            # Apply additional margin if specified
            margin_mm = parameters.get('margin_mm', 0)
            if margin_mm > 0:
                result = apply_uniform_margin(result, margin_mm=margin_mm)
                
        elif op_type == 'crop_to_boundary':
            if len(input_masks) != 1:
                raise ValueError("Crop operation requires exactly 1 boundary structure")
            if self.current_result is None:
                raise ValueError("Crop operation requires a previous result")
            result = crop_to_boundary(self.current_result, input_masks[0])
            
        elif op_type == 'smooth':
            if self.current_result is None:
                raise ValueError("Smooth operation requires a previous result")
            smoothing_mm = parameters.get('smoothing_mm', 2.0)
            iterations = parameters.get('iterations', 1)
            result = smooth_structure(
                self.current_result,
                smoothing_mm=smoothing_mm,
                iterations=iterations
            )
            
        elif op_type == 'fill_holes':
            if self.current_result is None:
                raise ValueError("Fill holes operation requires a previous result")
            result = fill_holes(self.current_result)
            
        elif op_type == 'remove_small_components':
            if self.current_result is None:
                raise ValueError("Remove small components operation requires a previous result")
            min_size_mm3 = parameters.get('min_size_mm3', 100.0)
            result = remove_small_components(self.current_result, min_size_mm3=min_size_mm3)
            
        elif op_type == 'keep_largest':
            if self.current_result is None:
                raise ValueError("Keep largest operation requires a previous result")
            result = keep_largest_component(self.current_result)
            
        else:
            raise ValueError(f"Unknown operation type: {op_type}")
        
        return result
    
    def save_result(self, output_path, new_structure_name="Generated_Structure", 
                    color=[255, 0, 0]):
        """
        Save the result as a new RT Structure Set.
        
        Args:
            output_path: Path to save the new RT Structure Set
            new_structure_name: Name for the generated structure
            color: RGB color for the new structure
        """
        if self.current_result is None:
            raise ValueError("No result to save. Execute pipeline first.")
        
        logger.info(f"Saving result to: {output_path}")
        
        # Convert SimpleITK mask to numpy array (in [z, y, x] order)
        mask_array = sitk.GetArrayFromImage(self.current_result)
        
        # rt-utils expects mask in [x, y, z] order, so transpose back
        mask_array = np.transpose(mask_array, (2, 1, 0))
        
        # Convert to boolean type (rt-utils requirement)
        mask_array = mask_array.astype(bool)
        
        logger.info(f"Generated structure shape: {mask_array.shape}, dtype: {mask_array.dtype}")
        
        # Add the new structure to RT Struct
        self.rtstruct.add_roi(
            mask=mask_array,
            name=new_structure_name,
            color=color
        )
        
        # Save
        self.rtstruct.save(output_path)
        logger.info(f"✓ Successfully saved RT Structure Set with new structure: {new_structure_name}")


def main():
    parser = argparse.ArgumentParser(
        description='Test ROI generation pipeline operations',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument(
        '--ct-dir',
        required=True,
        help='Path to directory containing CT DICOM series'
    )
    
    parser.add_argument(
        '--rtstruct',
        required=True,
        help='Path to RT Structure Set DICOM file'
    )
    
    parser.add_argument(
        '--pipeline',
        required=True,
        help='Path to JSON file containing pipeline definition'
    )
    
    parser.add_argument(
        '--output',
        required=True,
        help='Path to save output RT Structure Set'
    )
    
    parser.add_argument(
        '--structure-name',
        default='Generated_Structure',
        help='Name for the generated structure (default: Generated_Structure)'
    )
    
    parser.add_argument(
        '--color',
        default='255,0,0',
        help='RGB color for generated structure (default: 255,0,0 - red)'
    )
    
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Parse color
    try:
        color = [int(c) for c in args.color.split(',')]
        if len(color) != 3 or any(c < 0 or c > 255 for c in color):
            raise ValueError()
    except:
        logger.error("Invalid color format. Use R,G,B format (e.g., 255,0,0)")
        return 1
    
    # Load pipeline
    try:
        with open(args.pipeline, 'r') as f:
            pipeline_json = json.load(f)
        logger.info(f"Loaded pipeline from: {args.pipeline}")
    except Exception as e:
        logger.error(f"Failed to load pipeline JSON: {e}")
        return 1
    
    # Execute pipeline
    try:
        executor = PipelineExecutor(args.ct_dir, args.rtstruct)
        executor.execute_pipeline(pipeline_json)
        executor.save_result(args.output, args.structure_name, color)
        
        logger.info("Pipeline execution completed successfully!")
        return 0
        
    except Exception as e:
        logger.error(f"Pipeline execution failed: {e}", exc_info=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
