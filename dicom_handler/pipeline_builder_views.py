"""
Views for the Pipeline Builder - dedicated page for building ROI generation logic
"""

import logging
import json
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from .models import (
    AdditionalStructures, 
    AutosegmentationTemplate,
    AutosegmentationModel,
    AutosegmentationStructure
)

logger = logging.getLogger(__name__)


@login_required
@permission_required('dicom_handler.add_additionalstructures', raise_exception=True)
def pipeline_builder_new(request, template_id):
    """
    Pipeline builder page for creating a new additional structure.
    
    Args:
        template_id: ID of the autosegmentation template
    """
    template = get_object_or_404(AutosegmentationTemplate, id=template_id)
    
    # Get available structures from this template
    available_structures = _get_available_structures(template)
    
    context = {
        'template': template,
        'available_structures': json.dumps(available_structures),  # Serialize to JSON
        'mode': 'new',
        'structure': None,
        'initial_pipeline': None
    }
    
    return render(request, 'dicom_handler/pipeline_builder.html', context)


@login_required
@permission_required('dicom_handler.change_additionalstructures', raise_exception=True)
def pipeline_builder_edit(request, structure_id):
    """
    Pipeline builder page for editing an existing additional structure.
    
    Args:
        structure_id: ID of the AdditionalStructures instance
    """
    structure = get_object_or_404(AdditionalStructures, id=structure_id)
    template = structure.autosegmentation_template
    
    # Get available structures from this template
    available_structures = _get_available_structures(template)
    
    # Get existing pipeline (already a dict since it's a JSONField)
    initial_pipeline = structure.roi_generation_logic
    
    context = {
        'template': template,
        'available_structures': json.dumps(available_structures),  # Serialize to JSON
        'mode': 'edit',
        'structure': structure,
        'initial_pipeline': json.dumps(initial_pipeline) if initial_pipeline else None
    }
    
    return render(request, 'dicom_handler/pipeline_builder.html', context)


@login_required
@require_http_methods(["POST"])
def pipeline_builder_save(request):
    """
    Save the pipeline and structure data from the pipeline builder.
    
    Handles both new structures and updates to existing ones.
    """
    try:
        mode = request.POST.get('mode')
        template_id = request.POST.get('template_id')
        structure_id = request.POST.get('structure_id')
        
        # Get form data
        roi_label = request.POST.get('roi_label', '').strip()
        rt_roi_interpreted_type = request.POST.get('rt_roi_interpreted_type', '').strip() or None
        roi_display_color = request.POST.get('roi_display_color', '').strip() or None
        roi_generation_logic_str = request.POST.get('roi_generation_logic', '').strip()
        
        # Parse JSON string to dict for JSONField
        roi_generation_logic = None
        if roi_generation_logic_str:
            try:
                roi_generation_logic = json.loads(roi_generation_logic_str)
            except json.JSONDecodeError as e:
                messages.error(request, f'Invalid JSON in generation logic: {str(e)}')
                return redirect(request.META.get('HTTP_REFERER', '/'))
        
        # Validate required fields
        if not roi_label:
            messages.error(request, 'ROI Label is required')
            return redirect(request.META.get('HTTP_REFERER', '/'))
        
        if mode == 'new':
            # Create new structure
            template = get_object_or_404(AutosegmentationTemplate, id=template_id)
            
            structure = AdditionalStructures(
                autosegmentation_template=template,
                roi_label=roi_label,
                rt_roi_interpreted_type=rt_roi_interpreted_type,
                roi_display_color=roi_display_color,
                roi_generation_logic=roi_generation_logic
            )
            
            # Validate
            structure.full_clean()
            structure.save()
            
            messages.success(request, f'Successfully created additional structure: {roi_label}')
            logger.info(f'Created new additional structure: {roi_label} for template {template.template_name}')
            
        elif mode == 'edit':
            # Update existing structure
            structure = get_object_or_404(AdditionalStructures, id=structure_id)
            
            structure.roi_label = roi_label
            structure.rt_roi_interpreted_type = rt_roi_interpreted_type
            structure.roi_display_color = roi_display_color
            structure.roi_generation_logic = roi_generation_logic
            
            # Validate
            structure.full_clean()
            structure.save()
            
            messages.success(request, f'Successfully updated additional structure: {roi_label}')
            logger.info(f'Updated additional structure: {roi_label}')
            
            template = structure.autosegmentation_template
        else:
            messages.error(request, 'Invalid mode')
            return redirect('dicom_handler:template_list')
        
        # Redirect back to template detail page
        return redirect('dicom_handler:template_detail', template_id=template.id)
        
    except Exception as e:
        messages.error(request, f'Error saving structure: {str(e)}')
        logger.error(f'Error in pipeline_builder_save: {str(e)}', exc_info=True)
        return redirect(request.META.get('HTTP_REFERER', '/'))


@login_required
@require_http_methods(["GET"])
def get_available_structures_api(request, template_id):
    """
    API endpoint to get available structures for a template.
    Returns JSON list of structures.
    """
    try:
        template = get_object_or_404(AutosegmentationTemplate, id=template_id)
        structures = _get_available_structures(template)
        
        return JsonResponse({
            'success': True,
            'structures': structures
        })
    except Exception as e:
        logger.error(f'Error in get_available_structures_api: {str(e)}')
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


def _get_available_structures(template):
    """
    Helper function to get all available autosegmented structures for a template.
    
    Args:
        template: AutosegmentationTemplate instance
        
    Returns:
        List of dicts with 'value' and 'label' keys
    """
    structures = []
    
    # Get all models for this template
    models = AutosegmentationModel.objects.filter(
        autosegmentation_template_name=template
    ).prefetch_related(
        'autosegmentationstructure_set',
        'autosegmentationstructure_set__structureproperties'
    )
    
    for model in models:
        for structure in model.autosegmentationstructure_set.all():
            # Use roi_label if available, otherwise use structure name
            if hasattr(structure, 'structureproperties') and structure.structureproperties.roi_label:
                label = structure.structureproperties.roi_label
            else:
                label = structure.name
            
            structures.append({
                'value': label,
                'label': label,
                'model': model.name
            })
    
    # Sort by label
    structures.sort(key=lambda x: x['label'])
    
    return structures
