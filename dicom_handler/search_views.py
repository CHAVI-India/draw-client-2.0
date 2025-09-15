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
        
        # Flatten all structures from all models
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
        
        # Render the table HTML
        table_html = render_to_string('dicom_handler/structures_table.html', {
            'page_obj': page_obj,
            'selected_structures': selected_structures,
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
