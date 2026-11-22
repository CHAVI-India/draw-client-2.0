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

from .structure_generation import execute_operation

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
        Execute a single operation by routing through the shared dispatcher.

        The pipeline-builder JSON uses ``{type, structures, parameters}``.
        ``structures`` are the explicitly-named structures for this operation;
        operations that continue the running chain (refinement, crop) use the
        previous result as their source instead.
        """
        # Load the named structures referenced by this operation.
        input_masks = []
        for struct_name in structures:
            mask = self.load_structure(struct_name)
            if mask is None:
                logger.error(f"Required structure '{struct_name}' not found")
                return None
            input_masks.append(mask)

        try:
            roles = self._build_roles(op_type, input_masks)
            result = execute_operation(op_type, roles, parameters or {})
            return result
        except Exception as e:
            logger.error(f"Operation '{op_type}' failed: {e}")
            return None

    def _build_roles(self, op_type: str, input_masks: List[sitk.Image]) -> Dict[str, Any]:
        """Map a pipeline-builder operation to its dispatcher roles.

        ``input_masks`` are the operation's explicitly-selected structures (in
        the order given by the JSON). The running result (``self.current_result``)
        is used as the source for refinement/crop operations.
        """
        cur = self.current_result

        def first():
            if not input_masks:
                raise ValueError(f"Operation '{op_type}' requires a source structure")
            return input_masks[0]

        def second():
            if len(input_masks) < 2:
                raise ValueError(f"Operation '{op_type}' requires a second structure")
            return input_masks[1]

        if op_type in ("margin", "expand", "contract", "ring"):
            return {"source": first()}
        if op_type in ("union", "intersection", "subtract", "xor"):
            return {"primary": first(), "others": input_masks[1:]}
        if op_type == "crop_to_boundary":
            return {"source": cur, "boundaries": input_masks}
        if op_type == "overlap":
            return {"source": first(), "others": input_masks[1:]}
        if op_type == "expand_subtract":
            return {"source": first(), "subtract": second()}
        if op_type == "avoid_margin":
            return {"source": first(), "avoid": second()}
        if op_type in (
            "smooth", "gaussian_smooth", "fill_holes", "remove_small_components",
            "keep_largest", "keep_n_largest", "close_gaps", "remove_protrusions",
        ):
            return {"source": cur}
        if op_type == "intensity_range":
            return {
                "seed": input_masks[0] if input_masks else None,
                "boundary": input_masks[1] if len(input_masks) > 1 else None,
            }
        raise ValueError(f"Unsupported operation type: {op_type}")

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
