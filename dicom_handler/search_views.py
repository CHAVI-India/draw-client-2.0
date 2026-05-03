import json
import requests
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.template.loader import render_to_string
from .models import SystemConfiguration

@login_required
def search_structures(request):
    """
    AJAX endpoint to search structures while preserving template creation state
    """
    if request.method != 'GET':
        return JsonResponse({'success': False, 'error': 'Only GET method allowed'})
    
    try:
        search_query = request.GET.get('search', '').strip()
        category_filter = request.GET.get('category', '').strip()
        anatomic_filter = request.GET.get('anatomic', '').strip()
        model_filter = request.GET.get('model', '').strip()
        page_number = request.GET.get('page', 1)
        
        # Get template data from session
        template_name = request.session.get('template_name')
        template_description = request.session.get('template_description')
        
        if not template_name:
            return JsonResponse({'success': False, 'error': 'Template session expired. Please start over.'})
        
        # Fetch API data
        system_config = SystemConfiguration.objects.first()
        if not system_config or not system_config.draw_base_url:
            return JsonResponse({'success': False, 'error': 'System configuration not found'})
        
        api_url = f"{system_config.draw_base_url.rstrip('/')}/api/models/"
        headers = {}
        if system_config.draw_bearer_token:
            headers['Authorization'] = f"Bearer {system_config.draw_bearer_token}"
        
        response = requests.get(api_url, headers=headers, timeout=30)
        response.raise_for_status()
        
        api_data = response.json()

        # Define core fields that are displayed in the main table
        # All other fields from the API will be shown in the expandable details card
        CORE_STRUCTURE_FIELDS = {
            'id', 'mapid', 'map_tg263_primary_name', 'Major_Category',
            'Anatomic_Group', 'Description', 'delineation_modality',
            'median_dice_score'
        }
        CORE_MODEL_FIELDS = {
            'model_id', 'model_name', 'model_config',
            'model_trainer_name', 'model_postprocess'
        }
        # Internal fields that should never be displayed in the UI
        INTERNAL_MODEL_FIELDS = {
            'model_file_paths', 'model_uploaded_to_gpu_server',
            'date_model_uploaded_to_gpu_server', 'model_uploaded_to_gpu_server_provider',
            'model_uploaded_to_gpu_server_template_name', 'created_user',
            'created_date', 'modified_date', 'modified_user',
            'activate_date', 'model_activate_date', 'is_active',
            'model_created_date', 'model_modified_date', 'model_activate_date',
            'model_date_model_activated', 'date_model_activated', 'model_activated_date',
            'model_date_created', 'model_date_modified', 'date_created', 'date_modified',
            'model_activation_date', 'model_activated_at', 'model_activation_at',
            'model_activated_on', 'model_activation_on', 'model_activated_time',
            'model_activation_time', 'model_active_status', 'active_status',
            'model_status', 'model_is_active', 'is_model_active', 'model_state'
        }

        # Flatten all structures from all models
        all_structures = []
        for model in api_data:
            if 'modelmap' in model and model['modelmap']:
                for structure in model['modelmap']:
                    # Capture ALL fields from both structure and model dynamically
                    # This ensures future API fields are automatically available
                    structure_data = {}

                    # Add all structure fields
                    if isinstance(structure, dict):
                        structure_data.update(structure)

                    # Add all model fields with 'model_' prefix (except modelmap)
                    if isinstance(model, dict):
                        for key, value in model.items():
                            if key != 'modelmap':
                                model_key = f"model_{key}" if not key.startswith('model_') else key
                                structure_data[model_key] = value

                    # Store metadata for template rendering
                    # (Using 'detail_fields' and 'core_fields' without underscore prefix
                    # because Django templates block access to underscore-prefixed attributes)
                    structure_data['core_fields'] = list(CORE_STRUCTURE_FIELDS | CORE_MODEL_FIELDS)
                    structure_data['detail_fields'] = [k for k in structure_data.keys()
                                                        if k not in ('core_fields', 'detail_fields') and
                                                        k not in (CORE_STRUCTURE_FIELDS | CORE_MODEL_FIELDS | INTERNAL_MODEL_FIELDS)]

                    all_structures.append(structure_data)
        
        # Handle search and filters
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
        
        # Get unique values for filter dropdowns
        categories = sorted(list(set(s.get('Major_Category', '') for s in all_structures if s.get('Major_Category'))))
        anatomic_regions = sorted(list(set(s.get('Anatomic_Group', '') for s in all_structures if s.get('Anatomic_Group'))))
        model_names = sorted(list(set(s.get('model_name', '') for s in all_structures if s.get('model_name'))))
        
        # Handle pagination
        paginator = Paginator(all_structures, 25)
        page_obj = paginator.get_page(page_number)
        
        # Get selected structures from session
        selected_structures = request.session.get('selected_structures', [])

        # Extract IDs for template checkbox checking
        selected_structure_ids = []
        for item in selected_structures:
            if isinstance(item, dict) and item.get('id'):
                selected_structure_ids.append(str(item['id']))
            elif isinstance(item, (str, int)):
                selected_structure_ids.append(str(item))

        # Render the table HTML
        table_html = render_to_string('dicom_handler/structures_table.html', {
            'page_obj': page_obj,
            'selected_structures': selected_structures,
            'selected_structure_ids': selected_structure_ids,
            'system_config': system_config,
            'search_query': search_query,
            'category_filter': category_filter,
            'anatomic_filter': anatomic_filter,
            'model_filter': model_filter,
            'categories': categories,
            'anatomic_regions': anatomic_regions,
            'model_names': model_names
        })
        
        return JsonResponse({
            'success': True,
            'table_html': table_html,
            'has_previous': page_obj.has_previous(),
            'has_next': page_obj.has_next(),
            'current_page': page_obj.number,
            'total_pages': page_obj.paginator.num_pages,
            'total_count': page_obj.paginator.count,
            'start_index': page_obj.start_index(),
            'end_index': page_obj.end_index(),
            'categories': categories,
            'anatomic_regions': anatomic_regions,
            'model_names': model_names
        })
        
    except requests.RequestException as e:
        return JsonResponse({'success': False, 'error': f'Error fetching API data: {str(e)}'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})
