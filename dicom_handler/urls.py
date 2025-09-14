from django.urls import path
from . import views
from .search_views import search_structures

app_name = 'dicom_handler'

urlpatterns = [
    path('create-template/', views.create_template, name='create_template'),
    path('save-template/', views.save_template, name='save_template'),
    path('save-selections/', views.save_selections, name='save_selections'),
    path('select-models/', views.select_models, name='select_models'),
    path('update-selections/', views.update_selections, name='update_selections'),
    path('templates/', views.template_list, name='template_list'),
    path('templates/<uuid:template_id>/', views.template_detail, name='template_detail'),
    path('templates/<uuid:template_id>/edit/', views.edit_template, name='edit_template'),
    path('templates/<uuid:template_id>/delete/', views.template_delete, name='template_delete'),
    path('templates/<uuid:template_id>/update/', views.update_template, name='update_template'),
    path('templates/<uuid:template_id>/update-info/', views.update_template_info, name='update_template_info'),
    path('search-structures/', search_structures, name='search_structures'),
    
    # RuleSet URLs
    path('rulesets/', views.ruleset_list, name='ruleset_list'),
    path('rulesets/create/', views.ruleset_create, name='ruleset_create'),
    path('rulesets/<uuid:ruleset_id>/', views.ruleset_detail, name='ruleset_detail'),
    path('rulesets/<uuid:ruleset_id>/edit/', views.ruleset_edit, name='ruleset_edit'),
    path('rulesets/<uuid:ruleset_id>/delete/', views.ruleset_delete, name='ruleset_delete'),
    
    # VR Validation AJAX URLs
    path('vr-guidance/<uuid:tag_id>/', views.get_vr_guidance, name='get_vr_guidance'),
    path('validate-vr-value/', views.validate_vr_value, name='validate_vr_value'),
    path('search-dicom-tags/', views.search_dicom_tags, name='search_dicom_tags'),
    
    # DICOM Series Processing Status
    path('series-status/', views.series_processing_status, name='series_processing_status'),
]
