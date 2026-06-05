from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib import messages
from django.http import JsonResponse
from django.db import transaction
from django.views.decorators.http import require_http_methods
from django.core.exceptions import ValidationError
import json
import logging

from .forms import XMLTemplateUploadForm, StructureMappingForm
from .models import (
    AutosegmentationTemplate,
    AutosegmentationStructure,
    StructureProperties
)
from .xml_template_parser import XMLTemplateParser

logger = logging.getLogger(__name__)


def _smart_truncate_roi_name(name: str, max_length: int = 16) -> str:
    """
    Intelligently truncate ROI name to max_length while preserving laterality indicators.
    
    Preserves common laterality suffixes: _L, _R, _LEFT, _RIGHT, _Lt, _Rt
    
    Args:
        name: Original ROI name
        max_length: Maximum length (default 16 for TG263 compliance)
        
    Returns:
        Truncated name with laterality preserved if possible
        
    Examples:
        "PAROTID_GLAND_RIGHT" (19 chars) -> "PAROTID_G_RIGHT" (15 chars)
        "SUBMANDIBULAR_L" (15 chars) -> "SUBMANDIBULAR_L" (unchanged)
        "VERY_LONG_STRUCTURE_NAME_R" (26 chars) -> "VERY_LONG_ST_R" (14 chars)
    """
    if len(name) <= max_length:
        return name
    
    # Common laterality suffixes (case-insensitive)
    laterality_suffixes = ['_RIGHT', '_LEFT', '_R', '_L', '_Rt', '_Lt']
    
    # Check if name ends with a laterality suffix
    laterality_suffix = None
    name_without_suffix = name
    
    for suffix in laterality_suffixes:
        if name.upper().endswith(suffix.upper()):
            laterality_suffix = name[-len(suffix):]  # Preserve original case
            name_without_suffix = name[:-len(suffix)]
            break
    
    if laterality_suffix:
        # Calculate how much space we have for the main part
        available_length = max_length - len(laterality_suffix)
        
        if available_length > 0:
            # Truncate the main part and add back the laterality suffix
            truncated = name_without_suffix[:available_length] + laterality_suffix
            return truncated
        else:
            # Laterality suffix itself is too long, just truncate normally
            return name[:max_length]
    else:
        # No laterality suffix, truncate normally
        return name[:max_length]


