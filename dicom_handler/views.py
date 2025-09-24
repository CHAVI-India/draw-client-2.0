from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.core.paginator import Paginator
from django.db import models
from .forms import TemplateCreationForm, RuleSetForm, RuleFormSet, RuleFormSetHelper, SystemConfigurationForm
from .models import SystemConfiguration, AutosegmentationTemplate, AutosegmentationModel, AutosegmentationStructure, RuleSet, Rule, DICOMTagType, Patient, DICOMStudy, DICOMSeries, ProcessingStatus
from .vr_validators import VRValidator
import requests
import json
import uuid

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
    View to display all rulesets
    """
    rulesets = RuleSet.objects.all().order_by('-created_at')
    
    # Add rule count for each ruleset
    for ruleset in rulesets:
        rule_count = Rule.objects.filter(ruleset=ruleset).count()
        ruleset.rule_count = rule_count
    
    return render(request, 'dicom_handler/ruleset_list.html', {
        'rulesets': rulesets
    })

@login_required
@permission_required('dicom_handler.add_ruleset', raise_exception=True)
def ruleset_create(request):
    """
    View to create a new ruleset with inline rules
    """
    # Get template_id from URL parameter if provided
    template_id = request.GET.get('template')
    initial_data = {}
    
    if template_id:
        try:
            template = AutosegmentationTemplate.objects.get(id=template_id)
            initial_data['associated_autosegmentation_template'] = template
        except AutosegmentationTemplate.DoesNotExist:
            messages.warning(request, 'The specified template was not found.')
    
    if request.method == 'POST':
        form = RuleSetForm(request.POST)
        formset = RuleFormSet(request.POST)
        
        # Debug: Print formset data
        print(f"POST data: {request.POST}")
        print(f"Formset is valid: {formset.is_valid()}")
        if not formset.is_valid():
            print(f"Formset errors: {formset.errors}")
            print(f"Formset non-form errors: {formset.non_form_errors}")
        
        if form.is_valid() and formset.is_valid():
            # Create the ruleset
            ruleset = form.save(commit=False)
            ruleset.id = uuid.uuid4()
            ruleset.save()
            
            # Save the rules
            formset.instance = ruleset
            formset.save()
            
            messages.success(request, f'RuleSet "{ruleset.ruleset_name}" created successfully!')
            return redirect('dicom_handler:ruleset_list')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = RuleSetForm(initial=initial_data)
        formset = RuleFormSet()
    
    # Add helper to formset for Crispy Forms
    formset_helper = RuleFormSetHelper()
    
    return render(request, 'dicom_handler/ruleset_create.html', {
        'form': form,
        'formset': formset,
        'formset_helper': formset_helper
    })

@login_required
@permission_required('dicom_handler.view_ruleset', raise_exception=True)
def ruleset_detail(request, ruleset_id):
    """
    View to display detailed information about a specific ruleset
    """
    ruleset = get_object_or_404(RuleSet, id=ruleset_id)
    rules = Rule.objects.filter(ruleset=ruleset).select_related('dicom_tag_type')
    
    return render(request, 'dicom_handler/ruleset_detail.html', {
        'ruleset': ruleset,
        'rules': rules
    })

@login_required
@permission_required('dicom_handler.change_ruleset', raise_exception=True)
def ruleset_edit(request, ruleset_id):
    """
    View to edit an existing ruleset
    """
    ruleset = get_object_or_404(RuleSet, id=ruleset_id)
    
    if request.method == 'POST':
        form = RuleSetForm(request.POST, instance=ruleset)
        formset = RuleFormSet(request.POST, instance=ruleset)
        
        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            
            messages.success(request, f'RuleSet "{ruleset.ruleset_name}" updated successfully!')
            return redirect('dicom_handler:ruleset_detail', ruleset_id=ruleset.id)
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = RuleSetForm(instance=ruleset)
        formset = RuleFormSet(instance=ruleset)
    
    # Add helper to formset for Crispy Forms
    formset_helper = RuleFormSetHelper()
    
    return render(request, 'dicom_handler/ruleset_edit.html', {
        'form': form,
        'formset': formset,
        'formset_helper': formset_helper,
        'ruleset': ruleset
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
        # Get related ruleset
        related_ruleset = RuleSet.objects.filter(
            associated_autosegmentation_template=template
        ).first()
        
        template.structure_count = structure_count
        template.model_count = model_count
        template.related_ruleset = related_ruleset
    
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
        ).prefetch_related('autosegmentationstructure_set')
        
        # Get related ruleset
        related_ruleset = RuleSet.objects.filter(
            associated_autosegmentation_template=template
        ).first()
        
        return render(request, 'dicom_handler/template_detail.html', {
            'template': template,
            'models': models,
            'related_ruleset': related_ruleset
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
            
            # Convert current_structures to a list of IDs for the template
            selected_structure_ids = [str(s['id']) for s in current_structures if s.get('id')]
            
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
        # Get matched rulesets and templates
        matched_rulesets = list(series.matched_rule_sets.values_list('ruleset_name', flat=True))
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
        
        series_info = {
            'id': series.id,
            'series_instance_uid': series.series_instance_uid,  # Add the missing field
            'patient_id': series.study.patient.patient_id or 'N/A',
            'patient_name': series.study.patient.patient_name or 'N/A',
            'gender': series.study.patient.patient_gender or 'N/A',
            'study_date': series.study.study_date,
            'study_description': series.study.study_description or 'N/A',
            'study_protocol': series.study.study_protocol or 'N/A',
            'study_modality': series.study.study_modality or 'N/A',
            'instance_count': series.instance_count or 0,
            'matched_rulesets': ', '.join(matched_rulesets) if matched_rulesets else 'None',
            'matched_templates': ', '.join(matched_templates) if matched_templates else 'None',
            'processing_status': series.get_series_processsing_status_display(),
            'updated_at': series.updated_at,
            'export_info': export_info
        }
        series_data.append(series_info)
    
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
