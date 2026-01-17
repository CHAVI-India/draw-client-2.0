from django.urls import path
from . import views
from . import views_qr

app_name = 'dicom_server'

urlpatterns = [
    # DICOM Server (SCP) URLs
    path('', views.dicom_server_dashboard, name='dashboard'),
    path('config/', views.dicom_server_config, name='config'),
    path('ae-titles/', views.allowed_ae_titles, name='allowed_ae_titles'),
    path('ae-titles/delete/<int:ae_title_id>/', views.delete_ae_title, name='delete_ae_title'),
    path('ae-titles/toggle/<int:ae_title_id>/', views.toggle_ae_title, name='toggle_ae_title'),
    path('transactions/', views.transaction_log, name='transaction_log'),
    path('service/control/', views.service_control, name='service_control'),
    path('api/status/', views.service_status_api, name='service_status_api'),
    
    # Query/Retrieve URLs
    # Remote Nodes Management
    path('qr/nodes/', views_qr.remote_nodes_list, name='remote_nodes_list'),
    path('qr/nodes/add/', views_qr.remote_node_add, name='remote_node_add'),
    path('qr/nodes/<int:node_id>/edit/', views_qr.remote_node_edit, name='remote_node_edit'),
    path('qr/nodes/<int:node_id>/delete/', views_qr.remote_node_delete, name='remote_node_delete'),
    path('qr/nodes/<int:node_id>/test/', views_qr.remote_node_test, name='remote_node_test'),
    
    # Query Interface
    path('qr/query/', views_qr.query_interface, name='query_interface'),
    path('qr/query/<uuid:query_id>/results/', views_qr.query_results, name='query_results'),
    path('qr/query/history/', views_qr.query_history, name='query_history'),
    
    # Retrieve Operations
    path('qr/retrieve/study/<int:result_id>/', views_qr.retrieve_study, name='retrieve_study'),
    path('qr/retrieve/series/<int:result_id>/', views_qr.retrieve_series, name='retrieve_series'),
    path('qr/retrieve/jobs/', views_qr.retrieve_jobs, name='retrieve_jobs'),
    path('qr/retrieve/jobs/<uuid:job_id>/status/', views_qr.retrieve_job_status, name='retrieve_job_status'),
    
    # C-STORE Push Operations
    path('qr/nodes/<int:node_id>/send/', views_qr.cstore_push_interface, name='cstore_push_interface'),
    path('qr/nodes/<int:node_id>/send/execute/', views_qr.cstore_push_send, name='cstore_push_send'),
    path('qr/nodes/<int:node_id>/test-cstore/', views_qr.cstore_test_connection, name='cstore_test_connection'),
]