@login_required
@permission_required('dicom_handler.add_structureproperties', raise_exception=True)
def xml_template_wizard_start(request):
    """
    Step 1: Upload XML template file and select autosegmentation template
    """
    # Get pre-selected template from query parameter or session
    preselected_template_id = request.GET.get('template') or request.session.get('wizard_template_id')
    preselected_template = None
    template_locked = False
    
    if preselected_template_id:
        try:
            preselected_template = AutosegmentationTemplate.objects.get(id=preselected_template_id)
            # Store in session for persistence across wizard steps
            request.session['wizard_template_id'] = str(preselected_template.id)
            request.session['wizard_template_name'] = preselected_template.template_name
            request.session.modified = True
            template_locked = True
        except AutosegmentationTemplate.DoesNotExist:
            # Clear invalid template from session
            if 'wizard_template_id' in request.session:
                del request.session['wizard_template_id']
                del request.session['wizard_template_name']
                request.session.modified = True
    
    if request.method == 'POST':
        # If template is locked, we don't need template field validation
        if template_locked and preselected_template:
            # Create form without template field requirement
            form = XMLTemplateUploadForm(request.POST, request.FILES)
            form.fields['template'].required = False
            
            logger.debug(f"Template locked mode - Form data: {request.POST}")
            logger.debug(f"Files: {request.FILES}")
            logger.debug(f"Form is valid: {form.is_valid()}")
            if not form.is_valid():
                logger.error(f"Form errors: {form.errors}")
            
            if form.is_valid():
                template = preselected_template  # Use locked template
                xml_file = request.FILES['xml_file']
                
                try:
                    # Read and parse XML file
                    xml_content = xml_file.read().decode('utf-8')
                    parsed_data = XMLTemplateParser.parse_xml_file(xml_content)
                    
                    # Store parsed data in session
                    request.session['xml_template_data'] = {
                        'template_id': str(template.id),
                        'template_name': template.template_name,
                        'xml_filename': xml_file.name,
                        'template_info': parsed_data['template_info'],
                        'structures': parsed_data['structures'],
                        'total_structures': parsed_data['total_structures']
                    }
                    request.session.modified = True
                    
                    messages.success(
                        request,
                        f'Successfully parsed XML file with {parsed_data["total_structures"]} structures. '
                        f'Proceed to map structures to autosegmentation template.'
                    )
                    
                    return redirect('dicom_handler:xml_template_wizard_map')
                    
                except ValueError as e:
                    messages.error(request, f'Error parsing XML file: {str(e)}')
                except Exception as e:
                    logger.error(f'Error processing XML file: {str(e)}', exc_info=True)
                    messages.error(request, f'Unexpected error processing XML file: {str(e)}')
        else:
            # Normal flow when template is not locked
            if form.is_valid():
                template = form.cleaned_data['template']
                xml_file = request.FILES['xml_file']
                
                try:
                    # Read and parse XML file
                    xml_content = xml_file.read().decode('utf-8')
                    parsed_data = XMLTemplateParser.parse_xml_file(xml_content)
                    
                    # Store parsed data in session
                    request.session['xml_template_data'] = {
                        'template_id': str(template.id),
                        'template_name': template.template_name,
                        'xml_filename': xml_file.name,
                        'template_info': parsed_data['template_info'],
                        'structures': parsed_data['structures'],
                        'total_structures': parsed_data['total_structures']
                    }
                    request.session.modified = True
                    
                    messages.success(
                        request,
                        f'Successfully parsed XML file with {parsed_data["total_structures"]} structures. '
                        f'Proceed to map structures to autosegmentation template.'
                    )
                    
                    return redirect('dicom_handler:xml_template_wizard_map')
                    
                except ValueError as e:
                    messages.error(request, f'Error parsing XML file: {str(e)}')
                except Exception as e:
                    logger.error(f'Error processing XML file: {str(e)}', exc_info=True)
                    messages.error(request, f'Unexpected error processing XML file: {str(e)}')
    else:
        # Pre-populate form with selected template if provided
        initial_data = {}
        if preselected_template:
            initial_data['template'] = preselected_template
        
        form = XMLTemplateUploadForm(initial=initial_data)
    
    context = {
        'form': form,
        'step': 1,
        'step_title': 'Upload XML Template',
        'template_locked': template_locked,
        'preselected_template': preselected_template
    }
    
    return render(request, 'dicom_handler/xml_template_wizard_upload.html', context)


