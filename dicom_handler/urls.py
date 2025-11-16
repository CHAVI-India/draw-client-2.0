from django.urls import path
from . import views
from .search_views import search_structures
from .manual_autosegmentation_views import (
    ManualAutosegmentationSeriesInfoView,
    ManualAutosegmentationValidateView,
    ManualAutosegmentationStartProcessingView,
    ManualAutosegmentationStatusView,
    ManualAutosegmentationRetryView,
    ManualAutosegmentationCancelView,
    get_available_templates_view,
    test_api_endpoint
)
from .dicom_viewer_views import (
    view_rt_structure_list,
    dicom_viewer,
    load_dicom_data,
    get_dicom_slice,
    cleanup_temp_files,
    save_contour_ratings
)

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
    path('manual-processing-status/', views.manual_processing_status, name='manual_processing_status'),
    
    # System Configuration
    path('system-config/', views.system_configuration, name='system_configuration'),
    
    # Statistics Dashboard
    path('statistics/', views.statistics_dashboard, name='statistics_dashboard'),
    
    # API Health Check
    path('api/health-check/', views.check_api_health, name='check_api_health'),
    
    # Contour Quality Rating
    path('rate-contour/<str:series_uid>/', views.rate_contour_quality, name='rate_contour_quality'),
    path('view-ratings/<str:series_uid>/', views.view_series_ratings, name='view_series_ratings'),
    
    # Patient Details
    path('patient/<uuid:patient_uuid>/', views.patient_details, name='patient_details'),
    
    # Manual Autosegmentation API URLs
    path('api/manual-autosegmentation/series-info/', ManualAutosegmentationSeriesInfoView.as_view(), name='manual_autosegmentation_series_info'),
    path('api/manual-autosegmentation/validate/', ManualAutosegmentationValidateView.as_view(), name='manual_autosegmentation_validate'),
    path('api/manual-autosegmentation/start-processing/', ManualAutosegmentationStartProcessingView.as_view(), name='manual_autosegmentation_start_processing'),
    path('api/manual-autosegmentation/status/', ManualAutosegmentationStatusView.as_view(), name='manual_autosegmentation_status'),
    path('api/manual-autosegmentation/retry/', ManualAutosegmentationRetryView.as_view(), name='manual_autosegmentation_retry'),
    path('api/manual-autosegmentation/cancel/', ManualAutosegmentationCancelView.as_view(), name='manual_autosegmentation_cancel'),
    path('api/manual-autosegmentation/templates/', get_available_templates_view, name='manual_autosegmentation_templates'),
    path('api/test/', test_api_endpoint, name='test_api_endpoint'),
    
    # DICOM Viewer URLs
    path('rt-structures/<str:series_uid>/', view_rt_structure_list, name='view_rt_structure_list'),
    path('dicom-viewer/<str:series_uid>/<uuid:rt_structure_id>/', dicom_viewer, name='dicom_viewer'),
    path('api/dicom-viewer/load-data/', load_dicom_data, name='load_dicom_data'),
    path('api/dicom-viewer/get-slice/', get_dicom_slice, name='get_dicom_slice'),
    path('api/dicom-viewer/cleanup/', cleanup_temp_files, name='cleanup_temp_files'),
    path('api/dicom-viewer/save-ratings/', save_contour_ratings, name='save_contour_ratings'),
]
