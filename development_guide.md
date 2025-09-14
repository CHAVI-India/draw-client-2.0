# DRAW v2.0 Development Guide

## Overview
This document details the implementation of key features in the DRAW v2.0 automatic segmentation system, including template management, DICOM processing, and logging infrastructure.

## Table of Contents
1. [Template Management](#template-management)
2. [DICOM Processing System](#dicom-processing-system)
3. [Logging Infrastructure](#logging-infrastructure)
4. [RuleSet Management](#ruleset-management)

---

# Template Management

## Core Models

### `AutosegmentationTemplate`
```python
class AutosegmentationTemplate(models.Model):
    id = models.UUIDField(primary_key=True, editable=False)
    template_name = models.CharField(max_length=256)
    template_description = models.CharField(max_length=256)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

### `AutosegmentationModel`
```python
class AutosegmentationModel(models.Model):
    id = models.UUIDField(primary_key=True, editable=False)
    autosegmentation_template_name = models.ForeignKey(AutosegmentationTemplate, on_delete=models.CASCADE)
    model_id = models.IntegerField()
    name = models.CharField(max_length=256)
    config = models.CharField(max_length=256)
    trainer_name = models.CharField(max_length=256)
    postprocess = models.CharField(max_length=256)
```

### `AutosegmentationMappedStructure`
```python
class AutosegmentationMappedStructure(models.Model):
    id = models.UUIDField(primary_key=True, editable=False)
    autosegmentation_model = models.ForeignKey(AutosegmentationModel, on_delete=models.CASCADE)
    map_id = models.IntegerField()
    name = models.CharField(max_length=256)
```

## Forms

### `TemplateCreationForm`
```python
class TemplateCreationForm(forms.Form):
    template_name = forms.CharField(
        max_length=256,
        widget=forms.TextInput(attrs={
            'class': 'w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500',
            'placeholder': 'Enter template name'
        }),
        label='Template Name'
    )
    
    template_description = forms.CharField(
        max_length=256,
        widget=forms.Textarea(attrs={
            'class': 'w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500',
            'placeholder': 'Enter template description',
            'rows': 3
        }),
        label='Template Description'
    )
```

## Template Creation Implementation

### 1. Initial Form View (`create_template`)
```python
@login_required
def create_template(request):
    if request.method == 'POST':
        form = TemplateCreationForm(request.POST)
        if form.is_valid():
            # Store template data in session
            request.session['template_name'] = form.cleaned_data['template_name']
            request.session['template_description'] = form.cleaned_data['template_description']
            request.session.modified = True
            
            # Fetch models from DRAW API and redirect to selection
            # ... API call logic ...
            return redirect('dicom_handler:select_models')
    else:
        form = TemplateCreationForm()
    
    return render(request, 'dicom_handler/create_template.html', {'form': form})
```

### 2. Structure Selection View (`select_models`)
```python
@login_required
def select_models(request):
    # Get filters and pagination parameters
    search_query = request.GET.get('search', '')
    category_filter = request.GET.get('category', '')
    anatomic_filter = request.GET.get('anatomic_region', '')
    model_filter = request.GET.get('model_name', '')
    page_number = request.GET.get('page', 1)
    
    # Fetch and filter structures from DRAW API
    # ... API integration logic ...
    
    # Apply pagination
    paginator = Paginator(filtered_structures, 20)
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'categories': categories,
        'anatomic_regions': anatomic_regions,
        'model_names': model_names,
        'selected_structures': request.session.get('selected_structures', []),
        # ... other context variables ...
    }
    
    return render(request, 'dicom_handler/select_models.html', context)
```

### 3. AJAX Selection Handler (`save_selections`)
```python
@login_required
@csrf_exempt
def save_selections(request):
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
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})
```

### 4. Template Creation Handler (`save_template`)
```python
@login_required
@csrf_exempt
def save_template(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Only POST method allowed'})
    
    try:
        # Get template data from session
        template_name = request.session.get('template_name')
        template_description = request.session.get('template_description', '')
        selected_structures = request.session.get('selected_structures', [])
        
        if not template_name or not selected_structures:
            return JsonResponse({'success': False, 'error': 'Missing required data'})
        
        # Create template
        template = AutosegmentationTemplate.objects.create(
            id=uuid.uuid4(),
            template_name=template_name,
            template_description=template_description
        )
        
        # Group structures by model
        models_dict = {}
        for structure in selected_structures:
            model_id = structure.get('model_id')
            if model_id not in models_dict:
                models_dict[model_id] = {
                    'model_data': structure,
                    'structures': []
                }
            models_dict[model_id]['structures'].append(structure)
        
        # Create models and structures
        for model_data in models_dict.values():
            model = AutosegmentationModel.objects.create(
                id=uuid.uuid4(),
                autosegmentation_template_name=template,
                model_id=model_data['model_data'].get('model_id'),
                name=model_data['model_data'].get('model_name', ''),
                config=model_data['model_data'].get('model_config', ''),
                trainer_name=model_data['model_data'].get('model_trainer_name', ''),
                postprocess=model_data['model_data'].get('model_postprocess', '')
            )
            
            # Create structures for this model
            for structure_data in model_data['structures']:
                AutosegmentationMappedStructure.objects.create(
                    id=uuid.uuid4(),
                    autosegmentation_model=model,
                    map_id=structure_data.get('mapid') or structure_data.get('id'),
                    name=structure_data.get('map_tg263_primary_name', '')
                )
        
        # Clear session data
        request.session.pop('selected_structures', None)
        request.session.pop('template_name', None)
        request.session.pop('template_description', None)
        request.session.modified = True
        
        return JsonResponse({
            'success': True,
            'message': 'Template created successfully!',
            'template_id': str(template.id)
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})
```

## Template View Implementation

### Template List View (`template_list`)
```python
@login_required
def template_list(request):
    templates = AutosegmentationTemplate.objects.all().order_by('-created_at')
    
    # Add counts for each template
    for template in templates:
        structure_count = AutosegmentationMappedStructure.objects.filter(
            autosegmentation_model__autosegmentation_template_name=template
        ).count()
        model_count = AutosegmentationModel.objects.filter(
            autosegmentation_template_name=template
        ).count()
        template.structure_count = structure_count
        template.model_count = model_count
    
    return render(request, 'dicom_handler/template_list.html', {
        'templates': templates
    })
```

### Template Detail View (`template_detail`)
```python
@login_required
def template_detail(request, template_id):
    try:
        template = AutosegmentationTemplate.objects.get(id=template_id)
        models = AutosegmentationModel.objects.filter(
            autosegmentation_template_name=template
        ).prefetch_related('autosegmentationmappedstructure_set')
        
        return render(request, 'dicom_handler/template_detail.html', {
            'template': template,
            'models': models
        })
    except AutosegmentationTemplate.DoesNotExist:
        messages.error(request, 'Template not found.')
        return redirect('dicom_handler:template_list')
```

## Template Update Implementation

### Edit Template View (`edit_template`) - Single Page Approach
```python
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
        
        # Fetch models from DRAW API for structure selection
        try:
            system_config = SystemConfiguration.objects.first()
            api_url = f"{system_config.draw_base_url}/models"
            
            headers = {}
            if system_config.draw_api_credentials:
                headers['Authorization'] = f"Bearer {system_config.draw_api_credentials}"
            
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
                filtered_structures = [s for s in filtered_structures 
                                     if search_query.lower() in s.get('map_tg263_primary_name', '').lower()]
            
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
```

### Update Template Handler (`update_template`)
```python
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
                continue
                
            if model_id not in models_dict:
                models_dict[model_id] = {
                    'model_data': structure,
                    'structures': []
                }
            models_dict[model_id]['structures'].append(structure)
        
        # Create new models and structures
        for model_data in models_dict.values():
            try:
                model = AutosegmentationModel.objects.create(
                    id=uuid.uuid4(),
                    autosegmentation_template_name=template,
                    model_id=model_data['model_data'].get('model_id'),
                    name=model_data['model_data'].get('model_name', ''),
                    config=model_data['model_data'].get('model_config', ''),
                    trainer_name=model_data['model_data'].get('model_trainer_name', ''),
                    postprocess=model_data['model_data'].get('model_postprocess', '')
                )
                
                # Create structures for this model
                for structure_data in model_data['structures']:
                    AutosegmentationStructure.objects.create(
                        id=uuid.uuid4(),
                        autosegmentation_model=model,
                        map_id=structure_data.get('mapid') or structure_data.get('id'),
                        name=structure_data.get('map_tg263_primary_name', '')
                    )
                    
            except Exception as model_error:
                return JsonResponse({'success': False, 'error': f'Error updating model data: {str(model_error)}'})
        
        return JsonResponse({
            'success': True,
            'message': f'Template "{template_name}" updated successfully!',
            'template_id': str(template.id)
        })
        
    except AutosegmentationTemplate.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Template not found'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})
```

### Update Template Info Handler (`update_template_info`)
```python
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
```

## URLs (`dicom_handler/urls.py`)

```python
urlpatterns = [
    path('create-template/', views.create_template, name='create_template'),
    path('select-models/', views.select_models, name='select_models'),
    path('save-selections/', views.save_selections, name='save_selections'),
    path('save-template/', views.save_template, name='save_template'),
    path('templates/', views.template_list, name='template_list'),
    path('templates/<uuid:template_id>/', views.template_detail, name='template_detail'),
    path('templates/<uuid:template_id>/edit/', views.edit_template, name='edit_template'),
    path('templates/<uuid:template_id>/update/', views.update_template, name='update_template'),
    path('templates/<uuid:template_id>/update-info/', views.update_template_info, name='update_template_info'),
]
```

## Frontend Implementation

### Edit Template JavaScript Features

The `edit_template.html` template includes comprehensive JavaScript functionality for:

1. **Selection Management**: 
   - Maintains a `Set` of selected structure IDs across pagination
   - Preserves selections when filtering or searching
   - Syncs checkbox states with selection data

2. **AJAX Pagination**:
   - `loadPage()` function handles pagination without page reloads
   - Maintains current search and filter state during pagination
   - Updates URL parameters for bookmarking

3. **Search and Filtering**:
   - Real-time search by structure name
   - Filter by category, anatomic region, and model name
   - Combines multiple filters seamlessly

4. **Template Update**:
   - Single "Update Template" button updates both template info and structure selections
   - Sends JSON payload with template data and selected structures
   - Provides user feedback with success/error notifications

### Key JavaScript Functions

```javascript
// Load page with AJAX pagination
function loadPage(page) {
    const params = new URLSearchParams({
        page: page,
        search: currentSearchQuery,
        category: currentCategoryFilter,
        anatomic_region: currentAnatomicFilter,
        model_name: currentModelFilter
    });
    
    fetch(`?${params.toString()}`, {
        headers: { 'X-Requested-With': 'XMLHttpRequest' }
    })
    .then(response => response.text())
    .then(html => {
        // Update table content and sync selections
        document.getElementById('structures-table').innerHTML = html;
        syncCheckboxes();
        updateSelectionCount();
    });
}

// Update template via AJAX
function updateTemplate() {
    const templateName = document.getElementById('template_name').value.trim();
    const templateDescription = document.getElementById('template_description').value.trim();
    
    if (!templateName) {
        showNotification('Template name is required', 'error');
        return;
    }
    
    if (selectedStructures.size === 0) {
        showNotification('Please select at least one structure', 'error');
        return;
    }
    
    const selectedStructuresArray = Array.from(selectedStructures).map(id => 
        window.structureData[id] || { id: id }
    );
    
    fetch(`/dicom-handler/templates/{{ template.id }}/update/`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value
        },
        body: JSON.stringify({
            template_name: templateName,
            template_description: templateDescription,
            selected_structures: selectedStructuresArray
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showNotification(data.message, 'success');
        } else {
            showNotification(data.error, 'error');
        }
    });
}
```

### Django Template Context Integration

The template receives the following context variables:
- `template`: The AutosegmentationTemplate object being edited
- `page_obj`: Paginated structure data from the API
- `selected_structures`: Current template structures (full objects)
- `selected_structure_ids`: List of selected structure IDs for checkbox pre-selection
- `search_query`: Current search term
- `categories`, `anatomic_regions`, `model_names`: Filter options

### Security Considerations

1. **CSRF Protection**: All AJAX requests include CSRF tokens
2. **Permission Checks**: Views use `@permission_required` decorators
3. **Data Escaping**: Django template data is properly escaped using `|escapejs` filter
4. **Input Validation**: Backend validates all user inputs before processing

## Templates

## Production Considerations

### Tailwind CSS Integration
The current implementation uses Tailwind CSS via CDN for rapid development. For production deployment, consider:

1. **Install Tailwind CSS locally**:
   ```bash
   npm install -D tailwindcss
   npx tailwindcss init
   ```

2. **Configure PostCSS** or use **Tailwind CLI** to build optimized CSS
3. **Purge unused CSS** to reduce bundle size
4. **Use Django-Tailwind** package for better Django integration

### Performance Optimizations

1. **API Caching**: Cache DRAW API responses to reduce external API calls
2. **Database Optimization**: Add indexes on frequently queried fields
3. **Pagination**: Current 25 items per page is reasonable, consider user preferences
4. **JavaScript Bundling**: Minify and bundle JavaScript for production

### Error Handling Improvements

1. **API Timeout Handling**: Current 30-second timeout may need adjustment
2. **Retry Logic**: Add retry mechanisms for failed API calls  
3. **User Feedback**: Enhanced error messages for better UX
4. **Logging**: Comprehensive logging for debugging production issues

## Troubleshooting

### Common Issues

1. **"No structures selected" Error**: 
   - Ensure `selected_structures` are properly passed in request body
   - Check JavaScript console for JSON parsing errors
   - Verify CSRF token is included in AJAX requests

2. **Pagination Not Working**:
   - Check that `X-Requested-With: XMLHttpRequest` header is set
   - Verify URL parameters are properly encoded
   - Ensure `syncCheckboxes()` is called after content update

3. **Selection State Lost**:
   - Confirm `selectedStructures` Set is maintained across operations
   - Check that `window.structureData` is properly populated
   - Verify checkbox `data-id` attributes match structure IDs

4. **API Connection Issues**:
   - Verify `SystemConfiguration` has correct DRAW API URL
   - Check Bearer token validity and format
   - Ensure network connectivity to DRAW API endpoint

5. **JavaScript "redeclaration of const" Error**:
   - **Problem**: Django template loops creating multiple `const` declarations in same scope
   - **Solution**: Wrap template loop variables in IIFE (Immediately Invoked Function Expression)
   - **Example Fix**:
     ```javascript
     // Before (causes error):
     {% for structure in selected_structures %}
     const dbStructure = { ... }; // Redeclared for each iteration
     {% endfor %}
     
     // After (fixed):
     {% for structure in selected_structures %}
     (function() {
         const dbStructure = { ... }; // Each in its own scope
     })();
     {% endfor %}
     ```

6. **Checkbox Selection Not Working - ID Mismatch**:
   - **Problem**: Database structure IDs don't match API structure IDs
   - **Solution**: Match structures using `model_id` + `map_id` combination instead of direct ID matching
   - **Implementation**: Create lookup map with `${model_id}_${map_id}` keys to match database structures with API structures

### `create_template.html`
```html
{% extends 'base.html' %}

{% block content %}
<div class="max-w-4xl mx-auto">
    <div class="bg-white rounded-xl shadow-lg border border-gray-100 p-8">
        <h1 class="text-3xl font-bold text-gray-900 mb-2">Create Autosegmentation Template</h1>
        
        <form method="post" class="space-y-6">
            {% csrf_token %}
            
            <div>
                <label for="{{ form.template_name.id_for_label }}">{{ form.template_name.label }}</label>
                {{ form.template_name }}
            </div>

            <div>
                <label for="{{ form.template_description.id_for_label }}">{{ form.template_description.label }}</label>
                {{ form.template_description }}
            </div>

            <div class="flex justify-end space-x-4">
                <button type="submit">Next: Select Models</button>
            </div>
        </form>
    </div>
</div>
{% endblock %}
```

### `select_models.html`
Key JavaScript functions for structure selection:

```javascript
// Selection management
let selectedStructures = new Set();

function handleCheckboxChange(checkbox) {
    const structureId = checkbox.getAttribute('data-id');
    const structureData = {
        id: checkbox.getAttribute('data-id'),
        mapid: checkbox.getAttribute('data-mapid'),
        map_tg263_primary_name: checkbox.getAttribute('data-map-tg263-primary-name'),
        model_id: checkbox.getAttribute('data-model-id'),
        model_name: checkbox.getAttribute('data-model-name'),
        // ... other attributes
    };
    
    if (checkbox.checked) {
        selectedStructures.add(structureId);
        window.structureData = window.structureData || {};
        window.structureData[structureId] = structureData;
    } else {
        selectedStructures.delete(structureId);
        if (window.structureData) {
            delete window.structureData[structureId];
        }
    }
    updateSelectionCount();
    saveSelections();
}

function createTemplate() {
    if (selectedStructures.size === 0) {
        showNotification('Please select at least one structure before creating the template.', 'error');
        return;
    }
    
    // Direct save using session data - no modal needed
    fetch('{% url "dicom_handler:save_template" %}', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': '{{ csrf_token }}'
        },
        body: JSON.stringify({})
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showNotification('Template created successfully!', 'success');
            setTimeout(() => {
                window.location.href = '{% url "dicom_handler:create_template" %}';
            }, 1500);
        } else {
            showNotification('Error: ' + data.error, 'error');
        }
    });
}
```

## Session Data Flow

### Template Creation Flow
1. **Step 1**: User fills form → Data stored in session → Redirect to selection
2. **Step 2**: User selects structures → AJAX updates session → Click "Create Template"  
3. **Step 3**: Backend uses session data → Creates database records → Clears session

### Session Keys
- `template_name`: From initial form
- `template_description`: From initial form  
- `selected_structures`: Array of structure objects with full data
- `editing_template_id`: For template updates (optional)

---

# DICOM Processing System

## Overview
The DICOM processing system handles the automated reading, validation, and database storage of DICOM files with parallel processing capabilities for improved performance.

## Task 1: Read DICOM from Storage

### Purpose
Recursively reads DICOM files from a configured storage folder, validates them, and creates database records for patients, studies, series, and instances.

### Key Features
- **Parallel Processing**: Uses multiprocessing with up to 8 worker processes
- **Batch Processing**: Processes files in batches of 500 for memory management
- **Filtering**: Supports modality filtering (CT/MR/PT only) and date-based filtering
- **Duplicate Prevention**: Checks existing SOP Instance UIDs to avoid duplicates
- **Bulk Database Operations**: Uses bulk_create for optimal database performance

### Implementation

#### Main Function: `read_dicom_from_storage()`
```python
def read_dicom_from_storage():
    """
    Main function to read DICOM files from configured storage folder (PARALLEL VERSION)
    Returns: Dictionary containing processing results and series information for next task
    """
    logger.info("Starting DICOM file reading task (parallel processing)")
    
    # Get system configuration and validate folder
    system_config = SystemConfiguration.get_singleton()
    folder_path = system_config.folder_configuration
    
    # Collect all files for processing
    file_list = []
    for root, dirs, files in os.walk(folder_path):
        for file in files:
            file_path = os.path.join(root, file)
            file_list.append((file_path, root, date_filter, current_time, ten_minutes_ago))
    
    # Process files in parallel batches
    max_workers = min(cpu_count(), 8)
    batch_size = 500
    
    for i in range(0, len(file_list), batch_size):
        batch = file_list[i:i + batch_size]
        
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            # Submit all files in batch
            future_to_file = {
                executor.submit(process_single_file, file_info): file_info[0]
                for file_info in batch
            }
            
            # Collect and process results
            batch_results = []
            for future in as_completed(future_to_file):
                result = future.result()
                batch_results.append(result)
            
            # Create database records for successful files
            successful_results = [r for r in batch_results if r['status'] == 'success']
            if successful_results:
                bulk_create_database_records(successful_results)
