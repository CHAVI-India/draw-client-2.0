from django.urls import path
from . import views

app_name = 'dicom_server'

urlpatterns = [
    path('', views.dicom_server_dashboard, name='dashboard'),
    path('config/', views.dicom_server_config, name='config'),
    path('ae-titles/', views.allowed_ae_titles, name='allowed_ae_titles'),
    path('ae-titles/delete/<int:ae_title_id>/', views.delete_ae_title, name='delete_ae_title'),
    path('ae-titles/toggle/<int:ae_title_id>/', views.toggle_ae_title, name='toggle_ae_title'),
    path('transactions/', views.transaction_log, name='transaction_log'),
    path('service/control/', views.service_control, name='service_control'),
    path('api/status/', views.service_status_api, name='service_status_api'),
]
