"""
Pipeline execution engine for chaining multiple structure operations.

This module provides:
- Operation definition and registration
- Pipeline construction from JSON/dict definitions
- Sequential execution of operations with context management
- Human-readable operation string parsing
"""

import SimpleITK as sitk
import json
import logging
from typing import Dict, Any, List, Callable, Optional
from dataclasses import dataclass, field

from . import operations
from . import advanced_operations

logger = logging.getLogger(__name__)


@dataclass
class OperationDefinition:
    """
    Definition of a single operation in a pipeline.
    
    Attributes:
        operation_type: Type of operation (e.g., "expand", "union", "smooth")
        parameters: Dictionary of parameters for the operation
        source_roi: Name of source ROI (if operation uses existing ROI)
        output_name: Optional name for intermediate result
    """
    operation_type: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    source_roi: Optional[str] = None
    output_name: Optional[str] = None


class OperationPipeline:
    """
    Manages and executes a sequence of structure operations.
    
    The pipeline maintains a context of available masks (both source ROIs
    and intermediate results) and executes operations in sequence.
    
    Example:
        >>> pipeline = OperationPipeline()
        >>> pipeline.add_operation("expand", {"margin_mm": 5.0})
        >>> pipeline.add_operation("crop_to_boundary", {"boundary_roi": "Body"})
        >>> pipeline.add_operation("smooth", {"smoothing_mm": 2.0})
        >>> result = pipeline.execute(input_mask, context)
    """
    
    def __init__(self):
        self.operations: List[OperationDefinition] = []
        self.operation_registry: Dict[str, Callable] = {}
        self._register_default_operations()
    
    def _register_default_operations(self):
        """Register all available operations from operations modules."""
        
        # Margin operations
        self.operation_registry['expand'] = self._op_expand
        self.operation_registry['contract'] = self._op_contract
        self.operation_registry['margin'] = self._op_margin
        self.operation_registry['anisotropic_margin'] = self._op_anisotropic_margin
        
        # Boolean operations
        self.operation_registry['union'] = self._op_union
        self.operation_registry['intersection'] = self._op_intersection
        self.operation_registry['subtract'] = self._op_subtract
        self.operation_registry['crop_to_boundary'] = self._op_crop_to_boundary
        
        # Advanced operations
        self.operation_registry['smooth'] = self._op_smooth
        self.operation_registry['fill_holes'] = self._op_fill_holes
        self.operation_registry['remove_small_components'] = self._op_remove_small_components
        self.operation_registry['keep_largest'] = self._op_keep_largest
        self.operation_registry['close_gaps'] = self._op_close_gaps
        self.operation_registry['remove_protrusions'] = self._op_remove_protrusions
        
        logger.debug(f"Registered {len(self.operation_registry)} operations")
    
    # ========================================================================
    # OPERATION WRAPPERS
    # ========================================================================
    
    def _op_expand(self, mask: sitk.Image, params: Dict, context: Dict) -> sitk.Image:
        """Expand structure by specified margin."""
        margin_mm = params.get('margin_mm', 5.0)
        kernel = params.get('kernel_type', 'ball')
        return operations.apply_uniform_margin(mask, margin_mm, kernel)
    
    def _op_contract(self, mask: sitk.Image, params: Dict, context: Dict) -> sitk.Image:
        """Contract structure by specified margin."""
        margin_mm = params.get('margin_mm', 3.0)
        kernel = params.get('kernel_type', 'ball')
        return operations.apply_uniform_margin(mask, -margin_mm, kernel)
    
    def _op_margin(self, mask: sitk.Image, params: Dict, context: Dict) -> sitk.Image:
        """Apply margin (positive or negative)."""
        margin_mm = params.get('margin_mm', 0.0)
        kernel = params.get('kernel_type', 'ball')
        return operations.apply_uniform_margin(mask, margin_mm, kernel)
    
    def _op_anisotropic_margin(self, mask: sitk.Image, params: Dict, context: Dict) -> sitk.Image:
        """Apply anisotropic margin."""
        margin_x = params.get('margin_x_mm', 0.0)
        margin_y = params.get('margin_y_mm', 0.0)
        margin_z = params.get('margin_z_mm', 0.0)
        return operations.apply_anisotropic_margin(mask, margin_x, margin_y, margin_z)
    
    def _op_union(self, mask: sitk.Image, params: Dict, context: Dict) -> sitk.Image:
        """Union with another ROI."""
        other_roi = params.get('other_roi')
        if not other_roi or other_roi not in context:
            raise ValueError(f"ROI '{other_roi}' not found in context for union operation")
        return operations.boolean_union(mask, context[other_roi])
    
    def _op_intersection(self, mask: sitk.Image, params: Dict, context: Dict) -> sitk.Image:
        """Intersection with another ROI."""
        other_roi = params.get('other_roi')
        if not other_roi or other_roi not in context:
            raise ValueError(f"ROI '{other_roi}' not found in context for intersection operation")
        return operations.boolean_intersection(mask, context[other_roi])
    
    def _op_subtract(self, mask: sitk.Image, params: Dict, context: Dict) -> sitk.Image:
        """Subtract another ROI."""
        other_roi = params.get('other_roi')
        margin_mm = params.get('margin_mm', 0.0)
        
        if not other_roi or other_roi not in context:
            raise ValueError(f"ROI '{other_roi}' not found in context for subtract operation")
        
        if margin_mm != 0:
            return operations.subtract_with_margin(mask, context[other_roi], margin_mm)
        else:
            return operations.boolean_subtraction(mask, context[other_roi])
    
    def _op_crop_to_boundary(self, mask: sitk.Image, params: Dict, context: Dict) -> sitk.Image:
        """Crop to boundary ROI."""
        boundary_roi = params.get('boundary_roi')
        if not boundary_roi or boundary_roi not in context:
            raise ValueError(f"ROI '{boundary_roi}' not found in context for crop operation")
        return operations.crop_to_boundary(mask, context[boundary_roi])
    
    def _op_smooth(self, mask: sitk.Image, params: Dict, context: Dict) -> sitk.Image:
        """Smooth structure."""
        smoothing_mm = params.get('smoothing_mm', 1.0)
        iterations = params.get('iterations', 1)
        return advanced_operations.smooth_structure(mask, smoothing_mm, iterations)
    
    def _op_fill_holes(self, mask: sitk.Image, params: Dict, context: Dict) -> sitk.Image:
        """Fill holes in structure."""
        fully_connected = params.get('fully_connected', False)
        return advanced_operations.fill_holes(mask, fully_connected)
    
    def _op_remove_small_components(self, mask: sitk.Image, params: Dict, context: Dict) -> sitk.Image:
        """Remove small components."""
        min_size_mm3 = params.get('min_size_mm3', 100.0)
        return advanced_operations.remove_small_components(mask, min_size_mm3)
    
    def _op_keep_largest(self, mask: sitk.Image, params: Dict, context: Dict) -> sitk.Image:
        """Keep only largest component."""
        return advanced_operations.keep_largest_component(mask)
    
    def _op_close_gaps(self, mask: sitk.Image, params: Dict, context: Dict) -> sitk.Image:
        """Close gaps in structure."""
        gap_size_mm = params.get('gap_size_mm', 2.0)
        return advanced_operations.close_gaps(mask, gap_size_mm)
    
    def _op_remove_protrusions(self, mask: sitk.Image, params: Dict, context: Dict) -> sitk.Image:
        """Remove protrusions from structure."""
        protrusion_size_mm = params.get('protrusion_size_mm', 2.0)
        return advanced_operations.remove_protrusions(mask, protrusion_size_mm)
    
    # ========================================================================
    # PIPELINE MANAGEMENT
    # ========================================================================
    
    def add_operation(
        self,
        operation_type: str,
        parameters: Optional[Dict[str, Any]] = None,
        source_roi: Optional[str] = None,
        output_name: Optional[str] = None
    ):
        """
        Add an operation to the pipeline.
        
        Args:
            operation_type: Type of operation (must be registered)
            parameters: Parameters for the operation
            source_roi: Name of source ROI (if different from pipeline input)
            output_name: Optional name for storing intermediate result
        """
        if operation_type not in self.operation_registry:
            raise ValueError(f"Unknown operation type: '{operation_type}'. "
                           f"Available: {list(self.operation_registry.keys())}")
        
        op_def = OperationDefinition(
            operation_type=operation_type,
            parameters=parameters or {},
            source_roi=source_roi,
            output_name=output_name
        )
        
        self.operations.append(op_def)
        logger.debug(f"Added operation: {operation_type} with params {parameters}")
    
    def execute(
        self,
        input_mask: sitk.Image,
        context: Optional[Dict[str, sitk.Image]] = None
    ) -> sitk.Image:
        """
        Execute all operations in the pipeline sequentially.
        
        Args:
            input_mask: Initial SimpleITK mask to process
            context: Dictionary of available ROI masks (for boolean operations)
                    Keys are ROI names, values are SimpleITK masks
        
        Returns:
            sitk.Image: Final processed mask
        """
        if not self.operations:
            logger.warning("No operations in pipeline, returning input mask")
            return input_mask
        
        context = context or {}
        current_mask = input_mask
        
        logger.info(f"Executing pipeline with {len(self.operations)} operations")
        
        for idx, op_def in enumerate(self.operations):
            logger.info(f"Step {idx+1}/{len(self.operations)}: {op_def.operation_type}")
            
            try:
                # Get the operation function
                op_func = self.operation_registry[op_def.operation_type]
                
                # Use source ROI if specified, otherwise use current mask
                if op_def.source_roi:
                    if op_def.source_roi not in context:
                        raise ValueError(f"Source ROI '{op_def.source_roi}' not found in context")
                    source_mask = context[op_def.source_roi]
                else:
                    source_mask = current_mask
                
                # Execute operation
                result_mask = op_func(source_mask, op_def.parameters, context)
                
                # Store intermediate result if named
                if op_def.output_name:
                    context[op_def.output_name] = result_mask
                    logger.debug(f"Stored intermediate result as '{op_def.output_name}'")
                
                # Update current mask
                current_mask = result_mask
                
            except Exception as e:
                logger.error(f"Operation {idx+1} ({op_def.operation_type}) failed: {str(e)}")
                raise RuntimeError(f"Pipeline execution failed at step {idx+1}: {str(e)}")
        
        logger.info("Pipeline execution completed successfully")
        return current_mask
    
    # ========================================================================
    # SERIALIZATION
    # ========================================================================
    
    @classmethod
    def from_dict(cls, pipeline_dict: Dict[str, Any]) -> 'OperationPipeline':
        """
        Create pipeline from dictionary definition.
        
        Expected format:
        {
            "operations": [
                {
                    "type": "expand",
                    "parameters": {"margin_mm": 5.0},
                    "source_roi": null,
                    "output_name": null
                },
                ...
            ]
        }
        """
        pipeline = cls()
        
        operations_list = pipeline_dict.get('operations', [])
        for op_dict in operations_list:
            pipeline.add_operation(
                operation_type=op_dict.get('type'),
                parameters=op_dict.get('parameters', {}),
                source_roi=op_dict.get('source_roi'),
                output_name=op_dict.get('output_name')
            )
        
        return pipeline
    
    @classmethod
    def from_json(cls, json_string: str) -> 'OperationPipeline':
        """Create pipeline from JSON string."""
        pipeline_dict = json.loads(json_string)
        return cls.from_dict(pipeline_dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert pipeline to dictionary."""
        return {
            'operations': [
                {
                    'type': op.operation_type,
                    'parameters': op.parameters,
                    'source_roi': op.source_roi,
                    'output_name': op.output_name
                }
                for op in self.operations
            ]
        }
    
    def to_json(self, indent: int = 2) -> str:
        """Convert pipeline to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def create_simple_pipeline(operation_type: str, **kwargs) -> OperationPipeline:
    """
    Create a simple single-operation pipeline.
    
    Args:
        operation_type: Type of operation
        **kwargs: Parameters for the operation
        
    Returns:
        OperationPipeline with single operation
    """
    pipeline = OperationPipeline()
    pipeline.add_operation(operation_type, parameters=kwargs)
    return pipeline


def parse_operation_string(operation_string: str) -> OperationPipeline:
    """
    Parse a human-readable operation string into a pipeline.
    
    Format: "operation1(param1=value1, param2=value2) | operation2(...) | ..."
    
    Example: "expand(margin_mm=5.0) | crop_to_boundary(boundary_roi=Body) | smooth(smoothing_mm=2.0)"
    
    Note: This is a simplified parser. For complex pipelines, use JSON/dict format.
    
    Args:
        operation_string: Human-readable operation string
        
    Returns:
        OperationPipeline
    """
    logger.info(f"Parsing operation string: {operation_string}")
    
    pipeline = OperationPipeline()
    
    # Split by pipe character
    operations = [op.strip() for op in operation_string.split('|')]
    
    for op_str in operations:
        # Parse operation name and parameters
        if '(' in op_str:
            op_name = op_str[:op_str.index('(')].strip()
            params_str = op_str[op_str.index('(')+1:op_str.rindex(')')].strip()
            
            # Parse parameters
            params = {}
            if params_str:
                for param in params_str.split(','):
                    key, value = param.split('=')
                    key = key.strip()
                    value = value.strip()
                    
                    # Try to convert to appropriate type
                    try:
                        # Try float
                        if '.' in value:
                            params[key] = float(value)
                        else:
                            params[key] = int(value)
                    except ValueError:
                        # Keep as string (for ROI names)
                        params[key] = value.strip('"\'')
        else:
            op_name = op_str.strip()
            params = {}
        
        pipeline.add_operation(op_name, parameters=params)
    
    logger.info(f"Parsed {len(pipeline.operations)} operations")
    return pipeline
