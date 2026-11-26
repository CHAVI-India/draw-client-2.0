"""
Views for managing AdditionalStructures
"""

import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import AdditionalStructures, AutosegmentationTemplate
from .utils.additional_structure_pipeline import save_pipeline_for_structure

logger = logging.getLogger(__name__)


@login_required
@permission_required('dicom_handler.add_additionalstructures', raise_exception=True)
def add_additional_structure(request):
    """
    Add a new AdditionalStructure to a template
    """
    if request.method != 'POST':
        return redirect('dicom_handler:template_list')

    template_id = request.POST.get('template_id')
    template = get_object_or_404(AutosegmentationTemplate, id=template_id)

    try:
        with transaction.atomic():
            structure = AdditionalStructures(
                autosegmentation_template=template,
                roi_label=request.POST.get('roi_label', '').strip(),
                rt_roi_interpreted_type=request.POST.get('rt_roi_interpreted_type', '').strip() or None,
                roi_display_color=request.POST.get('roi_display_color', '').strip() or None,
            )
            # Validate label/color/uniqueness
            structure.full_clean()

            # Persist the RBS pipeline (empty payload -> empty ROI "no step").
            pipeline = save_pipeline_for_structure(request, template, structure)
            structure.pipeline = pipeline
            structure.save()

        messages.success(request, f'Successfully added additional structure: {structure.roi_label}')

    except ValidationError as e:
        error_messages = []
        if hasattr(e, 'message_dict'):
            for field, errors in e.message_dict.items():
                for error in errors:
                    error_messages.append(f'{field}: {error}')
        else:
            error_messages.append(str(e))

        for error_msg in error_messages:
            messages.error(request, error_msg)
        logger.error(f'Validation error adding additional structure: {e}')

    except Exception as e:
        messages.error(request, f'Error adding structure: {str(e)}')
        logger.error(f'Error adding structure: {str(e)}', exc_info=True)

    return redirect('dicom_handler:template_detail', template_id=template.id)


@login_required
@permission_required('dicom_handler.change_additionalstructures', raise_exception=True)
def edit_additional_structure(request):
    """
    Edit an existing AdditionalStructure
    """
    if request.method != 'POST':
        return redirect('dicom_handler:template_list')

    structure_id = request.POST.get('structure_id')

    structure = get_object_or_404(AdditionalStructures, id=structure_id)
    template = structure.autosegmentation_template

    try:
        with transaction.atomic():
            structure.roi_label = request.POST.get('roi_label', '').strip()
            structure.rt_roi_interpreted_type = request.POST.get('rt_roi_interpreted_type', '').strip() or None
            structure.roi_display_color = request.POST.get('roi_display_color', '').strip() or None
            # roi_generation_logic is intentionally no longer written (frozen legacy
            # fallback); the RBS pipeline is the source of truth.
            structure.full_clean()

            pipeline = save_pipeline_for_structure(
                request, template, structure, existing_pipeline=structure.pipeline
            )
            structure.pipeline = pipeline
            structure.save()

        messages.success(request, f'Successfully updated additional structure: {structure.roi_label}')

    except ValidationError as e:
        error_messages = []
        if hasattr(e, 'message_dict'):
            for field, errors in e.message_dict.items():
                for error in errors:
                    error_messages.append(f'{field}: {error}')
        else:
            error_messages.append(str(e))

        for error_msg in error_messages:
            messages.error(request, error_msg)
        logger.error(f'Validation error editing additional structure: {e}')

    except Exception as e:
        messages.error(request, f'Error updating structure: {str(e)}')
        logger.error(f'Error updating structure: {str(e)}', exc_info=True)

    return redirect('dicom_handler:template_detail', template_id=template.id)


@login_required
@permission_required('dicom_handler.delete_additionalstructures', raise_exception=True)
def delete_additional_structure(request):
    """
    Delete an AdditionalStructure
    """
    if request.method != 'POST':
        return redirect('dicom_handler:template_list')

    structure_id = request.POST.get('structure_id')
    template_id = request.POST.get('template_id')

    structure = get_object_or_404(AdditionalStructures, id=structure_id)
    template = structure.autosegmentation_template
    roi_label = structure.roi_label

    try:
        structure.delete()
        messages.success(request, f'Successfully deleted additional structure: {roi_label}')
    except Exception as e:
        messages.error(request, f'Error deleting structure: {str(e)}')
        logger.error(f'Error deleting additional structure: {str(e)}', exc_info=True)

    return redirect('dicom_handler:template_detail', template_id=template.id)