@login_required
@permission_required('dicom_handler.add_structureproperties', raise_exception=True)
def xml_template_wizard_map(request):
    """
    Step 2: Map autosegmentation structures to XML structures
    """
    # Get data from session
    xml_data = request.session.get('xml_template_data')
    if not xml_data:
        messages.error(request, 'No XML template data found. Please upload an XML file first.')
        return redirect('dicom_handler:xml_template_wizard_start')
    
    template = get_object_or_404(AutosegmentationTemplate, id=xml_data['template_id'])
    xml_structures = xml_data['structures']
    
    # Get all autosegmentation structures for this template
    autoseg_structures = AutosegmentationStructure.objects.filter(
        autosegmentation_model__autosegmentation_template_name=template
    ).select_related('autosegmentation_model').order_by('name')
    
    # Create a mapping of XML structure names for auto-matching
    xml_structure_map = {s['name'].lower(): s for s in xml_structures}
    
    # Helper functions for structure name normalization
    def normalize_spaces(name):
        """Replace spaces with underscores, preserve other separators"""
        return name.lower().replace(' ', '_')
    
    def normalize_fuzzy(name):
        """Remove all separators for fuzzy matching (spaces, underscores, hyphens)"""
        return name.lower().replace(' ', '').replace('_', '').replace('-', '')
    
    # Create normalized mappings for better matching
    xml_normalized_map = {normalize_spaces(s['name']): s for s in xml_structures}
    xml_fuzzy_map = {normalize_fuzzy(s['name']): s for s in xml_structures}
    
    if request.method == 'POST':
        # Process the mapping form submission
        mappings = []
        errors = []
        
        for idx, autoseg_struct in enumerate(autoseg_structures):
            prefix = f'structure_{idx}'
            
            # Get form data
            xml_structure_id = request.POST.get(f'{prefix}_xml_structure')
            roi_label = request.POST.get(f'{prefix}_roi_label', '').strip()
            rt_roi_type = request.POST.get(f'{prefix}_rt_roi_interpreted_type', '').strip()
            roi_color = request.POST.get(f'{prefix}_roi_display_color', '').strip()
            
            if not xml_structure_id:
                # Allow skipping - not all autoseg structures need XML mapping
                continue
            
            # Find the XML structure
            xml_structure = next((s for s in xml_structures if s['id'] == xml_structure_id), None)
            if not xml_structure:
                errors.append(f'XML structure not found for {autoseg_struct.name}')
                continue
            
            # Validate ROI label
            if roi_label:
                is_valid, error_msg = XMLTemplateParser.validate_roi_label(roi_label)
                if not is_valid:
                    errors.append(f'{autoseg_struct.name}: {error_msg}')
                    continue
            
            # Validate color (skip if None, empty, or the string "None")
            if roi_color and roi_color.lower() != 'none':
                is_valid, error_msg = XMLTemplateParser.validate_dicom_color(roi_color)
                if not is_valid:
                    errors.append(f'{autoseg_struct.name}: {error_msg}')
                    continue
            else:
                # Clear invalid color values
                roi_color = None
            
            mappings.append({
                'autoseg_structure_id': str(autoseg_struct.id),
                'xml_structure': xml_structure,
                'roi_label': roi_label or xml_structure['name'],
                'rt_roi_interpreted_type': rt_roi_type or None,
                'roi_display_color': roi_color or None
            })
        
        if errors:
            for error in errors:
                messages.error(request, error)
        else:
            # Store mappings in session and proceed to review
            request.session['xml_template_mappings'] = mappings
            request.session.modified = True
            
            # Store mapped XML structure IDs to identify unmapped ones later
            mapped_xml_ids = [m['xml_structure']['id'] for m in mappings]
            request.session['mapped_xml_structure_ids'] = mapped_xml_ids
            request.session.modified = True
            
            return redirect('dicom_handler:xml_template_wizard_review')
    
    # Prepare autoseg structures with auto-matched XML suggestions
    structures_with_suggestions = []
    for autoseg_struct in autoseg_structures:
        # Try to find a matching XML structure using multiple strategies
        suggested_match = None
        autoseg_name_lower = autoseg_struct.name.lower()
        autoseg_name_spaces = normalize_spaces(autoseg_struct.name)
        autoseg_name_fuzzy = normalize_fuzzy(autoseg_struct.name)
        
        # 1. Exact match (case-insensitive)
        if autoseg_name_lower in xml_structure_map:
            suggested_match = xml_structure_map[autoseg_name_lower]
        # 2. Space-normalized match (e.g., "Optic_Chiasm" matches "OPTIC CHIASM")
        elif autoseg_name_spaces in xml_normalized_map:
            suggested_match = xml_normalized_map[autoseg_name_spaces]
        # 3. Fuzzy match - removes all separators (e.g., "OpticChiasm" matches "OPTIC CHIASM")
        #    Only use for exact fuzzy match, not partial, to avoid false positives
        elif autoseg_name_fuzzy in xml_fuzzy_map:
            suggested_match = xml_fuzzy_map[autoseg_name_fuzzy]
        # 4. Partial match (substring) - use original lowercase names
        else:
            for xml_name, xml_struct in xml_structure_map.items():
                if autoseg_name_lower in xml_name or xml_name in autoseg_name_lower:
                    suggested_match = xml_struct
                    break
        
        structures_with_suggestions.append({
            'autoseg_structure': autoseg_struct,
            'suggested_match': suggested_match
        })
    
    context = {
        'template': template,
        'xml_filename': xml_data['xml_filename'],
        'template_info': xml_data['template_info'],
        'structures_with_suggestions': structures_with_suggestions,
        'xml_structures': xml_structures,
        'total_structures': len(autoseg_structures),
        'step': 2,
        'step_title': 'Map Structures'
    }
    
    return render(request, 'dicom_handler/xml_template_wizard_map.html', context)