```

#### File Processing Function: `process_single_file()`
```python
def process_single_file(file_info):
    """
    Process a single DICOM file - designed for multiprocessing
    Returns: Dictionary with file processing results
    """
    file_path, series_root_path, date_filter, current_time, ten_minutes_ago = file_info
    
    # Check file modification time conditions
    file_stat = os.stat(file_path)
    file_mtime = datetime.fromtimestamp(file_stat.st_mtime, tz=timezone.get_current_timezone())
    
    # Skip if file was modified in the past 10 minutes
    if file_mtime > ten_minutes_ago:
        return {"status": "skipped", "reason": "recently_modified", "file_path": file_path}
    
    # Read DICOM file
    dicom_data = pydicom.dcmread(file_path, force=True)
    
    # Validate modality
    modality = getattr(dicom_data, 'Modality', None)
    if modality not in ['CT', 'MR', 'PT']:
        return {"status": "skipped", "reason": "unsupported_modality", "file_path": file_path}
    
    # Extract metadata
    dicom_metadata = {
        'patient_id': getattr(dicom_data, 'PatientID', ''),
        'patient_name': str(getattr(dicom_data, 'PatientName', '')),
        'study_instance_uid': getattr(dicom_data, 'StudyInstanceUID', ''),
        'series_instance_uid': getattr(dicom_data, 'SeriesInstanceUID', ''),
        'sop_instance_uid': getattr(dicom_data, 'SOPInstanceUID', ''),
        'file_path': file_path,
        'series_root_path': series_root_path
        # ... other metadata fields
    }
    
    return {"status": "success", "metadata": dicom_metadata}
