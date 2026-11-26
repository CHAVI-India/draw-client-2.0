"""
Views for managing AdditionalStructures
"""

import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import (
    AdditionalStructures,
    AutosegmentationStructure,
    AutosegmentationTemplate,
)
from rule_based_segmentation.models import SegmentationPipeline
from rule_based_segmentation.utils.pipeline_persistence import (
    parse_pipeline_data,
    pin_final_rule,
    referenced_structure_names,
    save_pipeline_from_dict,
)

logger = logging.getLogger(__name__)


def _available_structure_names(template, exclude_structure=None):
    """ROIs an additional-structure pipeline may reference for a template.

    Base ROIs (the template's reidentified structure set) + sibling
    additional-structure labels.
    """
    names = set()
    base = (
        AutosegmentationStructure.objects.filter(
            autosegmentation_model__autosegmentation_template_name=template
        )
        .select_related("structureproperties")
    )
    for struct in base:
        props = getattr(struct, "structureproperties", None)
        if props and props.roi_label:
            names.add(props.roi_label)
        if struct.name:
            names.add(struct.name)
    siblings = AdditionalStructures.objects.filter(autosegmentation_template=template)
    if exclude_structure is not None and exclude_structure.pk:
        siblings = siblings.exclude(pk=exclude_structure.pk)
    names.update(siblings.values_list("roi_label", flat=True))
    return names


def _save_pipeline_for_structure(request, template, structure, existing_pipeline=None):
    """Persist the posted pipeline for an additional structure.

    Parses ``pipeline_data``, creates/refreshes a SegmentationPipeline, pins the
    final rule to the structure's identity, and validates that every referenced
    structure belongs to the template. Returns the pipeline (zero rules == empty
    ROI). Raises ValidationError on a bad reference set (and removes any orphan).
    """
    data = parse_pipeline_data(request.POST)

    if data is None:
        # No builder payload: an empty ROI ("no step"). Keep an explicit (empty)
        # pipeline so the FK is always present.
        if existing_pipeline is None:
            existing_pipeline = SegmentationPipeline.objects.create(
                name=f"{structure.roi_label} generation",
                is_public=False, is_active=False,
            )
        return existing_pipeline

    rules = data.get("rules", [])
    if existing_pipeline is None:
        pipeline = save_pipeline_from_dict(data, request.user)
    else:
        pipeline = save_pipeline_from_dict(data, request.user, pipeline=existing_pipeline)

    # Stable, descriptive name; keep it private + inactive (it is not a
    # standalone job pipeline).
    pipeline.name = f"{structure.roi_label} generation"
    pipeline.is_public = False
    pipeline.is_active = False
    pipeline.save(update_fields=["name", "is_public", "is_active"])

    # Pin the exported ROI to the binding (name / color / interpreted type).
    pin_final_rule(
        pipeline,
        structure.roi_label,
        structure.roi_display_color,
        structure.rt_roi_interpreted_type,
    )

    # Validate references: every input structure must be part of the template,
    # except names produced by the pipeline itself (intermediates + final).
    referenced = referenced_structure_names(rules)
    produced = {r.get("name", "").strip() for r in rules}
    available = _available_structure_names(template, exclude_structure=structure)
    missing = (referenced - available) - produced
    if missing:
        pipeline.delete()  # drop the orphan if we are not going to keep it
        raise ValidationError({
            "pipeline": (
                "These structures are not part of the template: "
                f"{', '.join(sorted(missing))}"
            )
        })
    return pipeline


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
            pipeline = _save_pipeline_for_structure(request, template, structure)
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

            pipeline = _save_pipeline_for_structure(
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