@login_required
@permission_required('dicom_handler.add_structureproperties', raise_exception=True)
def xml_template_wizard_review(request):
    """
    Step 3: Review mappings before saving
    """
    # Get data from session
    xml_data = request.session.get('xml_template_data')
    mappings = request.session.get('xml_template_mappings')
    
    if not xml_data or not mappings:
        messages.error(request, 'No mapping data found. Please complete the previous steps.')
        return redirect('dicom_handler:xml_template_wizard_start')
    
    template = get_object_or_404(AutosegmentationTemplate, id=xml_data['template_id'])
    
    # Enrich mappings with autosegmentation structure details
    enriched_mappings = []
    for mapping in mappings:
        autoseg_structure = get_object_or_404(
            AutosegmentationStructure,
            id=mapping['autoseg_structure_id']
        )
        enriched_mappings.append({
            **mapping,
            'autoseg_structure': autoseg_structure
        })
    
    if request.method == 'POST':
        # Save the mappings
        return redirect('dicom_handler:xml_template_wizard_save')
    
    context = {
        'template': template,
        'xml_filename': xml_data['xml_filename'],
        'mappings': enriched_mappings,
        'total_mappings': len(enriched_mappings),
        'step': 3,
        'step_title': 'Review Mappings'
    }
    
    return render(request, 'dicom_handler/xml_template_wizard_review.html', context)