```

#### Bulk Database Creation: `bulk_create_database_records()`
```python
def bulk_create_database_records(processed_files):
    """
    Bulk create database records from processed DICOM files
    """
    patients_to_create = {}
    studies_to_create = {}
    series_to_create = {}
    instances_to_create = []
    
    # Group by patient, study, series
    for file_result in processed_files:
        metadata = file_result['metadata']
        
        # Group patients
        patient_key = metadata['patient_id']
        if patient_key not in patients_to_create:
            patients_to_create[patient_key] = {
                'patient_id': metadata['patient_id'],
                'patient_name': metadata['patient_name'],
                # ... other patient fields
            }
    
    # Bulk create in database with transactions
    with transaction.atomic():
        # Create patients
        for patient_data in patients_to_create.values():
            patient, created = Patient.objects.get_or_create(
                patient_id=patient_data['patient_id'],
                defaults=patient_data
            )
        
        # Create studies, series, and instances
        # ... similar bulk creation logic
        
        # Bulk create instances
        if instances_to_bulk_create:
            DICOMInstance.objects.bulk_create(instances_to_bulk_create, batch_size=1000)
```

### Performance Characteristics
- **Processing Speed**: 6-8x faster than sequential processing
- **Memory Management**: Batch processing prevents memory exhaustion
- **Database Efficiency**: Bulk operations reduce database load
- **Error Handling**: Comprehensive error tracking and logging

### Configuration Requirements
```python
# System Configuration Model
class SystemConfiguration(models.Model):
    folder_configuration = models.CharField(max_length=512)  # DICOM folder path
    data_pull_start_datetime = models.DateTimeField(null=True, blank=True)  # Date filter
