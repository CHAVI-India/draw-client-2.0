from django.urls import path

from . import views

app_name = 'log_console'

urlpatterns = [
    path('', views.console, name='console'),
    path('stream/', views.stream, name='stream'),
    path('download/', views.download_single, name='download'),
    path('download-all/', views.download_all, name='download_all'),
]
