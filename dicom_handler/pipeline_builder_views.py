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
from django.views.decorators.http import require_http_methods

from .models import (
    AutosegmentationTemplate,
    AutosegmentationModel,
)
from rule_based_segmentation.models import PipelineRule
from rule_based_segmentation.utils.pipeline_persistence import (
    pipeline_data_from_pipeline,
    save_pipeline_from_dict,
)
from .utils.template_pipeline import (
    template_pipeline_name,
)

logger = logging.getLogger(__name__)


def _redirect_to_referer(request):
    """Redirect to the request's Referer, but only for same-site relative URLs.

    ``HTTP_REFERER`` is attacker-controlled; only accept a relative path that
    is not protocol-relative ('//host') and contains no backslash, otherwise
    fall back to '/' (prevents open redirect). The location is rebuilt with a
    constant '/' prefix so the redirect target is provably same-site relative
    (also satisfies CodeQL's py/url-redirection, which does not treat the
    startswith checks above as a sanitizer).
    """
    referer = request.META.get('HTTP_REFERER', '/')
    if referer.startswith('/') and not referer.startswith('//') and '\\' not in referer:
        return redirect("/" + referer[1:])
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


# ---------------------------------------------------------------------------
# Template pipeline editor (Phase 5, A3)
#
# A template's additional structures live in ONE SegmentationPipeline
# (template.additional_structures_pipeline). This editor authors that pipeline
# via the shared rule_based_pipeline_builder.js, seeded from the template's
# autosegmented ROIs. The old per-row views above remain until A6 removes the
# AdditionalStructures model and its UI.
# ---------------------------------------------------------------------------


@login_required
@permission_required('dicom_handler.change_autosegmentationtemplate', raise_exception=True)
def template_pipeline_view(request, template_id):
    """Editor page for the template's additional-structures pipeline."""
    template = get_object_or_404(AutosegmentationTemplate, id=template_id)
    pipeline = template.additional_structures_pipeline

    context = {
        'template': template,
        'available_structures': json.dumps(_get_available_structures(template)),
        'rule_type_choices': PipelineRule.RULE_TYPE_CHOICES,
        'roi_type_choices': PipelineRule.ROI_TYPE_CHOICES,
        'js_cache_bust': _builder_js_cache_bust(),
        'pipeline_data': (
            pipeline_data_from_pipeline(pipeline) if pipeline
            else {"rules": [], "structures": []}
        ),
        'pipeline_name': template_pipeline_name(template),
    }

    return render(request, 'dicom_handler/template_pipeline_editor.html', context)


@login_required
@permission_required('dicom_handler.change_autosegmentationtemplate', raise_exception=True)
@require_http_methods(["POST"])
def template_pipeline_save(request, template_id):
    """Save the template's additional-structures pipeline from the builder.

    The builder posts ``pipeline_data`` (RBS rule JSON). The pipeline is saved
    through the canonical ``save_pipeline_from_dict`` (which deletes stale rules
    and re-creates them), forced to the fixed convention name / private /
    active, and linked to the template via the OneToOne field.
    """
    template = get_object_or_404(AutosegmentationTemplate, id=template_id)

    raw = request.POST.get('pipeline_data')
    if not raw:
        data = {"rules": [], "structures": []}
    else:
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            messages.error(request, 'Invalid pipeline data. Please try again.')
            return _redirect_to_referer(request)

    # Enforce the fixed convention (ignore any name the builder posted).
    data['name'] = template_pipeline_name(template)
    data['is_public'] = False

    try:
        existing = template.additional_structures_pipeline
        with transaction.atomic():
            pipeline = save_pipeline_from_dict(data, request.user, pipeline=existing)
            pipeline.is_public = False
            pipeline.is_active = True
            pipeline.save(update_fields=['is_public', 'is_active'])
            template.additional_structures_pipeline = pipeline
            template.save(update_fields=['additional_structures_pipeline'])

        messages.success(request, 'Additional-structures pipeline saved.')
        logger.info(
            f"Saved additional-structures pipeline for template "
            f"{template.template_name}: {pipeline.id}"
        )
        return redirect('dicom_handler:template_detail', template_id=template.id)

    except (ValidationError, ValueError) as e:
        messages.error(request, f'Validation error: {e}')
        logger.error(f'Validation error in template_pipeline_save: {e}')
        return _redirect_to_referer(request)
    except Exception as e:
        messages.error(request, f'Error saving pipeline: {str(e)}')
        logger.error(f'Error in template_pipeline_save: {str(e)}', exc_info=True)
        return _redirect_to_referer(request)