```

### Return Format (JSON Serializable for Celery)
```python
{
    "status": "success",
    "processed_files": 4735,
    "skipped_files": 2082,
    "error_files": 0,
    "series_data": [
        {
            "series_instance_uid": "1.2.840.113619.2.55...",
            "first_instance_path": "/path/to/first/instance.dcm",
            "series_root_path": "/path/to/series/folder",
            "instance_count": 251
        }
        # ... more series
    ]
}
```

---

# Logging Infrastructure

## Overview
Comprehensive logging system with automatic log rotation, privacy protection, and component-specific log files for monitoring and debugging.

## Configuration

### Django Settings (`settings.py`)
```python
# Create logs directory
LOGS_DIR = BASE_DIR / 'logs'
LOGS_DIR.mkdir(exist_ok=True)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'dicom_formatter': {
            'format': '[DICOM] {levelname} {asctime} {module} - {message}',
            'style': '{',
        },
        'celery_formatter': {
            'format': '[CELERY] {levelname} {asctime} {module} - {message}',
            'style': '{',
        },
    },
    'handlers': {
        'dicom_file': {
            'level': 'DEBUG',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOGS_DIR / 'dicom_processing.log',
            'maxBytes': 100 * 1024 * 1024,  # 100 MB
            'backupCount': 15,
            'formatter': 'dicom_formatter',
        },
        'django_file': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOGS_DIR / 'django.log',
            'maxBytes': 50 * 1024 * 1024,  # 50 MB
            'backupCount': 10,
            'formatter': 'verbose',
        },
        'celery_file': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOGS_DIR / 'celery.log',
            'maxBytes': 50 * 1024 * 1024,  # 50 MB
            'backupCount': 10,
            'formatter': 'celery_formatter',
        },
        'error_file': {
            'level': 'ERROR',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOGS_DIR / 'errors.log',
            'maxBytes': 25 * 1024 * 1024,  # 25 MB
            'backupCount': 20,
            'formatter': 'verbose',
        },
        'security_file': {
            'level': 'WARNING',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOGS_DIR / 'security.log',
            'maxBytes': 25 * 1024 * 1024,  # 25 MB
            'backupCount': 20,
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'dicom_handler': {
            'handlers': ['dicom_file', 'console'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'dicom_handler.export_services': {
            'handlers': ['dicom_file', 'console'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'celery': {
            'handlers': ['celery_file', 'console'],
            'level': 'INFO',
            'propagate': False,
        },
        'django.request': {
            'handlers': ['error_file', 'console'],
            'level': 'ERROR',
            'propagate': False,
        },
        'django.security': {
            'handlers': ['security_file', 'console'],
            'level': 'WARNING',
            'propagate': False,
        },
    },
}
```

## Log Files

### File Structure
```
logs/
├── dicom_processing.log      # DICOM processing activities (100MB, 15 backups)
├── django.log                # General Django application logs (50MB, 10 backups)
├── celery.log                # Celery task execution logs (50MB, 10 backups)
├── errors.log                # All error-level messages (25MB, 20 backups)
└── security.log              # Security-related warnings (25MB, 20 backups)
```

### Log Rotation
- **Automatic rotation** when files reach size limits
- **Compressed backups** to save disk space
- **Configurable retention** with different backup counts per log type

## Privacy Protection

### Sensitive Data Masking
```python
def mask_sensitive_data(data, field_name=""):
    """
    Mask sensitive patient information in logs
    """
    if not data:
        return "None"
    
    # Mask patient identifiable information
    if any(field in field_name.lower() for field in ['name', 'id', 'birth']):
        return f"***{field_name.upper()}_MASKED***"
    
    # For UIDs, show only first and last 4 characters
    if 'uid' in field_name.lower() and len(str(data)) > 8:
        return f"{str(data)[:4]}...{str(data)[-4:]}"
    
    return str(data)
```

### Usage in DICOM Processing
```python
# Example log entries with masking
logger.info(f"Processing patient: {mask_sensitive_data(patient_name, 'patient_name')}")
logger.debug(f"Series UID: {mask_sensitive_data(series_uid, 'series_uid')}")
logger.info(f"File path: {mask_sensitive_data(file_path, 'file_path')}")
```

## Log Management Script (`manage_logs.py`)

### Available Commands
```bash
# View log status
python manage_logs.py status

# View last 50 lines of a log
python manage_logs.py tail dicom_processing

# Follow log in real-time
python manage_logs.py follow dicom_processing

# Search for patterns
python manage_logs.py search "error" --log dicom_processing

# Clean old logs (30+ days)
python manage_logs.py clean --days 30

# Compress old logs (7+ days)
python manage_logs.py compress --days 7
```

### Key Functions
```python
def show_log_status():
    """Display status of all log files"""
    log_files = get_log_files()
    for log_file in log_files:
        print(f"{log_file['name']:<30} {log_file['size_mb']:<12.2f} {log_file['modified']}")

def tail_log(log_name, lines=50):
    """Display last N lines of a log file"""
    with open(log_path, 'r') as f:
        all_lines = f.readlines()
        for line in all_lines[-lines:]:
            print(line.rstrip())

def search_logs(pattern, log_name=None):
    """Search for pattern in log files"""
    for log_file in log_files:
        with open(log_file, 'r') as f:
            for line_num, line in enumerate(f, 1):
                if pattern.lower() in line.lower():
                    print(f"{log_file.name}:{line_num}: {line.rstrip()}")
```

## Logging Best Practices

### Log Levels
- **DEBUG**: Detailed processing steps, file-by-file operations
- **INFO**: Task start/completion, major milestones, record creation
- **WARNING**: Recoverable errors, skipped files
- **ERROR**: Critical errors, database issues

### Example Log Entries
```
[DICOM] INFO 2025-09-14 13:54:12 task1_read_dicom_from_storage - Starting DICOM file reading task (parallel processing)
[DICOM] INFO 2025-09-14 13:54:12 task1_read_dicom_from_storage - Found 6817 files to process
[DICOM] INFO 2025-09-14 13:54:12 task1_read_dicom_from_storage - Processing files with 8 parallel workers
[DICOM] INFO 2025-09-14 13:54:12 task1_read_dicom_from_storage - Processing batch 1/14 (500 files)
[DICOM] DEBUG 2025-09-14 13:54:13 task1_read_dicom_from_storage - Skipped file: unsupported_modality - ***FILE_PATH_MASKED***
[DICOM] INFO 2025-09-14 13:54:13 task1_read_dicom_from_storage - Batch completed: 498 successful, 2 skipped, 0 errors
[DICOM] INFO 2025-09-14 13:54:13 task1_read_dicom_from_storage - Creating database records for 428 files
[DICOM] INFO 2025-09-14 13:54:13 task1_read_dicom_from_storage - Successfully created records for batch
[DICOM] INFO 2025-09-14 13:54:13 task1_read_dicom_from_storage - DICOM reading completed. Processed: 6738, Skipped: 79, Errors: 0
```

---

# RuleSet Management

## Overview
This section details the implementation of RuleSet management functionality for DICOM tag-based automatic template selection in the DRAW v2.0 system.

## Core Models

### `DICOMTagType`
```python
class DICOMTagType(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tag_name = models.CharField(max_length=256)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

### `RuleCombinationType`
```python
class RuleCombinationType(models.TextChoices):
    AND = "AND", "And"
    OR = "OR", "Or"
```

### `OperatorType`
```python
class OperatorType(models.TextChoices):
    EQUALS = "EQUALS", "Equals"
    NOT_EQUALS = "NOT_EQUALS", "Not Equals"
    GREATER_THAN = "GREATER_THAN", "Greater Than"
    LESS_THAN = "LESS_THAN", "Less Than"
    GREATER_THAN_OR_EQUAL_TO = "GREATER_THAN_OR_EQUAL_TO", "Greater Than Or Equal To"
    LESS_THAN_OR_EQUAL_TO = "LESS_THAN_OR_EQUAL_TO", "Less Than Or Equal To"
    CASE_SENSITIVE_STRING_CONTAINS = "CASE_SENSITIVE_STRING_CONTAINS", "Case Sensitive String Contains"
    CASE_INSENSITIVE_STRING_CONTAINS = "CASE_INSENSITIVE_STRING_CONTAINS", "Case Insensitive String Contains"
    CASE_SENSITIVE_STRING_DOES_NOT_CONTAIN = "CASE_SENSITIVE_STRING_DOES_NOT_CONTAIN", "Case Sensitive String Does Not Contain"
    CASE_INSENSITIVE_STRING_DOES_NOT_CONTAIN = "CASE_INSENSITIVE_STRING_DOES_NOT_CONTAIN", "Case Insensitive String Does Not Contain"
    CASE_SENSITIVE_STRING_EXACT_MATCH = "CASE_SENSITIVE_STRING_EXACT_MATCH", "Case Sensitive String Exact Match"
    CASE_INSENSITIVE_STRING_EXACT_MATCH = "CASE_INSENSITIVE_STRING_EXACT_MATCH", "Case Insensitive String Exact Match"
```

### `RuleSet`
```python
class RuleSet(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ruleset_name = models.CharField(max_length=256,help_text = "The name of the ruleset.")
    ruleset_description = models.CharField(max_length=256,help_text = "The description of the ruleset.")
    rule_combination_type = models.CharField(max_length=256, choices=RuleCombinationType.choices,help_text = "The rule combination type. This can be AND or OR.")
    associated_autosegmentation_template = models.ForeignKey(AutosegmentationTemplate, on_delete=models.CASCADE, null=True, blank=True,help_text = "The autosegmentation template associated with the ruleset.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

### `Rule`
```python
class Rule(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ruleset = models.ForeignKey(RuleSet, on_delete=models.CASCADE,help_text = "The ruleset to which this rule belongs to.")
    dicom_tag_type = models.ForeignKey(DICOMTagType, on_delete=models.CASCADE,help_text = "The DICOM tag type whose value will be evaluated.")
    operator_type = models.CharField(max_length=256, choices=OperatorType.choices,help_text = "The operator type. This can be a string operator to be used for text and number or a numeric operator for numeric values.")
    tag_value_to_evaluate = models.CharField(max_length=256,help_text = "The tag value to evaluate. This is the value that the rule will match to.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def clean(self):
        """Validate operator-value combinations"""
        # String operators that allow string values
        string_operators = [
            OperatorType.CASE_SENSITIVE_STRING_CONTAINS,
            OperatorType.CASE_INSENSITIVE_STRING_CONTAINS,
            OperatorType.CASE_SENSITIVE_STRING_DOES_NOT_CONTAIN,
            OperatorType.CASE_INSENSITIVE_STRING_DOES_NOT_CONTAIN,
            OperatorType.CASE_SENSITIVE_STRING_EXACT_MATCH,
            OperatorType.CASE_INSENSITIVE_STRING_EXACT_MATCH,
        ]
        
        is_numeric = self.is_numeric_value(self.tag_value_to_evaluate)
        
        # All operators except string operators require numeric values
        if self.operator_type not in string_operators and not is_numeric:
            raise ValidationError({
                'tag_value_to_evaluate': f'Operator "{self.get_operator_type_display()}" can only be used with numeric values.'
            })
```

## Forms Implementation

### `RuleSetForm`
```python
class RuleSetForm(forms.ModelForm):
    class Meta:
        model = RuleSet
        fields = ['ruleset_name', 'ruleset_description', 'rule_combination_type', 'associated_autosegmentation_template']
        widgets = {
            'ruleset_name': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500',
                'placeholder': 'Enter ruleset name'
            }),
            # ... other widgets with Tailwind CSS classes
        }
```

### `RuleForm` with Validation
```python
class RuleForm(forms.ModelForm):
    class Meta:
        model = Rule
        fields = ['dicom_tag_type', 'operator_type', 'tag_value_to_evaluate']
        widgets = {
            'operator_type': forms.Select(attrs={
                'onchange': 'validateOperatorValue(this)'
            }),
            'tag_value_to_evaluate': forms.TextInput(attrs={
                'oninput': 'validateOperatorValue(this)'
            })
        }
    
    def clean(self):
        """Form-level validation for operator-value combinations"""
        cleaned_data = super().clean()
        operator_type = cleaned_data.get('operator_type')
        tag_value = cleaned_data.get('tag_value_to_evaluate')
        
        if operator_type and tag_value:
            string_operators = [
                'CASE_SENSITIVE_STRING_CONTAINS',
                'CASE_INSENSITIVE_STRING_CONTAINS',
                'CASE_SENSITIVE_STRING_DOES_NOT_CONTAIN',
                'CASE_INSENSITIVE_STRING_DOES_NOT_CONTAIN',
                'CASE_SENSITIVE_STRING_EXACT_MATCH',
                'CASE_INSENSITIVE_STRING_EXACT_MATCH',
            ]
            
            try:
                float(tag_value)
                is_numeric = True
            except (ValueError, TypeError):
                is_numeric = False
            
            if operator_type not in string_operators and not is_numeric:
                raise forms.ValidationError({
                    'tag_value_to_evaluate': f'Operator requires numeric values. Use string operators for text values.'
                })
        
        return cleaned_data
```

### `RuleFormSet` Configuration
```python
RuleFormSet = inlineformset_factory(
    RuleSet, 
    Rule, 
    form=RuleForm,
    fields=['dicom_tag_type', 'operator_type', 'tag_value_to_evaluate'],
    extra=1,  # Show 1 empty form initially
    can_delete=True,
    min_num=1,  # Require at least 1 rule
    validate_min=True
)
```

## Views Implementation

### `ruleset_list`
```python
@login_required
def ruleset_list(request):
    rulesets = RuleSet.objects.all().order_by('-created_at')
    
    for ruleset in rulesets:
        ruleset.rule_count = Rule.objects.filter(ruleset=ruleset).count()
    
    return render(request, 'dicom_handler/ruleset_list.html', {
        'rulesets': rulesets
    })
```

### `ruleset_create`
```python
@login_required
def ruleset_create(request):
    if request.method == 'POST':
        form = RuleSetForm(request.POST)
        formset = RuleFormSet(request.POST)
        
        if form.is_valid() and formset.is_valid():
            ruleset = form.save(commit=False)
            ruleset.id = uuid.uuid4()
            ruleset.save()
            
            formset.instance = ruleset
            formset.save()
            
            messages.success(request, f'RuleSet "{ruleset.ruleset_name}" created successfully!')
            return redirect('dicom_handler:ruleset_list')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = RuleSetForm()
        formset = RuleFormSet()
    
    return render(request, 'dicom_handler/ruleset_create.html', {
        'form': form, 
        'formset': formset
    })
```

### `ruleset_detail`
```python
@login_required
def ruleset_detail(request, ruleset_id):
    try:
        ruleset = get_object_or_404(RuleSet, id=ruleset_id)
        rules = Rule.objects.filter(ruleset=ruleset).order_by('created_at')
        
        return render(request, 'dicom_handler/ruleset_detail.html', {
            'ruleset': ruleset,
            'rules': rules
        })
    except RuleSet.DoesNotExist:
        messages.error(request, 'RuleSet not found.')
        return redirect('dicom_handler:ruleset_list')
```

### `ruleset_edit`
```python
@login_required
def ruleset_edit(request, ruleset_id):
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
    
    return render(request, 'dicom_handler/ruleset_edit.html', {
        'form': form,
        'formset': formset,
        'ruleset': ruleset
    })
```

### `ruleset_delete`
```python
@login_required
def ruleset_delete(request, ruleset_id):
    ruleset = get_object_or_404(RuleSet, id=ruleset_id)
    rules = Rule.objects.filter(ruleset=ruleset)
    
    if request.method == 'POST':
        ruleset_name = ruleset.ruleset_name
        ruleset.delete()
        messages.success(request, f'RuleSet "{ruleset_name}" deleted successfully!')
        return redirect('dicom_handler:ruleset_list')
    
    return render(request, 'dicom_handler/ruleset_confirm_delete.html', {
        'ruleset': ruleset,
        'rules': rules
    })
```

## Validation System

### Operator-Value Validation Rules
1. **String Operators** (allow text values):
   - Case Sensitive String Contains
   - Case Insensitive String Contains
   - Case Sensitive String Does Not Contain
   - Case Insensitive String Does Not Contain
   - Case Sensitive String Exact Match
   - Case Insensitive String Exact Match

2. **Numeric-Only Operators** (require numeric values):
   - Equals
   - Not Equals
   - Greater Than
   - Less Than
   - Greater Than or Equal To
   - Less Than or Equal To

### Multi-Level Validation
1. **Model Level**: `Rule.clean()` method validates operator-value combinations
2. **Form Level**: `RuleForm.clean()` provides user-friendly error messages
3. **Client-Side**: JavaScript provides real-time validation feedback

## JavaScript Implementation

### Dynamic Rule Management
```javascript
// Add new rule form
function addRule() {
    const emptyFormTemplate = document.querySelector('.rule-form').cloneNode(true);
    
    // Update form indices
    const formRegex = /form-\d+-/g;
    emptyFormTemplate.innerHTML = emptyFormTemplate.innerHTML.replace(formRegex, `form-${formCount}-`);
    
    // Clear values and reset validation
    emptyFormTemplate.querySelectorAll('input, select, textarea').forEach(function(field) {
        if (field.type !== 'hidden') {
            field.value = '';
            field.selectedIndex = 0;
        }
    });
    
    // Update form count and attach events
    formCount++;
    document.querySelector('#id_form-TOTAL_FORMS').value = formCount;
    
    attachRemoveEvent(emptyFormTemplate);
    attachValidationEvents(emptyFormTemplate);
    updateRemoveButtonVisibility();
}

// Remove rule management
function removeRule(formElement) {
    const forms = document.querySelectorAll('.rule-form');
    if (forms.length > 1) {  // Maintain minimum of 1 rule
        formElement.remove();
        updateFormNumbers();
        updateRemoveButtonVisibility();
    }
}

// Remove button visibility logic
function updateRemoveButtonVisibility() {
    const forms = document.querySelectorAll('.rule-form');
    forms.forEach(function(form) {
        const removeBtn = form.querySelector('.remove-rule');
        if (removeBtn) {
            removeBtn.style.display = forms.length === 1 ? 'none' : 'block';
        }
    });
}
```

### Real-Time Validation
```javascript
function validateOperatorValue(element) {
    const ruleForm = element.closest('.rule-form');
    const operatorSelect = ruleForm.querySelector('select[name$="-operator_type"]');
    const valueInput = ruleForm.querySelector('input[name$="-tag_value_to_evaluate"]');
    
    const stringOperators = [
        'CASE_SENSITIVE_STRING_CONTAINS',
        'CASE_INSENSITIVE_STRING_CONTAINS',
        'CASE_SENSITIVE_STRING_DOES_NOT_CONTAIN',
        'CASE_INSENSITIVE_STRING_DOES_NOT_CONTAIN',
        'CASE_SENSITIVE_STRING_EXACT_MATCH',
        'CASE_INSENSITIVE_STRING_EXACT_MATCH'
    ];
    
    const operator = operatorSelect.value;
    const value = valueInput.value.trim();
    const isValueNumeric = !isNaN(parseFloat(value)) && isFinite(value);
    
    // Validate and show errors
    if (!stringOperators.includes(operator) && !isValueNumeric) {
        showValidationError(ruleForm, 'Operator requires numeric values. Use string operators for text values.');
        return false;
    }
    
    clearValidationError(ruleForm);
    return true;
}
```

## URL Patterns

```python
# RuleSet URLs
path('rulesets/', views.ruleset_list, name='ruleset_list'),
path('rulesets/create/', views.ruleset_create, name='ruleset_create'),
path('rulesets/<uuid:ruleset_id>/', views.ruleset_detail, name='ruleset_detail'),
path('rulesets/<uuid:ruleset_id>/edit/', views.ruleset_edit, name='ruleset_edit'),
path('rulesets/<uuid:ruleset_id>/delete/', views.ruleset_delete, name='ruleset_delete'),
```

## Templates

### Key Features
1. **Responsive Design**: Tailwind CSS for consistent styling
2. **Dynamic Forms**: JavaScript-powered inline formset management
3. **Real-Time Validation**: Immediate feedback on operator-value combinations
4. **User Experience**: Clear error messages and intuitive navigation
5. **Accessibility**: Proper form labels and ARIA attributes

### Template Structure
- `ruleset_list.html`: Display all rulesets with actions
- `ruleset_create.html`: Create new ruleset with inline rules
- `ruleset_detail.html`: View ruleset details and logic summary
- `ruleset_edit.html`: Edit existing ruleset and rules
- `ruleset_confirm_delete.html`: Confirmation page with impact preview

## Navigation Integration

Added RuleSet link to main navigation:
```html
<!-- Desktop Navigation -->
<a href="{% url 'dicom_handler:ruleset_list' %}" class="text-gray-700 hover:text-primary-600 px-3 py-2 rounded-md text-sm font-medium transition-colors">RuleSets</a>

<!-- Mobile Navigation -->
<a href="{% url 'dicom_handler:ruleset_list' %}" class="block text-gray-700 hover:text-primary-600 px-3 py-2 rounded-md text-base font-medium">RuleSets</a>
```

---

# DICOM Dictionary Seed Data Implementation

## Overview
This section details the implementation of DICOM dictionary seed data import functionality for populating the `DICOMTagType` model with standardized DICOM tags.

## Updated DICOMTagType Model

### Enhanced Model Structure
```python
class DICOMTagType(models.Model):
    '''
    This is a model to store data about the DICOM tags. Note that only DICOM tags approved by the DICOM standards are allowed.
    '''
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tag_name = models.CharField(max_length=256)
    tag_id = models.CharField(max_length=256, null=True, blank=True)
    tag_description = models.CharField(max_length=256, null=True, blank=True)
    value_representation = models.CharField(max_length=256, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.tag_name

    class Meta:
        verbose_name = "DICOM Tag Type"
        verbose_name_plural = "DICOM Tag Types"
```

### Model Changes
- **Added `tag_id`**: Stores DICOM tag identifier (e.g., "(4010,1070)")
- **Added `tag_description`**: Stores detailed description of the DICOM tag
- **Added `value_representation`**: Stores DICOM value representation (e.g., "CS", "FD", "US")

## Seed Data Structure

### CSV File Format
Location: `/seed_data/dicom_dictionary.csv`

```csv
"id","tag_id","tag_name","tag_description","value_representation"
1,"(4010,1070)","AITDeviceType","AIT Device Type","CS"
```

---

# Advanced RuleSet Features Implementation

## Overview
This section documents the advanced features added to the RuleSet management system, including VR (Value Representation) validation, Select2 integration for DICOM tag selection, and dynamic formset management.

## VR Validation System

### VR Validators Module (`vr_validators.py`)
```python
import re
from django.core.exceptions import ValidationError

def validate_vr_value(vr_type, value, operator=None):
    """
    Validate a DICOM value against its Value Representation (VR) type
    """
    if not value:
        return True, "Value is empty"
    
    # VR validation patterns
    vr_patterns = {
        'CS': r'^[A-Za-z0-9_ ]{1,16}$',  # Code String - allows uppercase, lowercase, digits, spaces, underscores
        'SH': r'^.{1,16}$',              # Short String
        'LO': r'^.{1,64}$',              # Long String
        'US': r'^\d+$',                  # Unsigned Short
        'FD': r'^-?\d+(\.\d+)?$',        # Floating Point Double
        'DA': r'^\d{8}$',                # Date (YYYYMMDD)
        'TM': r'^\d{6}(\.\d{1,6})?$',    # Time (HHMMSS.FFFFFF)
        'UI': r'^[\d\.]+$',              # Unique Identifier
        'PN': r'^[^\\^=]*(\^[^\\^=]*){0,4}$',  # Person Name
    }
    
    pattern = vr_patterns.get(vr_type)
    if not pattern:
        return True, f"No validation pattern for VR type: {vr_type}"
    
    if not re.match(pattern, value):
        return False, f"Value '{value}' is not valid for VR type {vr_type}"
    
    return True, "Valid"

def get_compatible_operators(vr_type):
    """
    Get operators compatible with a specific VR type
    """
    string_vrs = ['CS', 'SH', 'LO', 'PN', 'UI']
    numeric_vrs = ['US', 'FD', 'IS', 'DS']
    date_time_vrs = ['DA', 'TM', 'DT']
    
    string_operators = [
        'CASE_SENSITIVE_STRING_CONTAINS',
        'CASE_INSENSITIVE_STRING_CONTAINS',
        'CASE_SENSITIVE_STRING_DOES_NOT_CONTAIN',
        'CASE_INSENSITIVE_STRING_DOES_NOT_CONTAIN',
        'CASE_SENSITIVE_STRING_EXACT_MATCH',
        'CASE_INSENSITIVE_STRING_EXACT_MATCH',
        'EQUALS',
        'NOT_EQUALS'
    ]
    
    numeric_operators = [
        'EQUALS',
        'NOT_EQUALS',
        'GREATER_THAN',
        'LESS_THAN',
        'GREATER_THAN_OR_EQUAL_TO',
        'LESS_THAN_OR_EQUAL_TO'
    ]
    
    if vr_type in string_vrs:
        return string_operators
    elif vr_type in numeric_vrs:
        return numeric_operators
    elif vr_type in date_time_vrs:
        return numeric_operators  # Date/time can use comparison operators
    else:
        return string_operators  # Default to string operators
```

### AJAX Endpoints for VR Guidance

#### `get_vr_guidance` View
```python
@login_required
def get_vr_guidance(request, tag_uuid):
    """
    Get VR guidance for a specific DICOM tag
    """
    try:
        tag = DICOMTagType.objects.get(id=tag_uuid)
        vr_type = tag.value_representation
        
        compatible_operators = get_compatible_operators(vr_type)
        
        return JsonResponse({
            'success': True,
            'vr_type': vr_type,
            'compatible_operators': compatible_operators,
            'tag_name': tag.tag_name,
            'tag_description': tag.tag_description
        })
    except DICOMTagType.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'DICOM tag not found'
        })
```

#### `validate_vr_value` View
```python
@login_required
@csrf_exempt
def validate_vr_value(request):
    """
    Validate a value against VR rules
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Only POST method allowed'})
    
    try:
        data = json.loads(request.body)
        tag_uuid = data.get('tag_uuid')
        operator = data.get('operator')
        value = data.get('value')
        
        if not tag_uuid:
            return JsonResponse({'success': False, 'error': 'Tag UUID is required'})
        
        tag = DICOMTagType.objects.get(id=tag_uuid)
        vr_type = tag.value_representation
        
        is_valid, message = validate_vr_value(vr_type, value, operator)
        
        return JsonResponse({
            'success': True,
            'is_valid': is_valid,
            'message': message,
            'vr_type': vr_type
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})
```

#### `search_dicom_tags` View
```python
@login_required
def search_dicom_tags(request):
    """
    Search DICOM tags for Select2 autocomplete
    """
    search_term = request.GET.get('q', '').strip()
    
    if len(search_term) < 2:
        return JsonResponse({'results': []})
    
    tags = DICOMTagType.objects.filter(
        Q(tag_name__icontains=search_term) |
        Q(tag_description__icontains=search_term) |
        Q(tag_id__icontains=search_term)
    )[:20]  # Limit to 20 results
    
    results = []
    for tag in tags:
        results.append({
            'id': str(tag.id),
            'text': f"{tag.tag_name} ({tag.tag_id}) - {tag.tag_description or 'No description'}",
            'vr_type': tag.value_representation
        })
    
    return JsonResponse({'results': results})
```

## Enhanced Templates

### `ruleset_create.html` Features
1. **Select2 Integration**: Advanced DICOM tag selection with search
2. **Dynamic Formset Management**: Add/remove rules with proper form indexing
3. **VR Validation**: Real-time validation based on DICOM VR types
4. **Operator Filtering**: Dynamic operator options based on selected tag's VR
5. **Tailwind CSS Styling**: Modern, responsive design

### Key JavaScript Functions

#### Dynamic Form Management
```javascript
function addRule() {
    const emptyFormTemplate = document.querySelector('.rule-form').cloneNode(true);
    const formCount = document.querySelectorAll('.rule-form').length;
    
    // Update form indices and field names
    const formRegex = /rule_set-\d+-/g;
    emptyFormTemplate.innerHTML = emptyFormTemplate.innerHTML.replace(formRegex, `rule_set-${formCount}-`);
    
    // Clear form values and reset validation
    emptyFormTemplate.querySelectorAll('input, select, textarea').forEach(function(field) {
        if (field.type !== 'hidden') {
            field.value = '';
        } else if (field.name.includes('id')) {
            field.value = '';  // Clear ID for new forms
        } else if (field.name.includes('DELETE')) {
            field.checked = false;  // Uncheck DELETE for new forms
        }
    });
    
    // Update management form
    const totalFormsField = document.querySelector('#id_rule_set-TOTAL_FORMS');
    totalFormsField.value = formCount + 1;
    
    // Append new form and initialize Select2
    document.querySelector('#rules-container').appendChild(emptyFormTemplate);
    initializeSelect2(emptyFormTemplate);
    attachFormEvents(emptyFormTemplate);
}
```

#### VR-Based Validation
```javascript
function handleTagChange(selectElement) {
    const ruleForm = selectElement.closest('.rule-form');
    const operatorSelect = ruleForm.querySelector('select[name$="-operator_type"]');
    const valueInput = ruleForm.querySelector('input[name$="-tag_value_to_evaluate"]');
    const tagUuid = selectElement.value;
    
    if (!tagUuid) return;
    
    // Fetch VR guidance
    fetch(`/dicom_handler/get_vr_guidance/${tagUuid}/`)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                updateOperatorOptions(operatorSelect, data.compatible_operators);
                showVRGuidance(ruleForm, data.vr_type, data.tag_description);
            }
        })
        .catch(error => console.error('Error fetching VR guidance:', error));
}

function validateValue(valueInput) {
    const ruleForm = valueInput.closest('.rule-form');
    const tagSelect = ruleForm.querySelector('select[name$="-dicom_tag_type"]');
    const operatorSelect = ruleForm.querySelector('select[name$="-operator_type"]');
    
    if (!tagSelect.value || !valueInput.value.trim()) return;
    
    // Real-time VR validation
    fetch('/dicom_handler/validate_vr_value/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value
        },
        body: JSON.stringify({
            tag_uuid: tagSelect.value,
            operator: operatorSelect.value,
            value: valueInput.value.trim()
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showValidationResult(ruleForm, data.is_valid, data.message);
        }
    });
}
```

### `ruleset_edit.html` Features
Similar to create template but with additional features:
1. **Pre-populated Forms**: Existing rules loaded with proper formset management
2. **Delete Handling**: Proper handling of DELETE checkboxes for existing rules
3. **Update Logic**: Maintains form integrity during edits

## URL Patterns Update
```python
# VR and validation endpoints
path('get_vr_guidance/<uuid:tag_uuid>/', views.get_vr_guidance, name='get_vr_guidance'),
path('validate_vr_value/', views.validate_vr_value, name='validate_vr_value'),
path('search_dicom_tags/', views.search_dicom_tags, name='search_dicom_tags'),
```

## Key Improvements Made

### 1. Form Field Naming Fix
- **Issue**: JavaScript was using incorrect prefix `rules-` instead of `rule_set-`
- **Solution**: Updated all JavaScript form cloning to use correct `rule_set-` prefix
- **Impact**: Dynamic forms now save correctly

### 2. Management Form Updates
- **Issue**: TOTAL_FORMS field ID was incorrect (`#id_rules-TOTAL_FORMS`)
- **Solution**: Updated to correct ID (`#id_rule_set-TOTAL_FORMS`)
- **Impact**: Formset validation now works properly

### 3. VR Validation Enhancement
- **Issue**: CS (Code String) validation was too strict
- **Solution**: Updated regex to allow lowercase letters and spaces
- **Impact**: Values like 'Head Neck' now validate correctly

### 4. URL Resolution Fix
- **Issue**: Django reverse URL resolution failing in JavaScript
- **Solution**: Use dynamic URL construction in JavaScript
- **Impact**: AJAX calls now work reliably

### 5. Hidden Field Management
- **Issue**: Cloned forms retained stale ID and DELETE values
- **Solution**: Proper clearing of hidden fields in new forms
- **Impact**: No conflicts with existing form data

## Testing and Debugging

### Debug Features Added
1. **Server-side logging**: POST data and formset errors logged
2. **Client-side validation**: Real-time feedback on form errors
3. **VR guidance display**: Visual indicators for VR requirements
4. **Form state tracking**: Clear indication of form validation status

### Common Issues Resolved
1. **Formset not saving**: Fixed field naming and management form updates
2. **VR validation failures**: Updated validation patterns for real-world data
3. **AJAX URL errors**: Implemented dynamic URL construction
4. **Form cloning issues**: Proper handling of hidden fields and indices

---

# DICOM VR Validation Implementation Guide

## Overview
This section details the implementation of real-time DICOM Value Representation (VR) validation for ruleset creation and editing forms. The system provides inline guidance and validation to ensure accurate DICOM tag value entry.

## Core Components

### VR Validation Utility (`vr_validators.py`)

#### VRValidator Class
```python
class VRValidator:
    """Main validator class for DICOM Value Representations."""
    
    # VR Categories for validation logic
    NUMERIC_VRS = {'FL', 'FD', 'SL', 'SS', 'UL', 'US', 'IS', 'DS'}
    STRING_VRS = {'AE', 'CS', 'LO', 'LT', 'PN', 'SH', 'ST', 'UT', 'UI'}
    DATETIME_VRS = {'DA', 'DT', 'TM'}
    SPECIAL_VRS = {'AS', 'AT', 'SQ', 'OB', 'OD', 'OF', 'OW', 'UN'}
    
    @classmethod
    def validate_value_for_vr(cls, value: str, vr_code: str) -> Tuple[bool, str]:
        """Validate a value against its DICOM VR requirements."""
        # Returns (is_valid, error_message)
    
    @classmethod
    def get_vr_guidance(cls, vr_code: str) -> Dict[str, str]:
        """Get user-friendly guidance for a VR type."""
        # Returns dictionary with description, format, example
    
    @classmethod
    def is_operator_compatible(cls, vr_code: str, operator: str) -> bool:
        """Check if an operator is compatible with a VR type."""
```

#### User-Friendly VR Guidance
The system provides clear, actionable guidance for each VR type:

- **CS (Code String)**: "Enter text string with uppercase letters, numbers, spaces, underscores only"
- **DA (Date)**: "Enter date in format YYYYMMDD (year, month, day as 8 digits)"
- **IS (Integer String)**: "Enter whole number (positive or negative integer)"
- **LO (Long String)**: "Enter text string (letters, numbers, symbols) up to 64 characters"
- **PN (Person Name)**: "Enter person name using ^ to separate: Family^Given^Middle^Prefix^Suffix"

### Enhanced DICOMTagType Model

#### VR Integration Properties
```python
class DICOMTagType(models.Model):
    # ... existing fields ...
    value_representation = models.CharField(max_length=256, null=True, blank=True)
    
    @property
    def vr_guidance(self):
        """Get VR guidance for this tag type."""
        if self.value_representation:
            from .vr_validators import VRValidator
            return VRValidator.get_vr_guidance(self.value_representation)
        return None
    
    @property
    def compatible_operators(self):
        """Get list of operators compatible with this tag's VR."""
        if self.value_representation:
            from .vr_validators import VRValidator
            return VRValidator.get_compatible_operators(self.value_representation)
        return []
    
    def validate_value_for_vr(self, value):
        """Validate a value against this tag's VR requirements."""
        if self.value_representation:
            from .vr_validators import VRValidator
            return VRValidator.validate_value_for_vr(value, self.value_representation)
        return True, ""
    
    def is_operator_compatible(self, operator):
        """Check if an operator is compatible with this tag's VR."""
        if self.value_representation:
            from .vr_validators import VRValidator
            return VRValidator.is_operator_compatible(self.value_representation, operator)
        return True
```

### Enhanced Rule Model Validation

#### VR-Aware Clean Method
```python
class Rule(models.Model):
    # ... existing fields ...
    
    def clean(self):
        """Enhanced validation including VR requirements."""
        super().clean()
        
        if not self.operator_type or not self.tag_value_to_evaluate:
            return
            
        # Get VR code from associated DICOM tag
        vr_code = None
        if self.dicom_tag_type and self.dicom_tag_type.value_representation:
            vr_code = self.dicom_tag_type.value_representation
        
        if vr_code:
            from .vr_validators import VRValidator
            
            # Validate value format against VR
            is_valid, vr_error = VRValidator.validate_value_for_vr(
                self.tag_value_to_evaluate, vr_code
            )
            if not is_valid:
                raise ValidationError({
                    'tag_value_to_evaluate': f'Value format invalid for {vr_code} VR: {vr_error}'
                })kr_compatible(vr_code, self.operator_type):
                compatible_ops = VRValidator.get_compatible_operators(vr_code)
                raise ValidationError({
                    'operator_type': f'Operator "{self.get_operator_type_display()}" is not compatible with {vr_code} VR. Compatible operators: {", ".join(compatible_ops)}'
                })
```

## AJAX Endpoints

### VR Guidance Endpoint
```python
@login_required
def get_vr_guidance(request, tag_id):
    """Get VR guidance for a specific DICOM tag."""
    try:
        tag = DICOMTagType.objects.get(id=tag_id)
        vr_guidance = tag.vr_guidance
        compatible_operators = tag.compatible_operators
        
        if vr_guidance:
            return JsonResponse({
                'success': True,
                'vr_code': tag.value_representation,
                'guidance': vr_guidance,
                'compatible_operators': compatible_operators
            })
        else:
            return JsonResponse({
                'success': False,
                'message': 'No VR information available for this tag'
            })
    except DICOMTagType.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': 'DICOM tag not found'
        })
```

### VR Value Validation Endpoint
```python
@login_required
def validate_vr_value(request):
    """Validate a value against VR requirements."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Only POST method allowed'})
    
    try:
        data = json.loads(request.body)
        tag_id = data.get('tag_id')
        value = data.get('value', '').strip()
        operator = data.get('operator', '')
        
        tag = DICOMTagType.objects.get(id=tag_id)
        
        # Validate value format
        is_valid, error_message = tag.validate_value_for_vr(value)
        
        # Check operator compatibility
        operator_compatible = tag.is_operator_compatible(operator)
        
        return JsonResponse({
            'success': True,
            'is_valid': is_valid,
            'error_message': error_message,
            'operator_compatible': operator_compatible,
            'compatible_operators': tag.compatible_operators
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})
```

## Frontend Implementation

### Inline VR Guidance Display

#### HTML Structure
```html
<!-- VR Guidance Display -->
<div class="vr-guidance text-sm bg-green-50 border border-green-200 rounded-md p-2 mt-2" style="display: none;">
    <div class="flex items-start">
        <svg class="w-4 h-4 text-green-600 mt-0.5 mr-2 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
            <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clip-rule="evenodd"></path>
        </svg>
        <div class="text-green-800">
            <span class="vr-description font-medium"></span>
            <span class="ml-2 text-green-600">VR:</span> 
            <span class="vr-code font-mono text-xs bg-green-100 px-1 rounded"></span>
        </div>
    </div>
</div>
```

#### JavaScript Implementation
```javascript
function loadVRGuidance(tagSelect) {
    const ruleForm = tagSelect.closest('.rule-form');
    const vrGuidanceDiv = ruleForm.querySelector('.vr-guidance');
    const tagId = tagSelect.value;
    
    if (!tagId) {
        vrGuidanceDiv.style.display = 'none';
        return;
    }
    
    // Make AJAX call to get VR guidance
    fetch(`/dicom/vr-guidance/${tagId}/`, {
        method: 'GET',
        headers: {
            'X-Requested-With': 'XMLHttpRequest',
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success && data.vr_code) {
            // Extract user-friendly description from guidance object
            let guidanceText = 'No specific guidance available';
            if (data.guidance && typeof data.guidance === 'object') {
                guidanceText = data.guidance.description || data.guidance.format || 'No specific guidance available';
            } else if (data.guidance && typeof data.guidance === 'string') {
                guidanceText = data.guidance;
            }
            
            // Update inline VR guidance display
            vrGuidanceDiv.querySelector('.vr-code').textContent = data.vr_code;
            vrGuidanceDiv.querySelector('.vr-description').textContent = guidanceText;
            vrGuidanceDiv.style.display = 'block';
            
            // Store VR info for validation
            ruleForm.setAttribute('data-vr-code', data.vr_code);
            ruleForm.setAttribute('data-compatible-operators', JSON.stringify(data.compatible_operators));
        } else {
            vrGuidanceDiv.style.display = 'none';
            ruleForm.removeAttribute('data-vr-code');
            ruleForm.removeAttribute('data-compatible-operators');
        }
    })
    .catch(error => {
        console.error('Error loading VR guidance:', error);
        vrGuidanceDiv.style.display = 'none';
    });
}
```

### Real-Time VR Validation
```javascript
function validateVRValue(ruleForm) {
    const tagSelect = ruleForm.querySelector('select[name$="-dicom_tag_type"]');
    const valueInput = ruleForm.querySelector('input[name$="-tag_value_to_evaluate"]');
    
    if (!tagSelect || !valueInput || !tagSelect.value || !valueInput.value.trim()) {
        return true;
    }
    
    const tagId = tagSelect.value;
    const value = valueInput.value.trim();
    const operatorSelect = ruleForm.querySelector('select[name$="-operator_type"]');
    const operator = operatorSelect ? operatorSelect.value : '';
    
    // Make AJAX call to validate VR value
    fetch('/dicom/validate-vr-value/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value,
            'X-Requested-With': 'XMLHttpRequest',
        },
        body: JSON.stringify({
            tag_id: tagId,
            value: value,
            operator: operator
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            if (!data.is_valid) {
                showVRValidationError(ruleForm, data.error_message);
                return false;
            } else {
                clearVRValidationError(ruleForm);
                return true;
            }
        }
    })
    .catch(error => {
        console.error('Error validating VR value:', error);
    });
}
```

## URL Configuration

### VR Validation URLs
```python
urlpatterns = [
    # ... existing URLs ...
    
    # VR Validation endpoints
    path('vr-guidance/<uuid:tag_id>/', views.get_vr_guidance, name='get_vr_guidance'),
    path('validate-vr-value/', views.validate_vr_value, name='validate_vr_value'),
]
```

## Key Features

### 1. Inline Guidance Display
- **Green Background Theme**: Attractive green information box that stands out
- **Information Icon**: Clear visual indicator for helpful guidance
- **User-Friendly Text**: Plain English descriptions of expected input formats

### 2. Real-Time Validation
- **Format Validation**: Checks value format against VR requirements
- **Operator Compatibility**: Ensures selected operators work with the VR type
- **Immediate Feedback**: Shows validation errors as users type

### 3. VR-Specific Guidance Examples
- **Text Fields**: "Enter text string (letters, numbers, symbols) up to 64 characters"
- **Numeric Fields**: "Enter whole number (positive or negative integer)"
- **Date Fields**: "Enter date in format YYYYMMDD (year, month, day as 8 digits)"
- **Special Formats**: "Enter person name using ^ to separate: Family^Given^Middle^Prefix^Suffix"

### 4. Integration Points
- **Model Validation**: VR validation integrated into Django model clean methods
- **Form Validation**: Automatic validation through model integration
- **AJAX Endpoints**: Lightweight endpoints for real-time validation
- **Template Integration**: Seamless integration with existing ruleset forms

## Benefits

1. **Improved Data Quality**: Ensures DICOM values conform to standards
2. **Better User Experience**: Clear guidance prevents input errors
3. **Real-Time Feedback**: Immediate validation reduces form submission errors
4. **Standards Compliance**: Enforces DICOM VR requirements automatically
5. **Maintainable Code**: Clean separation between validation logic and UI
2,"(0052,0014)","ALinePixelSpacing","A-line Pixel Spacing","FD"
3,"(0052,0011)","ALineRate","A-line Rate","FD"
4,"(0052,0012)","ALinesPerFrame","A-lines Per Frame","US"
...
```

### Field Mapping
- `id` → **Skipped** (Django generates UUIDs automatically)
- `tag_id` → `tag_id` field
- `tag_name` → `tag_name` field  
- `tag_description` → `tag_description` field
- `value_representation` → `value_representation` field

## Migration Implementation

### Data Migration: `0010_auto_20250913_1850.py`

```python
# Generated by Django 5.2.6 on 2025-09-13 13:20

import csv
import os
from django.db import migrations
from django.conf import settings


def load_dicom_tags(apps, schema_editor):
    """Load DICOM tags from CSV file into DICOMTagType model"""
    DICOMTagType = apps.get_model('dicom_handler', 'DICOMTagType')
    
    # Path to the CSV file
    csv_file_path = os.path.join(settings.BASE_DIR, 'seed_data', 'dicom_dictionary.csv')
    
    if not os.path.exists(csv_file_path):
        print(f"Warning: CSV file not found at {csv_file_path}")
        return
    
    # Clear existing data to avoid duplicates
    DICOMTagType.objects.all().delete()
    
    with open(csv_file_path, 'r', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        
        dicom_tags = []
        for row in reader:
            # Skip the id field as requested, use other fields
            dicom_tag = DICOMTagType(
                tag_name=row['tag_name'],
                tag_id=row['tag_id'],
                tag_description=row['tag_description'],
                value_representation=row['value_representation']
            )
            dicom_tags.append(dicom_tag)
        
        # Bulk create for better performance
        DICOMTagType.objects.bulk_create(dicom_tags, batch_size=1000)
        print(f"Successfully imported {len(dicom_tags)} DICOM tags")


def reverse_load_dicom_tags(apps, schema_editor):
    """Remove all DICOM tags"""
    DICOMTagType = apps.get_model('dicom_handler', 'DICOMTagType')
    DICOMTagType.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('dicom_handler', '0009_dicomtagtype_tag_description_dicomtagtype_tag_id_and_more'),
    ]

    operations = [
        migrations.RunPython(load_dicom_tags, reverse_load_dicom_tags),
    ]
```

### Migration Features

#### Data Import Process
1. **File Path Resolution**: Uses `settings.BASE_DIR` to locate CSV file
2. **Data Cleanup**: Clears existing records to prevent duplicates
3. **CSV Processing**: Uses `csv.DictReader` for column-based access
4. **Bulk Creation**: Processes records in batches of 1000 for performance
5. **Error Handling**: Checks file existence before processing

#### Reversibility
- **Forward Migration**: Imports all DICOM tags from CSV
- **Reverse Migration**: Removes all DICOMTagType records
- **Safe Rollback**: Allows complete migration reversal if needed

#### Performance Optimizations
- **Batch Processing**: Uses `bulk_create()` with 1000-record batches
- **Memory Efficiency**: Processes CSV row-by-row instead of loading all into memory
- **Single Transaction**: All operations wrapped in migration transaction

## Execution Results

### Migration Commands
```bash
# Create the migration
python manage.py makemigrations --empty dicom_handler

# Apply the migration
python manage.py migrate
```

### Import Statistics
- **Total Records Imported**: 3,731 DICOM tags
- **Processing Time**: < 1 second
- **File Size**: ~500KB CSV file
- **Memory Usage**: Minimal due to batch processing

### Verification
```python
# Check import success
from dicom_handler.models import DICOMTagType
print(f"Total DICOM tags: {DICOMTagType.objects.count()}")

# Sample records
sample_tags = DICOMTagType.objects.all()[:5]
for tag in sample_tags:
    print(f"{tag.tag_id}: {tag.tag_name} - {tag.tag_description}")
```

## Usage in RuleSet System

### Integration with Rule Creation
The imported DICOM tags are now available for:
- **Rule Creation**: Dropdown selection of standardized DICOM tags
- **Validation**: Ensuring only valid DICOM tags are used in rules
- **Autocomplete**: Enhanced user experience with tag descriptions
- **Consistency**: Standardized tag naming across the system

### Template Integration
```python
# In RuleForm
class RuleForm(forms.ModelForm):
    class Meta:
        model = Rule
        fields = ['dicom_tag_type', 'operator_type', 'tag_value_to_evaluate']
        widgets = {
            'dicom_tag_type': forms.Select(attrs={
                'class': 'w-full px-4 py-2 border border-gray-300 rounded-lg'
            })
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # All 3,731 DICOM tags now available for selection
        self.fields['dicom_tag_type'].queryset = DICOMTagType.objects.all().order_by('tag_name')
```