@login_required
@permission_required('dicom_handler.add_structureproperties', raise_exception=True)
def xml_template_wizard_additional(request):
    """
    Step 4: Select unmapped XML structures to save as AdditionalStructures
    """
    xml_data = request.session.get('xml_template_data')
    mappings = request.session.get('xml_template_mappings', [])
    mapped_xml_ids = request.session.get('mapped_xml_structure_ids', [])
    
    if not xml_data:
        messages.error(request, 'No XML data found. Please start from the beginning.')
        return redirect('dicom_handler:xml_template_wizard_start')
    
    template = get_object_or_404(AutosegmentationTemplate, id=xml_data['template_id'])
    all_xml_structures = xml_data['structures']
    
    # Filter out mapped structures and add truncated names for preview
    unmapped_structures = []
    for s in all_xml_structures:
        if s['id'] not in mapped_xml_ids:
            # Add truncated name for display
            structure_copy = s.copy()
            structure_copy['truncated_name'] = _smart_truncate_roi_name(s['name'], 16)
            unmapped_structures.append(structure_copy)
    
    if request.method == 'POST':
        selected_structure_ids = request.POST.getlist('selected_structures')
        
        # Save selected structures as AdditionalStructures
        from dicom_handler.models import AdditionalStructures
        
        created_additional_count = 0
        created_properties_count = 0
        updated_properties_count = 0
        errors = []
        
        try:
            with transaction.atomic():
                # First, save the mapped structures as StructureProperties
                for mapping in mappings:
                    try:
                        autoseg_structure = AutosegmentationStructure.objects.get(
                            id=mapping['autoseg_structure_id']
                        )
                        
                        structure_props, created = StructureProperties.objects.get_or_create(
                            autosegmentation_structure=autoseg_structure,
                            defaults={
                                'roi_label': mapping['roi_label'],
                                'rt_roi_interpreted_type': mapping['rt_roi_interpreted_type'],
                                'roi_display_color': mapping['roi_display_color']
                            }
                        )
                        
                        if not created:
                            structure_props.roi_label = mapping['roi_label']
                            structure_props.rt_roi_interpreted_type = mapping['rt_roi_interpreted_type']
                            structure_props.roi_display_color = mapping['roi_display_color']
                            structure_props.save()
                            updated_properties_count += 1
                        else:
                            created_properties_count += 1
                            
                    except AutosegmentationStructure.DoesNotExist:
                        errors.append(f'Autosegmentation structure not found for mapping: {mapping}')
                    except Exception as e:
                        errors.append(f'Error saving structure properties: {str(e)}')
                        logger.error(f'Error saving structure properties: {str(e)}', exc_info=True)
                
                # Pre-process selected structures to detect duplicate ROI names
                roi_names_map = {}
                for struct_id in selected_structure_ids:
                    xml_struct = next((s for s in unmapped_structures if s['id'] == struct_id), None)
                    if xml_struct:
                        # Get custom ROI name from form input
                        custom_roi_name = request.POST.get(f'roi_name_{struct_id}', '').strip()
                        
                        if not custom_roi_name:
                            errors.append(f'ROI name is required for structure "{xml_struct["name"]}"')
                            continue
                        
                        if len(custom_roi_name) > 16:
                            errors.append(f'ROI name "{custom_roi_name}" exceeds 16 characters for structure "{xml_struct["name"]}"')
                            continue
                        
                        # Check for duplicates
                        if custom_roi_name.lower() in roi_names_map:
                            errors.append(
                                f'Duplicate ROI name detected: "{custom_roi_name}" is used for both '
                                f'"{xml_struct["name"]}" and "{roi_names_map[custom_roi_name.lower()]}". '
                                f'Please use unique names.'
                            )
                        else:
                            roi_names_map[custom_roi_name.lower()] = xml_struct['name']
                
                # Only proceed if no duplicate truncated names
                if not errors:
                    # Now save selected unmapped structures as AdditionalStructures
                    for struct_id in selected_structure_ids:
                        xml_struct = next((s for s in unmapped_structures if s['id'] == struct_id), None)
                        if xml_struct:
                            try:
                                # Get custom ROI name from form
                                original_name = xml_struct['name']
                                roi_label = request.POST.get(f'roi_name_{struct_id}', '').strip()
                                
                                # Create instance and validate before saving
                                additional_struct = AdditionalStructures(
                                    autosegmentation_template=template,
                                    roi_label=roi_label,
                                    rt_roi_interpreted_type=xml_struct['rt_roi_interpreted_type'],
                                    roi_display_color=xml_struct['dicom_color']
                                )
                                
                                # This will trigger the clean() method with duplicate checking
                                additional_struct.full_clean()
                                additional_struct.save()
                                created_additional_count += 1
                                
                                # Log truncation if it occurred
                                if len(original_name) > 16:
                                    logger.info(f'Truncated structure name: "{original_name}" -> "{roi_label}"')
                                
                            except ValidationError as ve:
                                # Collect validation errors
                                if hasattr(ve, 'message_dict'):
                                    for field, field_errors in ve.message_dict.items():
                                        for error in field_errors:
                                            if len(original_name) > 16:
                                                errors.append(f'Structure "{original_name}" (truncated to "{roi_label}"): {error}')
                                            else:
                                                errors.append(f'Structure "{original_name}": {error}')
                                else:
                                    errors.append(f'Structure "{original_name}": {str(ve)}')
                            except Exception as e:
                                errors.append(f'Error saving additional structure "{original_name}": {str(e)}')
                                logger.error(f'Error saving additional structure "{original_name}": {str(e)}', exc_info=True)
            
            if errors:
                for error in errors:
                    messages.error(request, error)
            else:
                success_msg = f'Successfully imported! '
                if created_properties_count or updated_properties_count:
                    success_msg += f'Structure Properties - Created: {created_properties_count}, Updated: {updated_properties_count}. '
                if created_additional_count:
                    success_msg += f'Additional Structures: {created_additional_count}.'
                messages.success(request, success_msg)
                
                # Clear session data
                for key in ['xml_template_data', 'xml_template_mappings', 'mapped_xml_structure_ids', 
                           'wizard_template_id', 'wizard_template_name']:
                    if key in request.session:
                        del request.session[key]
                request.session.modified = True
                
                return redirect('dicom_handler:template_detail', template_id=template.id)
                
        except Exception as e:
            messages.error(request, f'Error saving structures: {str(e)}')
            logger.error(f'Error in additional structures save: {str(e)}', exc_info=True)
    
    context = {
        'template': template,
        'unmapped_structures': unmapped_structures,
        'xml_filename': xml_data.get('xml_filename', 'Unknown'),
    }
    
    return render(request, 'dicom_handler/xml_template_wizard_additional.html', context)


