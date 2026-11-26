"""
Views for the Pipeline Builder - dedicated page for building ROI generation logic.

Phase 4: the builder now authors a RBS SegmentationPipeline (via the shared
``rule_based_pipeline_builder.js``) instead of a legacy roi_generation_logic blob.
"""

import logging
import json
import os
from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from .models import (
    AdditionalStructures,
    AutosegmentationTemplate,
    AutosegmentationModel,
    AutosegmentationStructure,
)
from rule_based_segmentation.models import PipelineRule, SegmentationPipeline
from rule_based_segmentation.utils.pipeline_persistence import (
    pipeline_data_from_pipeline,
)
from .utils.additional_structure_pipeline import save_pipeline_for_structure

logger = logging.getLogger(__name__)


def _redirect_to_referer(request):
    """Redirect to the request's Referer, but only for same-site relative URLs.

    ``HTTP_REFERER`` is attacker-controlled; only accept a relative path that
    is not protocol-relative ('//host') and contains no backslash, otherwise
    fall back to '/' (prevents open redirect).
    """
    referer = request.META.get('HTTP_REFERER', '/')
    if referer.startswith('/') and not referer.startswith('//') and '\\' not in referer:
        return redirect(referer)
    return redirect('/')


def _builder_js_cache_bust() -> str:
    """Short content hash of the RBS builder JS, appended to the <script> URL so
    any change to the builder JS busts the browser cache automatically.
    Returns '' if the file is missing (dev / edge case)."""
    import hashlib

    js_path = os.path.join(
        settings.STATICFILES_DIRS[0], "js", "rule_based_pipeline_builder.js"
    )
    try:
        with open(js_path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()[:16]
    except OSError:
        return ""


def _pipeline_data_for(structure):
    """Builder payload for an existing structure's pipeline.

    Uses the FK pipeline when present; otherwise (legacy row) synthesizes the
    frozen roi_generation_logic into a throwaway pipeline just to render it.
    """
    if structure.pipeline_id:
        return pipeline_data_from_pipeline(structure.pipeline)
    if structure.roi_generation_logic:
        from rule_based_segmentation.utils.legacy_synthesis import synthesize_rules

        tmp = SegmentationPipeline.objects.create(
            name="tmp-synth", is_public=False, is_active=False
        )
        try:
            synthesize_rules(structure, pipeline=tmp)
            return pipeline_data_from_pipeline(tmp)
        finally:
            tmp.delete()
    return {"rules": [], "structures": []}


@login_required
@permission_required('dicom_handler.add_additionalstructures', raise_exception=True)
def pipeline_builder_new(request, template_id):
    """
    Pipeline builder page for creating a new additional structure.

    Args:
        template_id: ID of the autosegmentation template
    """
    template = get_object_or_404(AutosegmentationTemplate, id=template_id)

    available_structures = _get_available_structures(template)

    context = {
        'template': template,
        'available_structures': json.dumps(available_structures),
        'rule_type_choices': PipelineRule.RULE_TYPE_CHOICES,
        'roi_type_choices': PipelineRule.ROI_TYPE_CHOICES,
        'js_cache_bust': _builder_js_cache_bust(),
        'mode': 'new',
        'structure': None,
        'pipeline_data': {"rules": [], "structures": []},
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

    available_structures = _get_available_structures(template)

    context = {
        'template': template,
        'available_structures': json.dumps(available_structures),
        'rule_type_choices': PipelineRule.RULE_TYPE_CHOICES,
        'roi_type_choices': PipelineRule.ROI_TYPE_CHOICES,
        'js_cache_bust': _builder_js_cache_bust(),
        'mode': 'edit',
        'structure': structure,
        'pipeline_data': _pipeline_data_for(structure),
    }

    return render(request, 'dicom_handler/pipeline_builder.html', context)


@login_required
@require_http_methods(["POST"])
def pipeline_builder_save(request):
    """
    Save the pipeline and structure data from the pipeline builder.

    Handles both new structures and updates to existing ones. The builder posts
    ``pipeline_data`` (RBS rule JSON); an empty payload means an empty ROI.
    """
    try:
        mode = request.POST.get('mode')
        template_id = request.POST.get('template_id')
        structure_id = request.POST.get('structure_id')

        roi_label = request.POST.get('roi_label', '').strip()
        rt_roi_interpreted_type = request.POST.get('rt_roi_interpreted_type', '').strip() or None
        roi_display_color = request.POST.get('roi_display_color', '').strip() or None

        if not roi_label:
            messages.error(request, 'ROI Label is required')
            return _redirect_to_referer(request)

        with transaction.atomic():
            if mode == 'new':
                template = get_object_or_404(AutosegmentationTemplate, id=template_id)

                structure = AdditionalStructures(
                    autosegmentation_template=template,
                    roi_label=roi_label,
                    rt_roi_interpreted_type=rt_roi_interpreted_type,
                    roi_display_color=roi_display_color,
                )
                structure.full_clean()

                pipeline = save_pipeline_for_structure(request, template, structure)
                structure.pipeline = pipeline
                structure.save()

                messages.success(request, f'Successfully created additional structure: {roi_label}')
                logger.info(
                    f'Created new additional structure: {roi_label} for template {template.template_name}'
                )

            elif mode == 'edit':
                structure = get_object_or_404(AdditionalStructures, id=structure_id)
                template = structure.autosegmentation_template

                structure.roi_label = roi_label
                structure.rt_roi_interpreted_type = rt_roi_interpreted_type
                structure.roi_display_color = roi_display_color
                structure.full_clean()

                pipeline = save_pipeline_for_structure(
                    request, template, structure, existing_pipeline=structure.pipeline
                )
                structure.pipeline = pipeline
                structure.save()

                messages.success(request, f'Successfully updated additional structure: {roi_label}')
                logger.info(f'Updated additional structure: {roi_label}')

            else:
                messages.error(request, 'Invalid mode')
                return redirect('dicom_handler:template_list')

        return redirect('dicom_handler:template_detail', template_id=template.id)

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
        logger.error(f'Validation error in pipeline_builder_save: {e}')
        return _redirect_to_referer(request)

    except Exception as e:
        messages.error(request, f'Error saving structure: {str(e)}')
        logger.error(f'Error in pipeline_builder_save: {str(e)}', exc_info=True)
        return _redirect_to_referer(request)


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
    except Exception:
        logger.error("Error in get_available_structures_api", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': 'Failed to load available structures'
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
                'model': model.name,
            })

    # Sort by label
    structures.sort(key=lambda x: x['label'])

    return structures
