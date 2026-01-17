from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.core.paginator import Paginator
from django.db import models
import csv
from .forms import (TemplateCreationForm, RuleGroupForm, RuleSetForm, RuleSetFormSet, RuleFormSet, RuleFormSetHelper, SystemConfigurationForm,
                    RTStructureReviewForm, VOIRatingFormSet, StructurePropertiesForm)
from .models import (SystemConfiguration, AutosegmentationTemplate, AutosegmentationModel, AutosegmentationStructure, 
                     RuleGroup, RuleSet, Rule, DICOMTagType, Patient, DICOMStudy, DICOMSeries, ProcessingStatus, Statistics,
                     RTStructureFileImport, RTStructureFileVOIData, DICOMFileExport, DICOMFileTransferStatus, StructureProperties)
from .vr_validators import VRValidator
import requests
import json
import uuid
import logging

logger = logging.getLogger(__name__)

@login_required
@permission_required('dicom_handler.add_autosegmentationtemplate', raise_exception=True)
def create_template(request):
    """
    View for creating autosegmentation templates
    """
    if request.method == 'POST':
        form = TemplateCreationForm(request.POST)
        if form.is_valid():
            # Store template data in session
            request.session['template_name'] = form.cleaned_data['template_name']
            request.session['template_description'] = form.cleaned_data['template_description']
            request.session.modified = True
            
            # Fetch models from API
            try:
                system_config = SystemConfiguration.get_singleton()
                if not system_config or not system_config.draw_base_url:
                    messages.error(request, 'System configuration not found. Please configure the DRAW API settings.')
                    return render(request, 'dicom_handler/create_template.html', {'form': form})
                
                api_url = f"{system_config.draw_base_url.rstrip('/')}/api/models/"
                headers = {}
                if system_config.draw_bearer_token:
                    headers['Authorization'] = f"Bearer {system_config.draw_bearer_token}"
                
                response = requests.get(api_url, headers=headers, timeout=30)
                response.raise_for_status()
                
                api_data = response.json()
                
                # Flatten all structures from all models for pagination and search
                all_structures = []
                for model in api_data:
                    if 'modelmap' in model and model['modelmap']:
                        for structure in model['modelmap']:
                            structure_data = {
                                'id': structure.get('id'),
                                'mapid': structure.get('mapid'),
                                'map_tg263_primary_name': structure.get('map_tg263_primary_name'),
                                'Major_Category': structure.get('Major_Category'),
                                'Anatomic_Group': structure.get('Anatomic_Group'),
                                'Description': structure.get('Description'),
                                'delineation_modality': structure.get('delineation_modality'),
                                'median_dice_score': structure.get('median_dice_score'),
                                'model_id': model.get('model_id'),
                                'model_name': model.get('model_name'),
                                'model_config': model.get('model_config'),
                                'model_trainer_name': model.get('model_trainer_name'),
                                'model_postprocess': model.get('model_postprocess')
                            }
                            all_structures.append(structure_data)
                
                # Get unique values for filter dropdowns from all structures
                all_categories = sorted(list(set(s.get('Major_Category', '') for s in all_structures if s.get('Major_Category'))))
                all_anatomic_regions = sorted(list(set(s.get('Anatomic_Group', '') for s in all_structures if s.get('Anatomic_Group'))))
                all_model_names = sorted(list(set(s.get('model_name', '') for s in all_structures if s.get('model_name'))))
                
                # Handle search and filters
                search_query = request.GET.get('search', '').strip()
                category_filter = request.GET.get('category', '').strip()
                anatomic_filter = request.GET.get('anatomic', '').strip()
                model_filter = request.GET.get('model', '').strip()
                
                filtered_structures = []
                for structure in all_structures:
                    # Apply search filter
                    search_match = True
                    if search_query:
                        search_match = (search_query.lower() in str(structure.get('map_tg263_primary_name', '')).lower() or
                                       search_query.lower() in str(structure.get('Major_Category', '')).lower() or
                                       search_query.lower() in str(structure.get('Anatomic_Group', '')).lower() or
                                       search_query.lower() in str(structure.get('Description', '')).lower() or
                                       search_query.lower() in str(structure.get('model_name', '')).lower())
                    
                    # Apply category filter
                    category_match = True
                    if category_filter:
                        category_match = str(structure.get('Major_Category', '')).lower() == category_filter.lower()
                    
                    # Apply anatomic region filter
                    anatomic_match = True
                    if anatomic_filter:
                        anatomic_match = str(structure.get('Anatomic_Group', '')).lower() == anatomic_filter.lower()
                    
                    # Apply model name filter
                    model_match = True
                    if model_filter:
                        model_match = str(structure.get('model_name', '')).lower() == model_filter.lower()
                    
                    # Include structure if all filters match
                    if search_match and category_match and anatomic_match and model_match:
                        filtered_structures.append(structure)
                
                all_structures = filtered_structures
                
                # Handle pagination
                page_number = request.GET.get('page', 1)
                paginator = Paginator(all_structures, 25)  # 25 structures per page
                page_obj = paginator.get_page(page_number)
                
                # Clear any existing selections when loading the form fresh
                request.session['selected_structures'] = []
                selected_structures = []
                
                # Add select_models view function
                return redirect('dicom_handler:select_models')
                
            except requests.RequestException as e:
                messages.error(request, f'Error fetching models from API: {str(e)}')
                return render(request, 'dicom_handler/create_template.html', {'form': form})
            except Exception as e:
                messages.error(request, f'Unexpected error: {str(e)}')
                return render(request, 'dicom_handler/create_template.html', {'form': form})
    else:
        form = TemplateCreationForm()
    
    return render(request, 'dicom_handler/create_template.html', {'form': form})

@login_required
def select_models(request):
    """
    View for selecting models and structures for template creation
    """
    # Get template data from session
    template_name = request.session.get('template_name', '')
    template_description = request.session.get('template_description', '')
    
    if not template_name:
        messages.error(request, 'Please create a template first.')
        return redirect('dicom_handler:create_template')
    
    try:
        system_config = SystemConfiguration.get_singleton()
        if not system_config or not system_config.draw_base_url:
            messages.error(request, 'System configuration not found. Please configure the DRAW API settings.')
            return redirect('dicom_handler:create_template')
        
        api_url = f"{system_config.draw_base_url.rstrip('/')}/api/models/"
        headers = {}
        if system_config.draw_bearer_token:
            headers['Authorization'] = f"Bearer {system_config.draw_bearer_token}"
        
        response = requests.get(api_url, headers=headers, timeout=30)
        response.raise_for_status()
        
        api_data = response.json()
        
        # Flatten all structures from all models for pagination and search
        all_structures = []
        for model in api_data:
            if 'modelmap' in model and model['modelmap']:
                for structure in model['modelmap']:
                    structure_data = {
                        'id': structure.get('id'),
                        'mapid': structure.get('mapid'),
                        'map_tg263_primary_name': structure.get('map_tg263_primary_name'),
                        'Major_Category': structure.get('Major_Category'),
                        'Anatomic_Group': structure.get('Anatomic_Group'),
                        'Description': structure.get('Description'),
                        'delineation_modality': structure.get('delineation_modality'),
                        'median_dice_score': structure.get('median_dice_score'),
                        'model_id': model.get('model_id'),
                        'model_name': model.get('model_name'),
                        'model_config': model.get('model_config'),
                        'model_trainer_name': model.get('model_trainer_name'),
                        'model_postprocess': model.get('model_postprocess')
                    }
                    all_structures.append(structure_data)
        
        # Get unique values for filter dropdowns from all structures
        all_categories = sorted(list(set(s.get('Major_Category', '') for s in all_structures if s.get('Major_Category'))))
        all_anatomic_regions = sorted(list(set(s.get('Anatomic_Group', '') for s in all_structures if s.get('Anatomic_Group'))))
        all_model_names = sorted(list(set(s.get('model_name', '') for s in all_structures if s.get('model_name'))))
        
        # Handle search and filters
        search_query = request.GET.get('search', '').strip()
        category_filter = request.GET.get('category', '').strip()
        anatomic_filter = request.GET.get('anatomic_region', '').strip()
        model_filter = request.GET.get('model_name', '').strip()
        
        filtered_structures = []
        for structure in all_structures:
            # Apply search filter
            search_match = True
            if search_query:
                search_match = (search_query.lower() in str(structure.get('map_tg263_primary_name', '')).lower() or
                               search_query.lower() in str(structure.get('Major_Category', '')).lower() or
                               search_query.lower() in str(structure.get('Anatomic_Group', '')).lower() or
                               search_query.lower() in str(structure.get('Description', '')).lower() or
                               search_query.lower() in str(structure.get('model_name', '')).lower())
            
            # Apply category filter
            category_match = True
            if category_filter:
                category_match = str(structure.get('Major_Category', '')).lower() == category_filter.lower()
            
            # Apply anatomic region filter
            anatomic_match = True
            if anatomic_filter:
                anatomic_match = str(structure.get('Anatomic_Group', '')).lower() == anatomic_filter.lower()
            
            # Apply model name filter
            model_match = True
            if model_filter:
                model_match = str(structure.get('model_name', '')).lower() == model_filter.lower()
            
            # Include structure if all filters match
            if search_match and category_match and anatomic_match and model_match:
                filtered_structures.append(structure)
        
        all_structures = filtered_structures
        
        # Handle pagination
        page_number = request.GET.get('page', 1)
        paginator = Paginator(all_structures, 25)  # 25 structures per page
        page_obj = paginator.get_page(page_number)
        
        # Get existing selections from session
        selected_structures = request.session.get('selected_structures', [])
        
        return render(request, 'dicom_handler/select_models.html', {
            'page_obj': page_obj,
            'template_name': template_name,
            'template_description': template_description,
            'selected_structures': json.dumps(selected_structures),
            'system_config': system_config,
            'search_query': search_query,
            'category_filter': category_filter,
            'anatomic_filter': anatomic_filter,
            'model_filter': model_filter,
            'categories': all_categories,
            'anatomic_regions': all_anatomic_regions,
            'model_names': all_model_names
        })
        
    except requests.RequestException as e:
        messages.error(request, f'Error fetching models from API: {str(e)}')
        return redirect('dicom_handler:create_template')
    except Exception as e:
        messages.error(request, f'Unexpected error: {str(e)}')
        return redirect('dicom_handler:create_template')