@login_required
@permission_required('dicom_handler.add_structureproperties', raise_exception=True)
@require_http_methods(['POST'])
def xml_template_wizard_save(request):
    """
    Step 4: Save the structure properties to database
    """
    # Get data from session
    xml_data = request.session.get('xml_template_data')
    mappings = request.session.get('xml_template_mappings')
    
    if not xml_data or not mappings:
        messages.error(request, 'No mapping data found. Please complete the previous steps.')
        return redirect('dicom_handler:xml_template_wizard_start')
    
    template = get_object_or_404(AutosegmentationTemplate, id=xml_data['template_id'])
    
    created_count = 0
    updated_count = 0
    errors = []
    
    try:
        with transaction.atomic():
            for mapping in mappings:
                try:
                    autoseg_structure = AutosegmentationStructure.objects.get(
                        id=mapping['autoseg_structure_id']
                    )
                    
                    # Get or create StructureProperties
                    structure_props, created = StructureProperties.objects.get_or_create(
                        autosegmentation_structure=autoseg_structure,
                        defaults={
                            'roi_label': mapping['roi_label'],
                            'rt_roi_interpreted_type': mapping['rt_roi_interpreted_type'],
                            'roi_display_color': mapping['roi_display_color']
                        }
                    )
                    
                    if not created:
                        # Update existing properties
                        structure_props.roi_label = mapping['roi_label']
                        structure_props.rt_roi_interpreted_type = mapping['rt_roi_interpreted_type']
                        structure_props.roi_display_color = mapping['roi_display_color']
                        structure_props.save()
                        updated_count += 1
                    else:
                        created_count += 1
                        
                except AutosegmentationStructure.DoesNotExist:
                    errors.append(f'Autosegmentation structure not found for mapping: {mapping}')
                except Exception as e:
                    errors.append(f'Error saving structure properties: {str(e)}')
                    logger.error(f'Error saving structure properties: {str(e)}', exc_info=True)
        
        if errors:
            for error in errors:
                messages.error(request, error)
        else:
            messages.success(
                request,
                f'Successfully imported structure properties! '
                f'Created: {created_count}, Updated: {updated_count}'
            )
            
            # Clear session data
            if 'xml_template_data' in request.session:
                del request.session['xml_template_data']
            if 'xml_template_mappings' in request.session:
                del request.session['xml_template_mappings']
            if 'wizard_template_id' in request.session:
                del request.session['wizard_template_id']
            if 'wizard_template_name' in request.session:
                del request.session['wizard_template_name']
            request.session.modified = True
            
            return redirect('dicom_handler:template_detail', template_id=template.id)
            
    except Exception as e:
        logger.error(f'Error in transaction: {str(e)}', exc_info=True)
        messages.error(request, f'Error saving mappings: {str(e)}')
    
    return redirect('dicom_handler:xml_template_wizard_review')


@login_required
@permission_required('dicom_handler.add_structureproperties', raise_exception=True)
def xml_template_wizard_cancel(request):
    """
    Cancel the wizard and clear session data
    """
    if 'xml_template_data' in request.session:
        del request.session['xml_template_data']
    if 'xml_template_mappings' in request.session:
        del request.session['xml_template_mappings']
    if 'wizard_template_id' in request.session:
        del request.session['wizard_template_id']
    if 'wizard_template_name' in request.session:
        del request.session['wizard_template_name']
    request.session.modified = True
    
    messages.info(request, 'XML template import wizard cancelled.')
    return redirect('dicom_handler:template_list')


@login_required
def xml_template_search_structures(request):
    """
    AJAX endpoint to search autosegmentation structures for a template
    """
    template_id = request.GET.get('template_id')
    search_query = request.GET.get('q', '').strip()
    
    if not template_id:
        return JsonResponse({'error': 'Template ID required'}, status=400)
    
    try:
        template = AutosegmentationTemplate.objects.get(id=template_id)
        structures = AutosegmentationStructure.objects.filter(
            autosegmentation_model__autosegmentation_template_name=template
        ).select_related('autosegmentation_model')
        
        if search_query:
            structures = structures.filter(name__icontains=search_query)
        
        structures = structures.order_by('name')[:50]  # Limit results
        
        results = [
            {
                'id': str(s.id),
                'name': s.name,
                'model_name': s.autosegmentation_model.name if s.autosegmentation_model else ''
            }
            for s in structures
        ]
        
        return JsonResponse({'structures': results})
        
    except AutosegmentationTemplate.DoesNotExist:
        return JsonResponse({'error': 'Template not found'}, status=404)
    except Exception as e:
        logger.error(f'Error searching structures: {str(e)}', exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)
