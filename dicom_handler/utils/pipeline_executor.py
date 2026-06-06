"""
Pipeline executor for generating ROI structures in production.

This module executes roi_generation_logic pipelines during RT Struct processing,
applying operations to existing structures and generating new contours.
"""

import logging
import numpy as np
import SimpleITK as sitk
from typing import Dict, List, Any, Optional
from rt_utils import RTStructBuilder

from .structure_generation import (
    apply_uniform_margin,
    boolean_union,
    boolean_intersection,
    boolean_subtraction,
    crop_to_boundary,
    smooth_structure,
    fill_holes,
    remove_small_components,
    keep_largest_component,
)

logger = logging.getLogger(__name__)


class ProductionPipelineExecutor:
    """
    Execute ROI generation pipelines in production environment.
    
    This class handles loading structures from RT Struct, executing pipeline
    operations, and converting results back to contours.
    """
    
    def __init__(self, rtstruct: RTStructBuilder, ct_image: sitk.Image):
        """
        Initialize executor.
        
        Args:
            rtstruct: RTStructBuilder instance with existing structures
            ct_image: SimpleITK CT image for geometry reference
        """
        self.rtstruct = rtstruct
        self.ct_image = ct_image
        self.loaded_structures = {}
        self.current_result = None
        
    def load_structure(self, structure_name: str) -> Optional[sitk.Image]:
        """
        Load a structure from RT Struct as SimpleITK mask.
        
        Args:
            structure_name: Name of the structure to load
            
        Returns:
            SimpleITK image or None if structure not found
        """
        # Check cache first
        if structure_name in self.loaded_structures:
            return self.loaded_structures[structure_name]
        
        try:
            # Get mask from rt-utils (returns numpy array in [x, y, z] order)
            mask_array = self.rtstruct.get_roi_mask_by_name(structure_name)
            
            # rt-utils returns mask in [x, y, z] order, but SimpleITK expects [z, y, x]
            mask_array = np.transpose(mask_array, (2, 1, 0))
            
            # Convert to SimpleITK image
            mask = sitk.GetImageFromArray(mask_array.astype(np.uint8))
            
            # Copy geometry from CT image
            mask.SetSpacing(self.ct_image.GetSpacing())
            mask.SetOrigin(self.ct_image.GetOrigin())
            mask.SetDirection(self.ct_image.GetDirection())
            
            # Cache it
            self.loaded_structures[structure_name] = mask
            logger.debug(f"Loaded structure '{structure_name}' with shape {mask.GetSize()}")
            
            return mask
            
        except Exception as e:
            logger.warning(f"Failed to load structure '{structure_name}': {e}")
            return None
    
    def execute_pipeline(self, pipeline_json: Dict[str, Any]) -> Optional[sitk.Image]:
        """
        Execute a pipeline of operations.
        
        Args:
            pipeline_json: Dictionary containing 'operations' array
            
        Returns:
            SimpleITK image result or None if execution failed
        """
        if not pipeline_json or 'operations' not in pipeline_json:
            logger.warning("Invalid pipeline JSON: missing 'operations' key")
            return None
        
        operations = pipeline_json['operations']
        if not operations:
            logger.warning("Pipeline has no operations")
            return None
        
        logger.info(f"Executing pipeline with {len(operations)} operations")
        
        try:
            for idx, operation in enumerate(operations, 1):
                op_type = operation.get('type')
                structures = operation.get('structures', [])
                parameters = operation.get('parameters', {})
                
                logger.debug(f"Operation {idx}/{len(operations)}: {op_type}")
                
                self.current_result = self._execute_operation(
                    op_type, structures, parameters
                )
                
                if self.current_result is None:
                    logger.error(f"Operation {idx} ({op_type}) failed")
                    return None
            
            return self.current_result
            
        except Exception as e:
            logger.error(f"Pipeline execution failed: {e}", exc_info=True)
            return None
    
    def _execute_operation(self, op_type: str, structures: List[str], 
                          parameters: Dict[str, Any]) -> Optional[sitk.Image]:
        """
        Execute a single operation.
        
        Args:
            op_type: Operation type (expand, union, etc.)
            structures: List of structure names
            parameters: Operation parameters
            
        Returns:
            SimpleITK image result or None if failed
        """
        # Load input structures
        input_masks = []
        for struct_name in structures:
            mask = self.load_structure(struct_name)
            if mask is None:
                logger.error(f"Required structure '{struct_name}' not found")
                return None
            input_masks.append(mask)
        
        try:
            # Execute based on operation type
            if op_type == 'expand':
                if len(input_masks) != 1:
                    raise ValueError("Expand requires exactly 1 structure")
                margin_mm = parameters.get('margin_mm', 5.0)
                kernel_type = parameters.get('kernel_type', 'ball')
                result = apply_uniform_margin(
                    input_masks[0], 
                    margin_mm=margin_mm,
                    kernel_type=kernel_type
                )
                logger.debug(f"Applied {margin_mm}mm expansion")
                
            elif op_type == 'contract':
                if len(input_masks) != 1:
                    raise ValueError("Contract requires exactly 1 structure")
                margin_mm = parameters.get('margin_mm', 3.0)
                kernel_type = parameters.get('kernel_type', 'ball')
                result = apply_uniform_margin(
                    input_masks[0], 
                    margin_mm=-margin_mm,
                    kernel_type=kernel_type
                )
                logger.debug(f"Applied {margin_mm}mm contraction")
                
            elif op_type == 'union':
                if len(input_masks) < 2:
                    raise ValueError("Union requires at least 2 structures")
                result = boolean_union(input_masks)
                logger.debug(f"Combined {len(input_masks)} structures")
                
            elif op_type == 'intersection':
                if len(input_masks) < 2:
                    raise ValueError("Intersection requires at least 2 structures")
                result = boolean_intersection(input_masks)
                logger.debug(f"Intersected {len(input_masks)} structures")
                
            elif op_type == 'subtract':
                if len(input_masks) < 2:
                    raise ValueError("Subtract requires at least 2 structures")
                result = input_masks[0]
                for mask in input_masks[1:]:
                    result = boolean_subtraction(result, mask)
                margin_mm = parameters.get('margin_mm', 0)
                if margin_mm > 0:
                    result = apply_uniform_margin(result, margin_mm=margin_mm)
                logger.debug(f"Subtracted {len(input_masks)-1} structures")
                
            elif op_type == 'crop_to_boundary':
                if len(input_masks) != 1:
                    raise ValueError("Crop requires exactly 1 boundary structure")
                if self.current_result is None:
                    raise ValueError("Crop requires a previous result")
                result = crop_to_boundary(self.current_result, input_masks[0])
                logger.debug("Applied boundary crop")
                
            elif op_type == 'smooth':
                if self.current_result is None:
                    raise ValueError("Smooth requires a previous result")
                smoothing_mm = parameters.get('smoothing_mm', 2.0)
                iterations = parameters.get('iterations', 1)
                result = smooth_structure(
                    self.current_result,
                    smoothing_mm=smoothing_mm,
                    iterations=iterations
                )
                logger.debug(f"Applied smoothing ({smoothing_mm}mm)")
                
            elif op_type == 'fill_holes':
                if self.current_result is None:
                    raise ValueError("Fill holes requires a previous result")
                result = fill_holes(self.current_result)
                logger.debug("Filled holes")
                
            elif op_type == 'remove_small_components':
                if self.current_result is None:
                    raise ValueError("Remove small components requires a previous result")
                min_size_mm3 = parameters.get('min_size_mm3', 100.0)
                result = remove_small_components(self.current_result, min_size_mm3=min_size_mm3)
                logger.debug(f"Removed components < {min_size_mm3}mm³")
                
            elif op_type == 'keep_largest':
                if self.current_result is None:
                    raise ValueError("Keep largest requires a previous result")
                result = keep_largest_component(self.current_result)
                logger.debug("Kept largest component")
                
            else:
                logger.error(f"Unknown operation type: {op_type}")
                return None
            
            return result
            
        except Exception as e:
            logger.error(f"Operation '{op_type}' failed: {e}")
            return None
    
    def add_result_to_rtstruct(self, structure_name: str, color: List[int]) -> bool:
        """
        Add the pipeline result to the RT Struct.
        
        Args:
            structure_name: Name for the generated structure
            color: RGB color [R, G, B]
            
        Returns:
            True if successful, False otherwise
        """
        if self.current_result is None:
            logger.error("No result to add - pipeline not executed")
            return False
        
        try:
            # Convert SimpleITK mask to numpy array (in [z, y, x] order)
            mask_array = sitk.GetArrayFromImage(self.current_result)
            
            # rt-utils expects mask in [x, y, z] order, so transpose back
            mask_array = np.transpose(mask_array, (2, 1, 0))
            
            # Convert to boolean type (rt-utils requirement)
            mask_array = mask_array.astype(bool)
            
            logger.debug(f"Adding structure '{structure_name}' with shape {mask_array.shape}")
            
            # Add to RT Struct
            self.rtstruct.add_roi(
                mask=mask_array,
                name=structure_name,
                color=color
            )
            
            logger.info(f"Successfully added generated structure: {structure_name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to add structure '{structure_name}': {e}", exc_info=True)
            return False


def execute_additional_structure_pipeline(
    rtstruct: RTStructBuilder,
    ct_image: sitk.Image,
    structure_name: str,
    pipeline_json: Dict[str, Any],
    color: List[int]
) -> bool:
    """
    Convenience function to execute a pipeline and add result to RT Struct.
    
    Args:
        rtstruct: RTStructBuilder instance
        ct_image: SimpleITK CT image
        structure_name: Name for generated structure
        pipeline_json: Pipeline definition
        color: RGB color
        
    Returns:
        True if successful, False otherwise
    """
    executor = ProductionPipelineExecutor(rtstruct, ct_image)
    result = executor.execute_pipeline(pipeline_json)
    
    if result is None:
        return False
    
    return executor.add_result_to_rtstruct(structure_name, color)