@login_required
def save_selections(request):
    """
    AJAX endpoint to save selected structures in session
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Only POST method allowed'})
    
    try:
        data = json.loads(request.body)
        selected_structures = data.get('selected_structures', [])
        
        # Store selections in session
        request.session['selected_structures'] = selected_structures
        request.session.modified = True
        
        return JsonResponse({
            'success': True, 
            'count': len(selected_structures),
            'message': f'{len(selected_structures)} structures selected'
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
def update_selections(request):
    """
    AJAX endpoint to update selected structures in session
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Only POST method allowed'})
    
    try:
        data = json.loads(request.body)
        selected_structures = data.get('selected_structures', [])
        
        # Store selections in session
        request.session['selected_structures'] = selected_structures
        request.session.modified = True
        
        return JsonResponse({
            'success': True, 
            'count': len(selected_structures),
            'message': f'{len(selected_structures)} structures selected'
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
@permission_required('dicom_handler.add_autosegmentationtemplate', raise_exception=True)
def save_template(request):
    """
    AJAX endpoint to save the selected template data
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Only POST method allowed'})
    
    try:
        data = json.loads(request.body)
        
        # Get template name and description from session (from first step)
        template_name = request.session.get('template_name')
        template_description = request.session.get('template_description', '')
        
        # Fallback to data from request if not in session
        if not template_name:
            template_name = data.get('template_name')
            template_description = data.get('template_description')
        
        # Get selected structures from session
        selected_structures = request.session.get('selected_structures', [])
        
        if not template_name:
            return JsonResponse({'success': False, 'error': 'Template name is required'})
        
        if not selected_structures:
            return JsonResponse({'success': False, 'error': 'No structures selected. Please select at least one structure.'})
        
        # Create the template
        template = AutosegmentationTemplate.objects.create(
            id=uuid.uuid4(),
            template_name=template_name,
            template_description=template_description or ''
        )
        
        # Debug logging
        print(f"Template name: {template_name}")
        print(f"Selected structures count: {len(selected_structures)}")
        print(f"First structure sample: {selected_structures[0] if selected_structures else 'None'}")
        
        # Group structures by model
        models_dict = {}
        for structure in selected_structures:
            model_id = structure.get('model_id')
            if not model_id:
                print(f"Warning: Structure missing model_id: {structure}")
                continue
                
            if model_id not in models_dict:
                models_dict[model_id] = {
                    'model_id': structure.get('model_id'),
                    'model_name': structure.get('model_name'),
                    'model_config': structure.get('model_config'),
                    'model_trainer_name': structure.get('model_trainer_name'),
                    'model_postprocess': structure.get('model_postprocess'),
                    'structures': []
                }
            models_dict[model_id]['structures'].append(structure)
        
        # Save models and their structures
        for model_data in models_dict.values():
            try:
                model = AutosegmentationModel.objects.create(
                    id=uuid.uuid4(),
                    autosegmentation_template_name=template,
                    model_id=model_data.get('model_id'),
                    name=model_data.get('model_name', ''),
                    config=model_data.get('model_config', ''),
                    trainer_name=model_data.get('model_trainer_name', ''),
                    postprocess=model_data.get('model_postprocess', '')
                )
                print(f"Created model: {model.name} with ID: {model.model_id}")
                
                # Save structures for this model
                for structure_data in model_data.get('structures', []):
                    # Handle both dict and string cases
                    if isinstance(structure_data, str):
                        # If it's a string (structure ID), we need to find the full data
                        structure_id = structure_data
                        # Try to get from window.structureData if available, otherwise use minimal data
                        structure = AutosegmentationStructure.objects.create(
                            id=uuid.uuid4(),
                            autosegmentation_model=model,
                            map_id=structure_id,
                            name=f'Structure {structure_id}'
                        )
                    else:
                        # It's a dict with full data
                        structure = AutosegmentationStructure.objects.create(
                            id=uuid.uuid4(),
                            autosegmentation_model=model,
                            map_id=structure_data.get('mapid') or structure_data.get('id'),
                            name=structure_data.get('map_tg263_primary_name', '')
                        )
                    print(f"Created structure: {structure.name} with map_id: {structure.map_id}")
                    
            except Exception as model_error:
                print(f"Error creating model {model_data.get('model_name')}: {str(model_error)}")
                return JsonResponse({'success': False, 'error': f'Error saving model data: {str(model_error)}'})
        
        # Clear all template data from session after successful creation
        request.session.pop('selected_structures', None)
        request.session.pop('template_name', None)
        request.session.pop('template_description', None)
        request.session.modified = True
        
        return JsonResponse({
            'success': True, 
            'message': 'Template saved successfully!',
            'template_id': str(template.id)
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


# RuleSet Management Views

@login_required
@permission_required('dicom_handler.view_ruleset', raise_exception=True)
def ruleset_list(request):
    """
    View to list all rulegroups with their rulesets
    """
    from .models import RuleGroup
    
    rulegroups = RuleGroup.objects.all().select_related('associated_autosegmentation_template').order_by('-created_at')
    
    # Add ruleset and rule counts for each rulegroup
    for rulegroup in rulegroups:
        rulesets = RuleSet.objects.filter(rulegroup=rulegroup).order_by('rulset_order')
        rulegroup.rulesets = rulesets
        rulegroup.ruleset_count = rulesets.count()
        
        # Count total rules across all rulesets
        total_rules = 0
        for ruleset in rulesets:
            total_rules += Rule.objects.filter(ruleset=ruleset).count()
        rulegroup.total_rules = total_rules
    
    return render(request, 'dicom_handler/rulegroup_list.html', {
        'rulegroups': rulegroups
    })

@login_required
@permission_required('dicom_handler.add_ruleset', raise_exception=True)
def rulegroup_create(request):
    """
    View to create a new rulegroup with multiple rulesets and inline rules
    Handles dynamic form submission with multiple rulesets
    """
    from .models import RuleGroup, DICOMTagType
    
    # Get template_id from URL parameter if provided
    template_id = request.GET.get('template')
    rulegroup_initial = {}
    
    if template_id:
        try:
            template = AutosegmentationTemplate.objects.get(id=template_id)
            rulegroup_initial['associated_autosegmentation_template'] = template
        except AutosegmentationTemplate.DoesNotExist:
            messages.warning(request, 'The specified template was not found.')
    
    if request.method == 'POST':
        rulegroup_form = RuleGroupForm(request.POST)
        
        if rulegroup_form.is_valid():
            # Create the rulegroup first
            rulegroup = rulegroup_form.save(commit=False)
            rulegroup.id = uuid.uuid4()
            rulegroup.save()
            
            # Parse the POST data to extract rulesets and rules
            # Field naming: ruleset_name___0, ruleset_name___1, etc.
            # Rule naming: rule_order___0___0, dicom_tag_type___0___0, etc.
            
            # Debug: Log POST data
            import logging
            logger = logging.getLogger(__name__)
            logger.info(f"POST data keys: {[k for k in request.POST.keys() if k.startswith(('ruleset_', 'rule_'))]}")
            
            rulesets_data = {}
            for key, value in request.POST.items():
                if key.startswith('ruleset_name___'):
                    ruleset_idx = key.split('___')[1]
                    if ruleset_idx not in rulesets_data:
                        rulesets_data[ruleset_idx] = {'rules': {}}
                    rulesets_data[ruleset_idx]['name'] = value
                elif key.startswith('ruleset_combination_type___'):
                    ruleset_idx = key.split('___')[1]
                    if ruleset_idx not in rulesets_data:
                        rulesets_data[ruleset_idx] = {'rules': {}}
                    rulesets_data[ruleset_idx]['combination_type'] = value
                elif key.startswith('rulset_order___'):
                    ruleset_idx = key.split('___')[1]
                    if ruleset_idx not in rulesets_data:
                        rulesets_data[ruleset_idx] = {'rules': {}}
                    rulesets_data[ruleset_idx]['order'] = value
                elif key.startswith('ruleset_description___'):
                    ruleset_idx = key.split('___')[1]
                    if ruleset_idx not in rulesets_data:
                        rulesets_data[ruleset_idx] = {'rules': {}}
                    rulesets_data[ruleset_idx]['description'] = value
                elif key.startswith('rule_order___'):
                    parts = key.split('___')
                    ruleset_idx = parts[1]
                    rule_idx = parts[2]
                    if ruleset_idx not in rulesets_data:
                        rulesets_data[ruleset_idx] = {'rules': {}}
                    if rule_idx not in rulesets_data[ruleset_idx]['rules']:
                        rulesets_data[ruleset_idx]['rules'][rule_idx] = {}
                    rulesets_data[ruleset_idx]['rules'][rule_idx]['order'] = value
                elif key.startswith('dicom_tag_type___'):
                    parts = key.split('___')
                    ruleset_idx = parts[1]
                    rule_idx = parts[2]
                    if ruleset_idx not in rulesets_data:
                        rulesets_data[ruleset_idx] = {'rules': {}}
                    if rule_idx not in rulesets_data[ruleset_idx]['rules']:
                        rulesets_data[ruleset_idx]['rules'][rule_idx] = {}
                    rulesets_data[ruleset_idx]['rules'][rule_idx]['tag_type'] = value
                elif key.startswith('operator_type___'):
                    parts = key.split('___')
                    ruleset_idx = parts[1]
                    rule_idx = parts[2]
                    if ruleset_idx not in rulesets_data:
                        rulesets_data[ruleset_idx] = {'rules': {}}
                    if rule_idx not in rulesets_data[ruleset_idx]['rules']:
                        rulesets_data[ruleset_idx]['rules'][rule_idx] = {}
                    rulesets_data[ruleset_idx]['rules'][rule_idx]['operator'] = value
                elif key.startswith('tag_value_to_evaluate___'):
                    parts = key.split('___')
                    ruleset_idx = parts[1]
                    rule_idx = parts[2]
                    if ruleset_idx not in rulesets_data:
                        rulesets_data[ruleset_idx] = {'rules': {}}
                    if rule_idx not in rulesets_data[ruleset_idx]['rules']:
                        rulesets_data[ruleset_idx]['rules'][rule_idx] = {}
                    rulesets_data[ruleset_idx]['rules'][rule_idx]['value'] = value
                elif key.startswith('rule_combination_type___'):
                    parts = key.split('___')
                    ruleset_idx = parts[1]
                    rule_idx = parts[2]
                    if ruleset_idx not in rulesets_data:
                        rulesets_data[ruleset_idx] = {'rules': {}}
                    if rule_idx not in rulesets_data[ruleset_idx]['rules']:
                        rulesets_data[ruleset_idx]['rules'][rule_idx] = {}
                    rulesets_data[ruleset_idx]['rules'][rule_idx]['combination'] = value
            
            # Create rulesets and rules
            for ruleset_idx, ruleset_data in rulesets_data.items():
                if 'name' in ruleset_data:  # Only process if we have a name
                    ruleset = RuleSet()
                    ruleset.id = uuid.uuid4()
                    ruleset.rulegroup = rulegroup
                    ruleset.ruleset_name = ruleset_data.get('name', '')
                    ruleset.ruleset_combination_type = ruleset_data.get('combination_type', 'AND')
                    ruleset.rulset_order = int(ruleset_data.get('order', 1))
                    ruleset.ruleset_description = ruleset_data.get('description', '')
                    ruleset.save()
                    
                    # Create rules for this ruleset
                    for rule_idx, rule_data in ruleset_data.get('rules', {}).items():
                        if 'tag_type' in rule_data:  # Only process if we have a tag
                            rule = Rule()
                            rule.id = uuid.uuid4()
                            rule.ruleset = ruleset
                            rule.rule_order = int(rule_data.get('order', 1))
                            rule.dicom_tag_type = DICOMTagType.objects.get(id=rule_data['tag_type'])
                            rule.operator_type = rule_data.get('operator', 'EQUALS')
                            rule.tag_value_to_evaluate = rule_data.get('value', '')
                            rule.rule_combination_type = rule_data.get('combination', 'AND')
                            rule.save()
            
            if len(rulesets_data) == 0:
                messages.warning(request, f'Rule Group "{rulegroup.rulegroup_name}" created, but no RuleSets were added. Please click "Add RuleSet" button to add rulesets and rules.')
            else:
                messages.success(request, f'Rule Group "{rulegroup.rulegroup_name}" with {len(rulesets_data)} RuleSet(s) created successfully!')
            return redirect('dicom_handler:ruleset_list')
        else:
            messages.error(request, 'Please correct the errors in the rule group form.')
    else:
        rulegroup_form = RuleGroupForm(initial=rulegroup_initial)
    
    return render(request, 'dicom_handler/rulegroup_create_multi.html', {
        'rulegroup_form': rulegroup_form,
    })

@login_required
@permission_required('dicom_handler.view_ruleset', raise_exception=True)
def rulegroup_detail(request, rulegroup_id):
    """
    View to display detailed information about a specific rulegroup with all its rulesets and rules
    """
    from .models import RuleGroup
    
    rulegroup = get_object_or_404(RuleGroup, id=rulegroup_id)
    rulesets = RuleSet.objects.filter(rulegroup=rulegroup).order_by('rulset_order')
    
    # Get rules for each ruleset
    rulesets_with_rules = []
    for ruleset in rulesets:
        rules = Rule.objects.filter(ruleset=ruleset).select_related('dicom_tag_type').order_by('rule_order')
        rulesets_with_rules.append({
            'ruleset': ruleset,
            'rules': rules
        })
    
    return render(request, 'dicom_handler/rulegroup_detail.html', {
        'rulegroup': rulegroup,
        'rulesets_with_rules': rulesets_with_rules
    })

@login_required
@permission_required('dicom_handler.change_ruleset', raise_exception=True)
def rulegroup_edit(request, rulegroup_id):
    """
    View to edit an existing rulegroup with all its rulesets and rules
    """
    from .models import RuleGroup
    
    rulegroup = get_object_or_404(RuleGroup, id=rulegroup_id)
    
    if request.method == 'POST':
        rulegroup_form = RuleGroupForm(request.POST, instance=rulegroup)
        
        if rulegroup_form.is_valid():
            rulegroup_form.save()
            
            # Parse the POST data to extract rulesets and rules
            import logging
            logger = logging.getLogger(__name__)
            logger.info(f"POST data keys: {[k for k in request.POST.keys() if k.startswith(('ruleset_', 'rule_'))]}")
            
            # Get existing rulesets to track deletions
            existing_ruleset_ids = set(str(rs.id) for rs in RuleSet.objects.filter(rulegroup=rulegroup))
            submitted_ruleset_ids = set()
            
            rulesets_data = {}
            for key, value in request.POST.items():
                if key.startswith('ruleset_id___'):
                    ruleset_idx = key.split('___')[1]
                    if ruleset_idx not in rulesets_data:
                        rulesets_data[ruleset_idx] = {'rules': {}}
                    rulesets_data[ruleset_idx]['id'] = value
                    submitted_ruleset_ids.add(value)
                elif key.startswith('ruleset_name___'):
                    ruleset_idx = key.split('___')[1]
                    if ruleset_idx not in rulesets_data:
                        rulesets_data[ruleset_idx] = {'rules': {}}
                    rulesets_data[ruleset_idx]['name'] = value
                elif key.startswith('ruleset_combination_type___'):
                    ruleset_idx = key.split('___')[1]
                    if ruleset_idx not in rulesets_data:
                        rulesets_data[ruleset_idx] = {'rules': {}}
                    rulesets_data[ruleset_idx]['combination_type'] = value
                elif key.startswith('rulset_order___'):
                    ruleset_idx = key.split('___')[1]
                    if ruleset_idx not in rulesets_data:
                        rulesets_data[ruleset_idx] = {'rules': {}}
                    rulesets_data[ruleset_idx]['order'] = value
                elif key.startswith('ruleset_description___'):
                    ruleset_idx = key.split('___')[1]
                    if ruleset_idx not in rulesets_data:
                        rulesets_data[ruleset_idx] = {'rules': {}}
                    rulesets_data[ruleset_idx]['description'] = value
                elif key.startswith('rule_id___'):
                    parts = key.split('___')
                    ruleset_idx = parts[1]
                    rule_idx = parts[2]
                    if ruleset_idx not in rulesets_data:
                        rulesets_data[ruleset_idx] = {'rules': {}}
                    if rule_idx not in rulesets_data[ruleset_idx]['rules']:
                        rulesets_data[ruleset_idx]['rules'][rule_idx] = {}
                    rulesets_data[ruleset_idx]['rules'][rule_idx]['id'] = value
                elif key.startswith('rule_order___'):
                    parts = key.split('___')
                    ruleset_idx = parts[1]
                    rule_idx = parts[2]
                    if ruleset_idx not in rulesets_data:
                        rulesets_data[ruleset_idx] = {'rules': {}}
                    if rule_idx not in rulesets_data[ruleset_idx]['rules']:
                        rulesets_data[ruleset_idx]['rules'][rule_idx] = {}
                    rulesets_data[ruleset_idx]['rules'][rule_idx]['order'] = value
                elif key.startswith('dicom_tag_type___'):
                    parts = key.split('___')
                    ruleset_idx = parts[1]
                    rule_idx = parts[2]
                    if ruleset_idx not in rulesets_data:
                        rulesets_data[ruleset_idx] = {'rules': {}}
                    if rule_idx not in rulesets_data[ruleset_idx]['rules']:
                        rulesets_data[ruleset_idx]['rules'][rule_idx] = {}
                    rulesets_data[ruleset_idx]['rules'][rule_idx]['tag_type'] = value
                elif key.startswith('operator_type___'):
                    parts = key.split('___')
                    ruleset_idx = parts[1]
                    rule_idx = parts[2]
                    if ruleset_idx not in rulesets_data:
                        rulesets_data[ruleset_idx] = {'rules': {}}
                    if rule_idx not in rulesets_data[ruleset_idx]['rules']:
                        rulesets_data[ruleset_idx]['rules'][rule_idx] = {}
                    rulesets_data[ruleset_idx]['rules'][rule_idx]['operator'] = value
                elif key.startswith('tag_value_to_evaluate___'):
                    parts = key.split('___')
                    ruleset_idx = parts[1]
                    rule_idx = parts[2]
                    if ruleset_idx not in rulesets_data:
                        rulesets_data[ruleset_idx] = {'rules': {}}
                    if rule_idx not in rulesets_data[ruleset_idx]['rules']:
                        rulesets_data[ruleset_idx]['rules'][rule_idx] = {}
                    rulesets_data[ruleset_idx]['rules'][rule_idx]['value'] = value
                elif key.startswith('rule_combination_type___'):
                    parts = key.split('___')
                    ruleset_idx = parts[1]
                    rule_idx = parts[2]
                    if ruleset_idx not in rulesets_data:
                        rulesets_data[ruleset_idx] = {'rules': {}}
                    if rule_idx not in rulesets_data[ruleset_idx]['rules']:
                        rulesets_data[ruleset_idx]['rules'][rule_idx] = {}
                    rulesets_data[ruleset_idx]['rules'][rule_idx]['combination'] = value
            
            # Delete rulesets that were removed
            rulesets_to_delete = existing_ruleset_ids - submitted_ruleset_ids
            if rulesets_to_delete:
                RuleSet.objects.filter(id__in=rulesets_to_delete).delete()
            
            # Create or update rulesets and rules
            for ruleset_idx, ruleset_data in rulesets_data.items():
                if 'name' in ruleset_data:
                    ruleset_id = ruleset_data.get('id')
                    if ruleset_id and ruleset_id != 'new':
                        # Update existing ruleset
                        try:
                            ruleset = RuleSet.objects.get(id=ruleset_id)
                            ruleset.ruleset_name = ruleset_data.get('name', '')
                            ruleset.ruleset_combination_type = ruleset_data.get('combination_type', 'AND')
                            ruleset.rulset_order = int(ruleset_data.get('order', 1))
                            ruleset.ruleset_description = ruleset_data.get('description', '')
                            ruleset.save()
                        except RuleSet.DoesNotExist:
                            # Create new if not found
                            ruleset = RuleSet()
                            ruleset.id = uuid.uuid4()
                            ruleset.rulegroup = rulegroup
                            ruleset.ruleset_name = ruleset_data.get('name', '')
                            ruleset.ruleset_combination_type = ruleset_data.get('combination_type', 'AND')
                            ruleset.rulset_order = int(ruleset_data.get('order', 1))
                            ruleset.ruleset_description = ruleset_data.get('description', '')
                            ruleset.save()
                    else:
                        # Create new ruleset
                        ruleset = RuleSet()
                        ruleset.id = uuid.uuid4()
                        ruleset.rulegroup = rulegroup
                        ruleset.ruleset_name = ruleset_data.get('name', '')
                        ruleset.ruleset_combination_type = ruleset_data.get('combination_type', 'AND')
                        ruleset.rulset_order = int(ruleset_data.get('order', 1))
                        ruleset.ruleset_description = ruleset_data.get('description', '')
                        ruleset.save()
                    
                    # Get existing rules for this ruleset
                    existing_rule_ids = set(str(r.id) for r in Rule.objects.filter(ruleset=ruleset))
                    submitted_rule_ids = set()
                    
                    # Create or update rules for this ruleset
                    for rule_idx, rule_data in ruleset_data.get('rules', {}).items():
                        if 'tag_type' in rule_data:
                            rule_id = rule_data.get('id')
                            if rule_id:
                                submitted_rule_ids.add(rule_id)
                            
                            if rule_id and rule_id != 'new':
                                # Update existing rule
                                try:
                                    rule = Rule.objects.get(id=rule_id)
                                    rule.rule_order = int(rule_data.get('order', 1))
                                    rule.dicom_tag_type = DICOMTagType.objects.get(id=rule_data['tag_type'])
                                    rule.operator_type = rule_data.get('operator', 'EQUALS')
                                    rule.tag_value_to_evaluate = rule_data.get('value', '')
                                    rule.rule_combination_type = rule_data.get('combination', 'AND')
                                    rule.save()
                                except Rule.DoesNotExist:
                                    # Create new if not found
                                    rule = Rule()
                                    rule.id = uuid.uuid4()
                                    rule.ruleset = ruleset
                                    rule.rule_order = int(rule_data.get('order', 1))
                                    rule.dicom_tag_type = DICOMTagType.objects.get(id=rule_data['tag_type'])
                                    rule.operator_type = rule_data.get('operator', 'EQUALS')
                                    rule.tag_value_to_evaluate = rule_data.get('value', '')
                                    rule.rule_combination_type = rule_data.get('combination', 'AND')
                                    rule.save()
                            else:
                                # Create new rule
                                rule = Rule()
                                rule.id = uuid.uuid4()
                                rule.ruleset = ruleset
                                rule.rule_order = int(rule_data.get('order', 1))
                                rule.dicom_tag_type = DICOMTagType.objects.get(id=rule_data['tag_type'])
                                rule.operator_type = rule_data.get('operator', 'EQUALS')
                                rule.tag_value_to_evaluate = rule_data.get('value', '')
                                rule.rule_combination_type = rule_data.get('combination', 'AND')
                                rule.save()
                    
                    # Delete rules that were removed
                    rules_to_delete = existing_rule_ids - submitted_rule_ids
                    if rules_to_delete:
                        Rule.objects.filter(id__in=rules_to_delete).delete()
            
            messages.success(request, f'Rule Group "{rulegroup.rulegroup_name}" updated successfully!')
            return redirect('dicom_handler:rulegroup_detail', rulegroup_id=rulegroup.id)
        else:
            messages.error(request, 'Please correct the errors in the rule group form.')
    else:
        rulegroup_form = RuleGroupForm(instance=rulegroup)
    
    # Get existing rulesets and rules
    import json
    rulesets = RuleSet.objects.filter(rulegroup=rulegroup).order_by('rulset_order')
    rulesets_with_rules = []
    rulesets_json = []
    
    for ruleset in rulesets:
        rules = Rule.objects.filter(ruleset=ruleset).select_related('dicom_tag_type').order_by('rule_order')
        rulesets_with_rules.append({
            'ruleset': ruleset,
            'rules': list(rules)
        })
        
        # Create JSON-serializable version
        rules_json = []
        for rule in rules:
            rules_json.append({
                'id': str(rule.id),
                'rule_order': rule.rule_order,
                'dicom_tag_type': {
                    'id': str(rule.dicom_tag_type.id),
                    'tag_name': rule.dicom_tag_type.tag_name
                },
                'operator_type': rule.operator_type,
                'tag_value_to_evaluate': rule.tag_value_to_evaluate,
                'rule_combination_type': rule.rule_combination_type
            })
        
        rulesets_json.append({
            'ruleset': {
                'id': str(ruleset.id),
                'ruleset_name': ruleset.ruleset_name,
                'ruleset_combination_type': ruleset.ruleset_combination_type,
                'rulset_order': ruleset.rulset_order,
                'ruleset_description': ruleset.ruleset_description or ''
            },
            'rules': rules_json
        })
    
    return render(request, 'dicom_handler/rulegroup_edit.html', {
        'rulegroup_form': rulegroup_form,
        'rulegroup': rulegroup,
        'rulesets_with_rules': rulesets_with_rules,
        'rulesets_json': json.dumps(rulesets_json)
    })

@login_required
@permission_required('dicom_handler.view_ruleset', raise_exception=True)
def ruleset_detail(request, ruleset_id):
    """
    View to display detailed information about a specific ruleset
    """
    ruleset = get_object_or_404(RuleSet, id=ruleset_id)
    rules = Rule.objects.filter(ruleset=ruleset).select_related('dicom_tag_type').order_by('rule_order')
    rulegroup = ruleset.rulegroup
    
    return render(request, 'dicom_handler/ruleset_detail.html', {
        'ruleset': ruleset,
        'rules': rules,
        'rulegroup': rulegroup
    })

@login_required
@permission_required('dicom_handler.change_ruleset', raise_exception=True)
def ruleset_edit(request, ruleset_id):
    """
    View to edit an existing ruleset
    """
    ruleset = get_object_or_404(RuleSet, id=ruleset_id)
    rulegroup = ruleset.rulegroup
    
    if request.method == 'POST':
        rulegroup_form = RuleGroupForm(request.POST, instance=rulegroup) if rulegroup else None
        ruleset_form = RuleSetForm(request.POST, instance=ruleset)
        formset = RuleFormSet(request.POST, instance=ruleset)
        
        forms_valid = ruleset_form.is_valid() and formset.is_valid()
        if rulegroup_form:
            forms_valid = forms_valid and rulegroup_form.is_valid()
        
        if forms_valid:
            if rulegroup_form:
                rulegroup_form.save()
            ruleset_form.save()
            formset.save()
            
            messages.success(request, f'RuleSet "{ruleset.ruleset_name}" updated successfully!')
            return redirect('dicom_handler:ruleset_detail', ruleset_id=ruleset.id)
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        rulegroup_form = RuleGroupForm(instance=rulegroup) if rulegroup else None
        ruleset_form = RuleSetForm(instance=ruleset)
        formset = RuleFormSet(instance=ruleset)
    
    # Add helper to formset for Crispy Forms
    formset_helper = RuleFormSetHelper()
    
    return render(request, 'dicom_handler/ruleset_edit.html', {
        'rulegroup_form': rulegroup_form,
        'form': ruleset_form,
        'formset': formset,
        'formset_helper': formset_helper,
        'ruleset': ruleset,
        'rulegroup': rulegroup
    })

@login_required
@permission_required('dicom_handler.delete_ruleset', raise_exception=True)
def ruleset_delete(request, ruleset_id):
    """
    View to delete a ruleset
    """
    ruleset = get_object_or_404(RuleSet, id=ruleset_id)
    
    if request.method == 'POST':
        ruleset_name = ruleset.ruleset_name
        ruleset.delete()
        messages.success(request, f'RuleSet "{ruleset_name}" deleted successfully!')
        return redirect('dicom_handler:ruleset_list')
    
    return render(request, 'dicom_handler/ruleset_confirm_delete.html', {
        'ruleset': ruleset
    })

@login_required
@permission_required('dicom_handler.view_autosegmentationtemplate', raise_exception=True)
def template_list(request):
    """
    View to display all templates created by the user
    """
    templates = AutosegmentationTemplate.objects.all().order_by('-created_at')
    
    # Add structure count and related ruleset for each template
    for template in templates:
        structure_count = AutosegmentationStructure.objects.filter(
            autosegmentation_model__autosegmentation_template_name=template
        ).count()
        model_count = AutosegmentationModel.objects.filter(
            autosegmentation_template_name=template
        ).count()
        # Get related rulegroup
        related_rulegroup = RuleGroup.objects.filter(
            associated_autosegmentation_template=template
        ).first()
        
        template.structure_count = structure_count
        template.model_count = model_count
        template.related_rulegroup = related_rulegroup
    
    return render(request, 'dicom_handler/template_list.html', {
        'templates': templates
    })

@login_required
@permission_required('dicom_handler.view_autosegmentationtemplate', raise_exception=True)
def template_detail(request, template_id):
    """
    View to display detailed information about a specific template
    """
    try:
        template = AutosegmentationTemplate.objects.get(id=template_id)
        models = AutosegmentationModel.objects.filter(
            autosegmentation_template_name=template
        ).prefetch_related(
            'autosegmentationstructure_set',
            'autosegmentationstructure_set__structureproperties'
        )
        
        # Parse color values for each structure
        for model in models:
            for structure in model.autosegmentationstructure_set.all():
                try:
                    if hasattr(structure, 'structureproperties') and structure.structureproperties.roi_display_color:
                        color_parts = structure.structureproperties.roi_display_color.split('\\')
                        if len(color_parts) == 3:
                            structure.color_rgb = f"{color_parts[0]}, {color_parts[1]}, {color_parts[2]}"
                        else:
                            structure.color_rgb = None
                    else:
                        structure.color_rgb = None
                except (AttributeError, ValueError):
                    structure.color_rgb = None
        
        # Get related rulegroup
        related_rulegroup = RuleGroup.objects.filter(
            associated_autosegmentation_template=template
        ).first()
        
        return render(request, 'dicom_handler/template_detail.html', {
            'template': template,
            'models': models,
            'related_rulegroup': related_rulegroup
        })
    except AutosegmentationTemplate.DoesNotExist:
        messages.error(request, 'Template not found.')
        return redirect('dicom_handler:template_list')

@login_required
@permission_required('dicom_handler.change_autosegmentationtemplate', raise_exception=True)
def edit_template(request, template_id):
    """
    View to edit an existing template - single page with structure selection
    """
    try:
        template = AutosegmentationTemplate.objects.get(id=template_id)
        
        # Get current structures for this template
        current_structures = []
        models = AutosegmentationModel.objects.filter(
            autosegmentation_template_name=template
        ).prefetch_related('autosegmentationstructure_set')
        
        for model in models:
            for structure in model.autosegmentationstructure_set.all():
                current_structures.append({
                    'id': structure.map_id,
                    'mapid': structure.map_id,
                    'map_tg263_primary_name': structure.name,
                    'model_id': model.model_id,
                    'model_name': model.name,
                    'model_config': model.config,
                    'model_trainer_name': model.trainer_name,
                    'model_postprocess': model.postprocess
                })
        
        # Fetch API data for structure selection
        system_config = SystemConfiguration.get_singleton()
        if not system_config or not system_config.draw_base_url:
            messages.error(request, 'System configuration not found. Please configure the DRAW API settings.')
            return redirect('dicom_handler:template_detail', template_id=template_id)
        
        try:
            api_url = f"{system_config.draw_base_url.rstrip('/')}/api/models/"
            headers = {}
            if system_config.draw_bearer_token:
                headers['Authorization'] = f"Bearer {system_config.draw_bearer_token}"
            
            response = requests.get(api_url, headers=headers, timeout=30)
            response.raise_for_status()
            
            api_data = response.json()
            
            # Flatten all structures from all models for pagination and search
            all_structures = []
            categories = set()
            anatomic_regions = set()
            model_names = set()
            
            for model in api_data:
                if 'modelmap' in model and model['modelmap']:
                    for structure in model['modelmap']:
                        structure_data = {
                            'id': structure.get('id'),
                            'mapid': structure.get('mapid'),
                            'map_tg263_primary_name': structure.get('map_tg263_primary_name'),
                            'Major_Category': structure.get('Major_Category'),
                            'Anatomic_Group': structure.get('Anatomic_Group'),
                            'Description': structure.get('Description'),
                            'median_dice_score': structure.get('median_dice_score'),
                            'model_id': model.get('model_id'),
                            'model_name': model.get('model_name'),
                            'model_config': model.get('model_config'),
                            'model_trainer_name': model.get('model_trainer_name'),
                            'model_postprocess': model.get('model_postprocess')
                        }
                        all_structures.append(structure_data)
                        
                        # Collect filter options
                        if structure.get('Major_Category'):
                            categories.add(structure.get('Major_Category'))
                        if structure.get('Anatomic_Group'):
                            anatomic_regions.add(structure.get('Anatomic_Group'))
                        if model.get('model_name'):
                            model_names.add(model.get('model_name'))
            
            # Handle search and filters
            search_query = request.GET.get('search', '').strip()
            category_filter = request.GET.get('category', '').strip()
            anatomic_filter = request.GET.get('anatomic_region', '').strip()
            model_filter = request.GET.get('model_name', '').strip()
            
            filtered_structures = all_structures
            
            if search_query:
                filtered_structures = []
                for structure in all_structures:
                    if (search_query.lower() in str(structure.get('map_tg263_primary_name', '')).lower() or
                        search_query.lower() in str(structure.get('Major_Category', '')).lower() or
                        search_query.lower() in str(structure.get('Anatomic_Group', '')).lower() or
                        search_query.lower() in str(structure.get('Description', '')).lower() or
                        search_query.lower() in str(structure.get('model_name', '')).lower()):
                        filtered_structures.append(structure)
            
            if category_filter:
                filtered_structures = [s for s in filtered_structures if s.get('Major_Category') == category_filter]
            
            if anatomic_filter:
                filtered_structures = [s for s in filtered_structures if s.get('Anatomic_Group') == anatomic_filter]
            
            if model_filter:
                filtered_structures = [s for s in filtered_structures if s.get('model_name') == model_filter]
            
            # Handle pagination
            page_number = request.GET.get('page', 1)
            paginator = Paginator(filtered_structures, 25)
            page_obj = paginator.get_page(page_number)
            
            # Build a set of selected structure IDs by matching model_id + mapid combinations
            # from database structures to API structures
            selected_structure_ids = []
            for db_structure in current_structures:
                db_model_id = db_structure.get('model_id')
                db_mapid = db_structure.get('mapid')
                
                # Find matching API structure
                for api_structure in all_structures:
                    if (api_structure.get('model_id') == db_model_id and 
                        api_structure.get('mapid') == db_mapid):
                        selected_structure_ids.append(str(api_structure.get('id')))
                        break
            
            return render(request, 'dicom_handler/edit_template.html', {
                'template': template,
                'page_obj': page_obj,
                'search_query': search_query,
                'selected_structures': current_structures,
                'selected_structure_ids': selected_structure_ids,
                'system_config': system_config,
                'categories': sorted(categories),
                'anatomic_regions': sorted(anatomic_regions),
                'model_names': sorted(model_names)
            })
            
        except requests.RequestException as e:
            messages.error(request, f'Error fetching models from API: {str(e)}')
            return redirect('dicom_handler:template_detail', template_id=template_id)
        
    except AutosegmentationTemplate.DoesNotExist:
        messages.error(request, 'Template not found.')
        return redirect('dicom_handler:template_list')

@login_required
@permission_required('dicom_handler.change_autosegmentationtemplate', raise_exception=True)
def update_template_info(request, template_id):
    """
    Update template name and description via AJAX
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Only POST method allowed'})
    
    try:
        template = AutosegmentationTemplate.objects.get(id=template_id)
        
        template_name = request.POST.get('template_name', '').strip()
        template_description = request.POST.get('template_description', '').strip()
        
        if not template_name:
            return JsonResponse({'success': False, 'error': 'Template name is required'})
        
        template.template_name = template_name
        template.template_description = template_description
        template.save()
        
        return JsonResponse({
            'success': True,
            'message': 'Template information updated successfully!'
        })
        
    except AutosegmentationTemplate.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Template not found'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
@permission_required('dicom_handler.delete_autosegmentationtemplate', raise_exception=True)
def delete_template(request, template_id):
    """
    View to delete a template
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Only POST method allowed'})
    
    try:
        template = AutosegmentationTemplate.objects.get(id=template_id)
        template_name = template.template_name
        template.delete()
        
        return JsonResponse({
            'success': True, 
            'message': f'Template "{template_name}" deleted successfully!'
        })
        
    except AutosegmentationTemplate.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Template not found'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
@permission_required('dicom_handler.change_autosegmentationtemplate', raise_exception=True)
def update_template(request, template_id):
    """
    AJAX endpoint to update an existing template
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Only POST method allowed'})
    
    try:
        template = AutosegmentationTemplate.objects.get(id=template_id)
        data = json.loads(request.body)
        template_name = data.get('template_name')
        template_description = data.get('template_description')
        
        # Get selected structures from request body (sent by JavaScript)
        selected_structures = data.get('selected_structures', [])
        
        # Debug logging
        print(f"DEBUG: Received {len(selected_structures)} structures for template update")
        for i, structure in enumerate(selected_structures[:3]):  # Log first 3 structures
            print(f"DEBUG: Structure {i}: {structure}")
        
        if not template_name:
            return JsonResponse({'success': False, 'error': 'Template name is required'})
        
        if not selected_structures:
            return JsonResponse({'success': False, 'error': 'No structures selected. Please select at least one structure.'})
        
        # Update template basic info
        template.template_name = template_name
        template.template_description = template_description or ''
        template.save()
        
        # Delete existing models and structures
        AutosegmentationModel.objects.filter(autosegmentation_template_name=template).delete()
        
        # Group structures by model
        models_dict = {}
        for structure in selected_structures:
            model_id = structure.get('model_id')
            if not model_id:
                print(f"DEBUG: Skipping structure without model_id: {structure}")
                continue
                
            if model_id not in models_dict:
                models_dict[model_id] = {
                    'model_id': structure.get('model_id'),
                    'model_name': structure.get('model_name'),
                    'model_config': structure.get('model_config'),
                    'model_trainer_name': structure.get('model_trainer_name'),
                    'model_postprocess': structure.get('model_postprocess'),
                    'structures': []
                }
            models_dict[model_id]['structures'].append(structure)
        
        print(f"DEBUG: Grouped structures into {len(models_dict)} models")
        
        # Save updated models and their structures
        for model_data in models_dict.values():
            try:
                model = AutosegmentationModel.objects.create(
                    id=uuid.uuid4(),
                    autosegmentation_template_name=template,
                    model_id=model_data.get('model_id'),
                    name=model_data.get('model_name', ''),
                    config=model_data.get('model_config', ''),
                    trainer_name=model_data.get('model_trainer_name', ''),
                    postprocess=model_data.get('model_postprocess', '')
                )
                
                # Save structures for this model
                for structure_data in model_data.get('structures', []):
                    # Ensure we have a valid map_id
                    map_id = structure_data.get('mapid') or structure_data.get('id')
                    if map_id:
                        try:
                            map_id = int(map_id)
                        except (ValueError, TypeError):
                            # If conversion fails, skip this structure
                            continue
                    else:
                        # Skip structures without valid map_id
                        continue
                        
                    AutosegmentationStructure.objects.create(
                        id=uuid.uuid4(),
                        autosegmentation_model=model,
                        map_id=map_id,
                        name=structure_data.get('map_tg263_primary_name', '')
                    )
                    
            except Exception as model_error:
                return JsonResponse({'success': False, 'error': f'Error updating model data: {str(model_error)}'})
        
        # Clear selections from session
        request.session.pop('selected_structures', None)
        request.session.pop('editing_template_id', None)
        request.session.modified = True
        
        return JsonResponse({
            'success': True, 
            'message': 'Template updated successfully!',
            'template_id': str(template.id)
        })
        
    except AutosegmentationTemplate.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Template not found'})
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
@permission_required('dicom_handler.delete_autosegmentationtemplate', raise_exception=True)
def template_delete(request, template_id):
    """
    AJAX endpoint to delete a template
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Only POST method allowed'})
    
    try:
        template = get_object_or_404(AutosegmentationTemplate, id=template_id)
        template_name = template.template_name
        template.delete()
        
        return JsonResponse({
            'success': True,
            'message': f'Template "{template_name}" deleted successfully!'
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def get_vr_guidance(request, tag_id):
    """
    AJAX endpoint to get VR guidance for a selected DICOM tag
    """
    try:
        dicom_tag = get_object_or_404(DICOMTagType, id=tag_id)
        
        return JsonResponse({
            'success': True,
            'vr_code': dicom_tag.value_representation,
            'guidance': dicom_tag.vr_guidance,
            'compatible_operators': dicom_tag.compatible_operators
        })
            
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': str(e)
        })


@login_required
def validate_vr_value(request):
    """
    AJAX endpoint to validate a value against VR requirements
    """
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            value = data.get('value', '')
            tag_id = data.get('tag_id', '')
            operator = data.get('operator', '')
            
            if not tag_id:
                return JsonResponse({
                    'success': True,
                    'is_valid': True,
                    'message': 'No tag selected'
                })
            
            dicom_tag = get_object_or_404(DICOMTagType, id=tag_id)
            
            # Validate value format using model method
            is_valid, vr_error = dicom_tag.validate_value_for_vr(value)
            
            # Check operator compatibility using model method
            operator_compatible = True
            operator_message = ""
            if operator and not dicom_tag.is_operator_compatible(operator):
                operator_compatible = False
                compatible_ops = dicom_tag.compatible_operators
                operator_message = f"Operator not compatible with {dicom_tag.value_representation} VR. Compatible: {', '.join(compatible_ops)}"
            
            return JsonResponse({
                'success': True,
                'is_valid': is_valid and operator_compatible,
                'vr_message': vr_error if not is_valid else "",
                'operator_message': operator_message,
                'vr_code': dicom_tag.value_representation
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            })
    
    return JsonResponse({
        'success': False,
        'message': 'Only POST method allowed'
    })

@login_required
def search_dicom_tags(request):
    """Search DICOM tags for autocomplete functionality."""
    query = request.GET.get('q', '').strip()
    get_all = request.GET.get('all', False)
    
    if get_all:
        # Return all DICOM tags for datalist population
        tags = DICOMTagType.objects.all().values('id', 'tag_name', 'tag_description', 'value_representation')[:100]
    elif len(query) < 2:
        return JsonResponse({'tags': []})
    else:
        # Search by tag name (case insensitive) - also search in description
        from django.db import models
        tags = DICOMTagType.objects.filter(
            models.Q(tag_name__icontains=query) | 
            models.Q(tag_description__icontains=query)
        ).values('id', 'tag_name', 'tag_description', 'value_representation')[:20]
    
    # Format results for autocomplete
    results = []
    for tag in tags:
        results.append({
            'id': str(tag['id']),
            'name': tag['tag_name'],
            'description': tag['tag_description'] or '',
            'vr': tag['value_representation'] or ''
        })
    
    return JsonResponse({'tags': results})

@login_required
@permission_required('dicom_handler.view_dicomseries', raise_exception=True)
def series_processing_status(request):
    """
    View to display DICOM series processing status with filtering, search, and pagination
    """
    # Get all series with related data including DICOMFileExport
    series_queryset = DICOMSeries.objects.select_related(
        'study__patient',
    ).prefetch_related(
        'matched_rule_sets',
        'matched_templates',
        'dicomfileexport_set'  # Add prefetch for DICOMFileExport
    ).order_by('-updated_at')
    
    # Handle search
    search_query = request.GET.get('search', '').strip()
    if search_query:
        series_queryset = series_queryset.filter(
            models.Q(study__patient__patient_name__icontains=search_query) |
            models.Q(study__patient__patient_id__icontains=search_query)
        )
    
    # Handle filters
    gender_filter = request.GET.get('gender', '').strip()
    if gender_filter:
        series_queryset = series_queryset.filter(study__patient__patient_gender=gender_filter)
    
    modality_filter = request.GET.get('modality', '').strip()
    if modality_filter:
        series_queryset = series_queryset.filter(study__study_modality=modality_filter)
    
    protocol_filter = request.GET.get('protocol', '').strip()
    if protocol_filter:
        series_queryset = series_queryset.filter(study__study_protocol__icontains=protocol_filter)
    
    status_filter = request.GET.get('status', '').strip()
    if status_filter:
        series_queryset = series_queryset.filter(series_processsing_status=status_filter)
    
    # Date filters
    study_date_from = request.GET.get('study_date_from', '').strip()
    study_date_to = request.GET.get('study_date_to', '').strip()
    updated_date_from = request.GET.get('updated_date_from', '').strip()
    updated_date_to = request.GET.get('updated_date_to', '').strip()
    
    if study_date_from:
        series_queryset = series_queryset.filter(study__study_date__gte=study_date_from)
    if study_date_to:
        series_queryset = series_queryset.filter(study__study_date__lte=study_date_to)
    if updated_date_from:
        series_queryset = series_queryset.filter(updated_at__gte=updated_date_from)
    if updated_date_to:
        series_queryset = series_queryset.filter(updated_at__lte=updated_date_to)
    
    # Get unique values for filter dropdowns
    all_genders = DICOMSeries.objects.select_related('study__patient').values_list(
        'study__patient__patient_gender', flat=True
    ).distinct().exclude(study__patient__patient_gender__isnull=True).exclude(study__patient__patient_gender='')
    
    all_modalities = DICOMSeries.objects.select_related('study').values_list(
        'study__study_modality', flat=True
    ).distinct().exclude(study__study_modality__isnull=True).exclude(study__study_modality='')
    
    all_protocols = DICOMSeries.objects.select_related('study').values_list(
        'study__study_protocol', flat=True
    ).distinct().exclude(study__study_protocol__isnull=True).exclude(study__study_protocol='')
    
    # Pagination
    paginator = Paginator(series_queryset, 10)  # 10 series per page as requested
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Prepare data for template
    series_data = []
    for series in page_obj:
        # Get matched rulegroups (via rulesets) and templates
        matched_rulesets = series.matched_rule_sets.select_related('rulegroup').all()
        matched_rulegroups = list(set([rs.rulegroup.rulegroup_name for rs in matched_rulesets if rs.rulegroup]))
        matched_templates = list(series.matched_templates.values_list('template_name', flat=True))
        
        # Get the most recent DICOMFileExport for this series if it exists
        export_info = None
        if hasattr(series, 'dicomfileexport_set') and series.dicomfileexport_set.exists():
            latest_export = series.dicomfileexport_set.latest('updated_at')
            export_info = {
                'server_segmentation_status': latest_export.server_segmentation_status or 'N/A',
                'task_id': latest_export.task_id or 'N/A',
                'server_segmentation_updated': latest_export.server_segmentation_updated_datetime
            }
        
        # Get RT Structure counts and rating info
        rt_structures = RTStructureFileImport.objects.filter(deidentified_series_instance_uid=series)
        rt_structure_count = rt_structures.count()
        rated_count = rt_structures.filter(date_contour_reviewed__isnull=False).count()
        
        series_info = {
            'id': series.id,
            'series_instance_uid': series.series_instance_uid,  # Add the missing field
            'patient_uuid': series.study.patient.id,  # UUID primary key for patient details link
            'patient_id': series.study.patient.patient_id or 'N/A',
            'patient_name': series.study.patient.patient_name or 'N/A',
            'gender': series.study.patient.patient_gender or 'N/A',
            'study_date': series.study.study_date,
            'series_description': series.series_description or 'N/A',
            'study_protocol': series.study.study_protocol or 'N/A',
            'study_modality': series.study.study_modality or 'N/A',
            'instance_count': series.instance_count or 0,
            'matched_rulesets': ', '.join(matched_rulegroups) if matched_rulegroups else 'None',
            'matched_templates': ', '.join(matched_templates) if matched_templates else 'None',
            'processing_status': series.get_series_processsing_status_display(),
            'updated_at': series.updated_at,
            'export_info': export_info,
            'rt_structure_count': rt_structure_count,
            'rated_count': rated_count
        }
        series_data.append(series_info)
    
    # Get active remote nodes for C-STORE push
    from dicom_server.models import RemoteDicomNode
    remote_nodes = RemoteDicomNode.objects.filter(
        is_active=True,
        allow_incoming=True
    ).exclude(
        incoming_ae_title__isnull=True
    ).exclude(
        incoming_ae_title=''
    ).exclude(
        host__isnull=True
    ).exclude(
        host=''
    )
    
    context = {
        'page_obj': page_obj,
        'series_data': series_data,
        'search_query': search_query,
        'gender_filter': gender_filter,
        'modality_filter': modality_filter,
        'protocol_filter': protocol_filter,
        'status_filter': status_filter,
        'study_date_from': study_date_from,
        'study_date_to': study_date_to,
        'updated_date_from': updated_date_from,
        'updated_date_to': updated_date_to,
        'all_genders': sorted(list(set(all_genders))),
        'all_modalities': sorted(list(set(all_modalities))),
        'all_protocols': sorted(list(set(all_protocols))),
        'processing_statuses': ProcessingStatus.choices,
        'remote_nodes': remote_nodes,
    }
    
    return render(request, 'dicom_handler/series_processing_status.html', context)

# System Configuration Views

@login_required
@permission_required('dicom_handler.view_systemconfiguration', raise_exception=True)
def system_configuration(request):
    """
    View to display and edit system configuration (singleton)
    """
    config = SystemConfiguration.load()  # This will create one if it doesn't exist
    
    if request.method == 'POST':
        # Check if user has change permission
        if not request.user.has_perm('dicom_handler.change_systemconfiguration'):
            messages.error(request, 'You do not have permission to modify system configuration.')
            return redirect('dicom_handler:system_configuration')
        
        form = SystemConfigurationForm(request.POST, instance=config)
        if form.is_valid():
            form.save()
            messages.success(request, 'System configuration updated successfully!')
            return redirect('dicom_handler:system_configuration')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = SystemConfigurationForm(instance=config)
    
    return render(request, 'dicom_handler/system_configuration.html', {
        'form': form,
        'config': config,
        'can_edit': request.user.has_perm('dicom_handler.change_systemconfiguration')
    })


@login_required
@permission_required('dicom_handler.view_dicomseries', raise_exception=True)
def manual_processing_status(request):
    """
    View for displaying manual processing status
    """
    from .utils.manual_autosegmentation import get_manual_processing_status
    from django.db.models import Q
    
    # Get all series that have been manually processed (have matched templates)
    manually_processed_series = DICOMSeries.objects.filter(
        matched_templates__isnull=False
    ).select_related('study__patient').prefetch_related('matched_templates', 'dicomfileexport_set')
    
    # Get series UIDs for status checking
    series_uids = list(manually_processed_series.values_list('series_instance_uid', flat=True))
    
    # Get detailed status information
    status_result = get_manual_processing_status(series_uids) if series_uids else {'status': 'success', 'series_status': []}
    
    # Calculate summary statistics
    total_processing = manually_processed_series.count()
    in_progress = manually_processed_series.filter(
        series_processsing_status__in=[
            ProcessingStatus.RULE_MATCHED,
            ProcessingStatus.PENDING_TRANSFER_TO_DRAW_SERVER
        ]
    ).count()
    completed = manually_processed_series.filter(
        series_processsing_status__in=[
            ProcessingStatus.SENT_TO_DRAW_SERVER,
            ProcessingStatus.RTSTRUCTURE_RECEIVED,
            ProcessingStatus.RTSTRUCTURE_EXPORTED
        ]
    ).count()
    failed = manually_processed_series.filter(
        series_processsing_status__in=[
            ProcessingStatus.DEIDENTIFICATION_FAILED,
            ProcessingStatus.FAILED_TRANSFER_TO_DRAW_SERVER
        ]
    ).count()
    
    # Prepare series status data
    series_status = []
    if status_result['status'] == 'success':
        for series_info in status_result.get('series_status', []):
            # Get the series object for additional information
            try:
                series = manually_processed_series.get(series_instance_uid=series_info['series_instance_uid'])
                series_info['matched_templates'] = series.matched_templates.all()
                series_info['export_info'] = series.dicomfileexport_set.first()
                series_info['last_updated'] = series.updated_at
            except DICOMSeries.DoesNotExist:
                pass
            series_status.append(series_info)
    
    context = {
        'total_processing': total_processing,
        'in_progress': in_progress,
        'completed': completed,
        'failed': failed,
        'series_status': series_status,
    }
    
    # Handle AJAX requests for status updates
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return render(request, 'dicom_handler/manual_processing_status.html', context)
    
    return render(request, 'dicom_handler/manual_processing_status.html', context)


@login_required
def statistics_dashboard(request):
    """
    View for displaying DICOM processing statistics dashboard with aggregated daily and weekly stats
    """
    from django.db.models import Count, Avg
    from django.utils import timezone
    from datetime import timedelta, datetime, time
    import json
    import statistics as stats_module
    
    now = timezone.now()
    
    # Calculate time ranges (week starts on Monday)
    today_start = timezone.make_aware(datetime.combine(now.date(), time.min))
    today_end = timezone.make_aware(datetime.combine(now.date(), time.max))
    
    # Current week (Monday to Sunday)
    days_since_monday = now.weekday()  # Monday = 0, Sunday = 6
    this_week_start = timezone.make_aware(
        datetime.combine((now - timedelta(days=days_since_monday)).date(), time.min)
    )
    this_week_end = timezone.make_aware(
        datetime.combine((this_week_start + timedelta(days=6)).date(), time.max)
    )
    
    # Past week (previous Monday to Sunday)
    past_week_start = this_week_start - timedelta(days=7)
    past_week_end = this_week_start - timedelta(seconds=1)
    
    def aggregate_stats(start_time, end_time, period_name):
        """
        Aggregate statistics for a given time period
        """
        stats = Statistics.objects.filter(
            created_at__gte=start_time,
            created_at__lte=end_time
        )
        
        # Initialize aggregated values
        aggregated = {
            'period': period_name,
            'unique_patients': 0,
            'unique_studies': 0,
            'unique_series': 0,
            'unique_instances': 0,
            'rt_struct_files': 0,
            'matched_rulesets': 0,
            'failed_segmentation': 0,
            'failed_deidentification': 0,
            'failed_exports': 0,
            'successful_exports': 0,
            'completed_segmentation': 0,
            'median_processing_time': 0,
        }
        
        # Aggregate each metric by summing values
        for param_name in [
            'unique_patients_since_last_run',
            'unique_dicom_studies_since_last_run',
            'unique_dicom_series_since_last_run',
            'unique_dicom_instances_since_last_run',
            'rt_struct_files_downloaded_since_last_run',
            'series_with_matching_rulesets_since_last_run',
            'series_with_failed_segmentation_since_last_run',
            'series_with_failed_deidentification_since_last_run',
            'series_with_failed_export_since_last_run',
            'series_exported_successfully_since_last_run',
            'series_completing_segmentation_since_last_run',
        ]:
            param_stats = stats.filter(parameter_name=param_name)
            total = sum(int(s.parameter_value) for s in param_stats if s.parameter_value.isdigit())
            
            # Map to aggregated keys
            if 'unique_patients' in param_name:
                aggregated['unique_patients'] = total
            elif 'unique_dicom_studies' in param_name:
                aggregated['unique_studies'] = total
            elif 'unique_dicom_series' in param_name:
                aggregated['unique_series'] = total
            elif 'unique_dicom_instances' in param_name:
                aggregated['unique_instances'] = total
            elif 'rt_struct_files_downloaded' in param_name:
                aggregated['rt_struct_files'] = total
            elif 'series_with_matching_rulesets' in param_name:
                aggregated['matched_rulesets'] = total
            elif 'series_with_failed_segmentation' in param_name:
                aggregated['failed_segmentation'] = total
            elif 'series_with_failed_deidentification' in param_name:
                aggregated['failed_deidentification'] = total
            elif 'series_with_failed_export' in param_name:
                aggregated['failed_exports'] = total
            elif 'series_exported_successfully' in param_name:
                aggregated['successful_exports'] = total
            elif 'series_completing_segmentation' in param_name:
                aggregated['completed_segmentation'] = total
        
        # Calculate median processing time (excluding zeros)
        processing_times = stats.filter(
            parameter_name='average_segmentation_processing_time_seconds_since_last_run'
        )
        time_values = []
        for pt in processing_times:
            try:
                val = float(pt.parameter_value)
                if val > 0:  # Exclude zero values
                    time_values.append(val)
            except (ValueError, TypeError):
                continue
        
        if time_values:
            aggregated['median_processing_time'] = round(stats_module.median(time_values)/60, 2)
        else:
            aggregated['median_processing_time'] = 0
        
        return aggregated
    
    # Calculate aggregated statistics for each period
    today_stats = aggregate_stats(today_start, today_end, 'Today')
    this_week_stats = aggregate_stats(this_week_start, this_week_end, 'This Week')
    past_week_stats = aggregate_stats(past_week_start, past_week_end, 'Past Week')
    
    # Processing status breakdown (current state)
    status_breakdown = DICOMSeries.objects.values('series_processsing_status').annotate(
        count=Count('id')
    ).order_by('series_processsing_status')
    
    context = {
        'today_stats': today_stats,
        'this_week_stats': this_week_stats,
        'past_week_stats': past_week_stats,
        'status_breakdown': status_breakdown,
        'last_updated': now,
        'today_date': today_start.strftime('%B %d, %Y'),
        'this_week_range': f"{this_week_start.strftime('%b %d')} - {this_week_end.strftime('%b %d, %Y')}",
        'past_week_range': f"{past_week_start.strftime('%b %d')} - {past_week_end.strftime('%b %d, %Y')}",
    }
    
    return render(request, 'dicom_handler/statistics_dashboard.html', context)


@login_required
@permission_required('dicom_handler.view_dicomseries', raise_exception=True)
def rate_contour_quality(request, series_uid):
    """
    View for rating contour quality of RT Structure Set and individual VOIs.
    Displays form to rate RT Structure Set level data and individual VOI ratings.
    
    Args:
        series_uid: Series Instance UID to find the RT Structure
        rt_import (query param): Optional RT Structure Import ID to rate a specific structure set
    """
    # Get the series
    series = get_object_or_404(DICOMSeries, series_instance_uid=series_uid)
    
    # Check if a specific RT Structure Import ID was provided
    rt_import_id = request.GET.get('rt_import')
    
    if rt_import_id:
        # Get the specific RT Structure Import
        rt_import = get_object_or_404(
            RTStructureFileImport,
            id=rt_import_id,
            deidentified_series_instance_uid=series
        )
    else:
        # Get the most recent RT Structure File Import for this series
        try:
            rt_import = RTStructureFileImport.objects.filter(
                deidentified_series_instance_uid=series
            ).order_by('-created_at').first()
            
            if not rt_import:
                raise RTStructureFileImport.DoesNotExist
        except RTStructureFileImport.DoesNotExist:
            messages.error(request, 'No RT Structure file found for this series.')
            return redirect('dicom_handler:series_processing_status')
    
    # Get all VOI data for this RT Structure
    voi_queryset = RTStructureFileVOIData.objects.filter(
        rt_structure_file_import=rt_import
    ).order_by('volume_name')
    
    if request.method == 'POST':
        # Process both forms
        rt_form = RTStructureReviewForm(request.POST, instance=rt_import)
        voi_formset = VOIRatingFormSet(request.POST, queryset=voi_queryset)
        
        if rt_form.is_valid() and voi_formset.is_valid():
            # Save RT Structure level data
            rt_form.save()
            
            # Save all VOI ratings
            voi_formset.save()
            
            messages.success(request, 'Contour quality ratings saved successfully!')
            return redirect('dicom_handler:series_processing_status')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        # Initialize forms
        rt_form = RTStructureReviewForm(instance=rt_import)
        voi_formset = VOIRatingFormSet(queryset=voi_queryset)
    
    # Get patient and study information for display
    patient = series.study.patient
    study = series.study
    
    # Get total RT Structure count for this series
    total_rt_structures = RTStructureFileImport.objects.filter(
        deidentified_series_instance_uid=series
    ).count()
    
    context = {
        'series': series,
        'patient': patient,
        'study': study,
        'rt_import': rt_import,
        'rt_form': rt_form,
        'voi_formset': voi_formset,
        'voi_count': voi_queryset.count(),
        'total_rt_structures': total_rt_structures,
        'rt_import_id': rt_import.id,
    }
    
    return render(request, 'dicom_handler/contour_rating.html', context)


@login_required
@permission_required('dicom_handler.view_dicomseries', raise_exception=True)
def view_series_ratings(request, series_uid):
    """
    View to display all RT Structure ratings for a given series.
    Shows all RT Structure sets and their ratings.
    
    Args:
        series_uid: Series Instance UID
    """
    # Get the series
    series = get_object_or_404(DICOMSeries, series_instance_uid=series_uid)
    
    # Get all RT Structure imports for this series
    rt_imports = RTStructureFileImport.objects.filter(
        deidentified_series_instance_uid=series
    ).order_by('-created_at')
    
    # Prepare rating data
    ratings_data = []
    for rt_import in rt_imports:
        # Get VOI count
        voi_count = RTStructureFileVOIData.objects.filter(rt_structure_file_import=rt_import).count()
        
        rating_info = {
            'rt_import': rt_import,
            'voi_count': voi_count,
            'export_date': rt_import.reidentified_rt_structure_file_export_datetime,
            'has_rating': rt_import.date_contour_reviewed is not None,
        }
        ratings_data.append(rating_info)
    
    # Get patient and study information
    patient = series.study.patient
    study = series.study
    
    context = {
        'series': series,
        'patient': patient,
        'study': study,
        'ratings_data': ratings_data,
        'rt_structure_count': len(ratings_data),
        'rated_count': sum(1 for r in ratings_data if r['has_rating']),
    }
    
    return render(request, 'dicom_handler/view_series_ratings.html', context)

@login_required
def check_api_health(request):
    """
    View to check the health status of the DRAW API server
    Returns JSON response with health status
    """
    try:
        system_config = SystemConfiguration.get_singleton()
        
        if not system_config:
            return JsonResponse({
                'status': 'error',
                'message': 'System configuration not found. Please configure system settings.'
            }, status=500)
        
        if not system_config.draw_base_url:
            return JsonResponse({
                'status': 'error',
                'message': 'DRAW API URL not configured. Please set draw_base_url in System Configuration.'
            }, status=500)
        
        # Check if bearer token needs refresh
        from django.utils import timezone
        if system_config.draw_bearer_token_validaty and system_config.draw_bearer_token_validaty <= timezone.now():
            logger.info("Bearer token expired, attempting refresh before health check")
            if system_config.draw_refresh_token and system_config.draw_token_refresh_endpoint:
                # Attempt to refresh the token
                refresh_url = system_config.draw_base_url + system_config.draw_token_refresh_endpoint
                try:
                    refresh_headers = {
                        'Authorization': f'Bearer {system_config.draw_refresh_token}',
                        'Content-Type': 'application/json'
                    }
                    refresh_response = requests.post(refresh_url, headers=refresh_headers, timeout=5)
                    
                    if refresh_response.status_code == 200:
                        token_data = refresh_response.json()
                        from django.db import transaction
                        from dateutil import parser as dateutil_parser
                        from datetime import timedelta
                        
                        with transaction.atomic():
                            system_config.draw_bearer_token = token_data.get('access_token')
                            if 'refresh_token' in token_data:
                                system_config.draw_refresh_token = token_data.get('refresh_token')
                            
                            # Calculate expiry date from expires_in (seconds)
                            if 'expires_in' in token_data:
                                expires_in_seconds = int(token_data['expires_in'])
                                expires_at = timezone.now() + timedelta(seconds=expires_in_seconds)
                                system_config.draw_bearer_token_validaty = expires_at
                                logger.info(f"Token expiry updated to: {expires_at}")
                            elif 'expires_at' in token_data:
                                # Fallback: Parse ISO format datetime if provided
                                expires_at = dateutil_parser.isoparse(token_data['expires_at'])
                                if expires_at.tzinfo is None:
                                    expires_at = timezone.make_aware(expires_at)
                                system_config.draw_bearer_token_validaty = expires_at
                                logger.info(f"Token expiry updated to: {expires_at}")
                            
                            system_config.save()
                        
                        logger.info("Bearer token refreshed successfully during health check")
                    else:
                        logger.warning(f"Token refresh failed with status: {refresh_response.status_code}")
                except Exception as refresh_error:
                    logger.error(f"Error refreshing token during health check: {str(refresh_error)}")
        
        # Construct the health check URL
        # Note: draw_base_url already has trailing slash
        api_url = f"{system_config.draw_base_url}api/health"
        
        headers = {}
        if system_config.draw_bearer_token:
            headers['Authorization'] = f"Bearer {system_config.draw_bearer_token}"
        
        # Make request to health endpoint with timeout
        response = requests.get(api_url, headers=headers, timeout=5)
        
        # If we get 401, try to refresh token and retry once
        if response.status_code == 401:
            logger.info("Received 401 Unauthorized, attempting token refresh")
            if system_config.draw_refresh_token and system_config.draw_token_refresh_endpoint:
                refresh_url = system_config.draw_base_url + system_config.draw_token_refresh_endpoint
                try:
                    refresh_headers = {
                        'Authorization': f'Bearer {system_config.draw_refresh_token}',
                        'Content-Type': 'application/json'
                    }
                    refresh_response = requests.post(refresh_url, headers=refresh_headers, timeout=5)
                    
                    if refresh_response.status_code == 200:
                        token_data = refresh_response.json()
                        from django.db import transaction
                        from dateutil import parser as dateutil_parser
                        
                        with transaction.atomic():
                            system_config.draw_bearer_token = token_data.get('access_token')
                            if 'refresh_token' in token_data:
                                system_config.draw_refresh_token = token_data.get('refresh_token')
                            
                            # Calculate expiry date from expires_in (seconds)
                            if 'expires_in' in token_data:
                                expires_in_seconds = int(token_data['expires_in'])
                                expires_at = timezone.now() + timedelta(seconds=expires_in_seconds)
                                system_config.draw_bearer_token_validaty = expires_at
                                logger.info(f"Token expiry updated to: {expires_at}")
                            elif 'expires_at' in token_data:
                                # Fallback: Parse ISO format datetime if provided
                                expires_at = dateutil_parser.isoparse(token_data['expires_at'])
                                if expires_at.tzinfo is None:
                                    expires_at = timezone.make_aware(expires_at)
                                system_config.draw_bearer_token_validaty = expires_at
                                logger.info(f"Token expiry updated to: {expires_at}")
                            
                            system_config.save()
                        
                        logger.info("Bearer token refreshed successfully, retrying health check")
                        
                        # Retry health check with new token
                        headers['Authorization'] = f"Bearer {system_config.draw_bearer_token}"
                        response = requests.get(api_url, headers=headers, timeout=5)
                except Exception as refresh_error:
                    logger.error(f"Error refreshing token after 401: {str(refresh_error)}")
        
        # Parse the response
        if response.status_code == 200:
            health_data = response.json()
            return JsonResponse({
                'status': health_data.get('status', 'unknown'),
                'details': health_data.get('details', {})
            })
        elif response.status_code == 503:
            health_data = response.json()
            return JsonResponse({
                'status': health_data.get('status', 'degraded'),
                'details': health_data.get('details', {})
            })
        elif response.status_code == 401:
            return JsonResponse({
                'status': 'error',
                'message': 'Authentication failed. Please check bearer token configuration.'
            }, status=401)
        else:
            return JsonResponse({
                'status': 'error',
                'message': f'Unexpected status code: {response.status_code}'
            }, status=response.status_code)
            
    except requests.exceptions.Timeout:
        return JsonResponse({
            'status': 'error',
            'message': 'Request timeout'
        }, status=504)
    except requests.exceptions.ConnectionError:
        return JsonResponse({
            'status': 'error',
            'message': 'Connection error'
        }, status=503)
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)

@login_required
def patient_list(request):
    """
    View for displaying list of all patients with search and pagination.
    """
    search_query = request.GET.get('search', '').strip()
    
    # Get all patients
    patients = Patient.objects.all()
    
    # Apply search filter if provided
    if search_query:
        patients = patients.filter(
            models.Q(patient_name__icontains=search_query) |
            models.Q(patient_id__icontains=search_query) |
            models.Q(deidentified_patient_id__icontains=search_query)
        )
    
    # Order by most recent
    patients = patients.order_by('-created_at')
    
    # Add study count annotation
    patients = patients.annotate(
        study_count=models.Count('dicomstudy', distinct=True)
    )
    
    # Pagination
    paginator = Paginator(patients, 25)  # 25 patients per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'search_query': search_query,
        'total_patients': patients.count(),
    }
    
    return render(request, 'dicom_handler/patient_list.html', context)


@login_required
def patient_details(request, patient_uuid):
    """
    View for displaying comprehensive patient details with hierarchical data:
    Patient -> Studies -> Series -> RT Structure Sets -> VOI Data
    """
    # Get patient by UUID (primary key) - no special character issues
    patient = get_object_or_404(Patient, id=patient_uuid)
    
    # Get all studies for this patient
    studies = DICOMStudy.objects.filter(patient=patient).order_by('-study_date')
    
    # Build hierarchical data structure
    studies_data = []
    for study in studies:
        # Get all series for this study
        series_list = DICOMSeries.objects.filter(study=study).order_by('-series_date')
        
        series_data = []
        for series in series_list:
            # Get file export information for this series
            file_exports = DICOMFileExport.objects.filter(
                deidentified_series_instance_uid=series
            ).order_by('-created_at')
            
            # Get RT Structure imports for this series
            rt_structures = RTStructureFileImport.objects.filter(
                deidentified_series_instance_uid=series
            ).order_by('-created_at')
            
            rt_structure_data = []
            for rt_struct in rt_structures:
                # Get VOI data for this RT structure
                voi_data = RTStructureFileVOIData.objects.filter(
                    rt_structure_file_import=rt_struct
                ).order_by('volume_name')
                
                # Check if this RT structure has been rated
                has_rating = (
                    rt_struct.date_contour_reviewed is not None or
                    rt_struct.contour_modification_time_required is not None or
                    rt_struct.overall_rating is not None
                )
                
                rt_structure_data.append({
                    'rt_import': rt_struct,
                    'voi_list': voi_data,
                    'voi_count': voi_data.count(),
                    'has_rating': has_rating,
                })
            
            # Get matched rulesets and templates
            matched_rulesets = series.matched_rule_sets.all()
            matched_templates = series.matched_templates.all()
            
            series_data.append({
                'series': series,
                'file_exports': file_exports,
                'rt_structures': rt_structure_data,
                'rt_structure_count': len(rt_structure_data),
                'matched_rulesets': matched_rulesets,
                'matched_templates': matched_templates,
            })
        
        studies_data.append({
            'study': study,
            'series_list': series_data,
            'series_count': len(series_data),
        })
    
    context = {
        'patient': patient,
        'studies_data': studies_data,
        'total_studies': studies.count(),
        'total_series': DICOMSeries.objects.filter(study__patient=patient).count(),
        'total_rt_structures': RTStructureFileImport.objects.filter(
            deidentified_series_instance_uid__study__patient=patient
        ).count(),
    }
    
    return render(request, 'dicom_handler/patient_details.html', context)

@login_required
def rt_structure_ratings_list(request):
    """
    View to display and export RT Structure ratings data
    """
    # Get all RT Structure imports with ratings (where date_contour_reviewed is not null)
    rt_imports = RTStructureFileImport.objects.filter(
        date_contour_reviewed__isnull=False
    ).select_related(
        'deidentified_series_instance_uid__study__patient'
    ).order_by('-date_contour_reviewed')
    
    # Pagination
    paginator = Paginator(rt_imports, 20)  # 20 items per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Prepare data for display
    ratings_data = []
    for rt_import in page_obj:
        series = rt_import.deidentified_series_instance_uid
        if series and series.study and series.study.patient:
            patient = series.study.patient
            
            # Get VOI data count
            voi_count = RTStructureFileVOIData.objects.filter(
                rt_structure_file_import=rt_import
            ).count()
            
            ratings_data.append({
                'rt_import': rt_import,
                'patient': patient,
                'series': series,
                'voi_count': voi_count,
            })
    
    context = {
        'page_obj': page_obj,
        'ratings_data': ratings_data,
        'total_ratings': rt_imports.count(),
    }
    
    return render(request, 'dicom_handler/rt_structure_ratings_list.html', context)

@login_required
def export_rt_structure_ratings_csv(request):
    """
    Export RT Structure ratings data as CSV file in long format
    """
    # Create the HttpResponse object with CSV header
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="rt_structure_ratings_export.csv"'
    
    writer = csv.writer(response)
    
    # Write header row
    writer.writerow([
        'patient_id',
        'name',
        'gender',
        'date_of_birth',
        'series_instance_uid',
        'date_contour_reviewed',
        'contour_modification_time_required',
        'assessor_name',
        'overall_rating',
        'volume_name',
        'contour_modification',
        'contour_modification_type',
        'contour_modification_comments',
    ])
    
    # Get all RT Structure imports with ratings
    rt_imports = RTStructureFileImport.objects.filter(
        date_contour_reviewed__isnull=False
    ).select_related(
        'deidentified_series_instance_uid__study__patient'
    ).prefetch_related(
        'rtstructurefilevoidata_set__contour_modification_type'
    ).order_by('-date_contour_reviewed')
    
    # Write data rows (long format - one row per VOI)
    for rt_import in rt_imports:
        series = rt_import.deidentified_series_instance_uid
        if not series or not series.study or not series.study.patient:
            continue
            
        patient = series.study.patient
        
        # Get all VOI data for this RT Structure
        voi_data_list = RTStructureFileVOIData.objects.filter(
            rt_structure_file_import=rt_import
        ).prefetch_related('contour_modification_type')
        
        # If no VOI data, write one row with RT Structure info only
        if not voi_data_list.exists():
            writer.writerow([
                patient.patient_id or '',
                patient.patient_name or '',
                patient.patient_gender or '',
                patient.patient_date_of_birth.strftime('%Y-%m-%d') if patient.patient_date_of_birth else '',
                series.series_instance_uid or '',
                rt_import.date_contour_reviewed.strftime('%Y-%m-%d') if rt_import.date_contour_reviewed else '',
                rt_import.contour_modification_time_required or '',
                rt_import.assessor_name or '',
                rt_import.overall_rating or '',
                '',  # volume_name
                '',  # contour_modification
                '',  # contour_modification_type
                '',  # contour_modification_comments
            ])
        else:
            # Write one row per VOI
            for voi_data in voi_data_list:
                # Get all modification types as comma-separated string
                modification_types = ', '.join([
                    mod_type.modification_type 
                    for mod_type in voi_data.contour_modification_type.all()
                ])
                
                writer.writerow([
                    patient.patient_id or '',
                    patient.patient_name or '',
                    patient.patient_gender or '',
                    patient.patient_date_of_birth.strftime('%Y-%m-%d') if patient.patient_date_of_birth else '',
                    series.series_instance_uid or '',
                    rt_import.date_contour_reviewed.strftime('%Y-%m-%d') if rt_import.date_contour_reviewed else '',
                    rt_import.contour_modification_time_required or '',
                    rt_import.assessor_name or '',
                    rt_import.overall_rating or '',
                    voi_data.volume_name or '',
                    voi_data.get_contour_modification_display() if voi_data.contour_modification else '',
                    modification_types,
                    voi_data.contour_modification_comments or '',
                ])
    
    return response


@login_required
@permission_required('dicom_handler.change_autosegmentationstructure', raise_exception=True)
def edit_structure_properties(request, structure_id):
    """
    View to edit structure properties (ROI label, type, and display color)
    """
    try:
        structure = get_object_or_404(AutosegmentationStructure, id=structure_id)
        
        # Get or create StructureProperties for this structure
        structure_properties, created = StructureProperties.objects.get_or_create(
            autosegmentation_structure=structure
        )
        
        if request.method == 'POST':
            form = StructurePropertiesForm(request.POST, instance=structure_properties)
            if form.is_valid():
                form.save()
                messages.success(request, f'Properties for "{structure.name}" updated successfully.')
                
                # Return JSON response for AJAX requests
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({
                        'success': True,
                        'message': f'Properties for "{structure.name}" updated successfully.'
                    })
                
                # Redirect to template detail page
                template = structure.autosegmentation_model.autosegmentation_template_name
                return redirect('dicom_handler:template_detail', template_id=template.id)
            else:
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({
                        'success': False,
                        'errors': form.errors
                    }, status=400)
        else:
            form = StructurePropertiesForm(instance=structure_properties)
        
        # Get template for breadcrumb/navigation
        template = structure.autosegmentation_model.autosegmentation_template_name
        
        return render(request, 'dicom_handler/edit_structure_properties.html', {
            'form': form,
            'structure': structure,
            'structure_properties': structure_properties,
            'template': template
        })
        
    except AutosegmentationStructure.DoesNotExist:
        messages.error(request, 'Structure not found.')
        return redirect('dicom_handler:template_list')
