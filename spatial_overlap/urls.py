from django.urls import path
from . import views

app_name = 'spatial_overlap'

urlpatterns = [
    # RT Structure Set upload and management
    path('upload/', views.upload_rtstruct, name='upload_rtstruct'),
    path('compare-reference/', views.compare_with_reference, name='compare_with_reference'),
    path('select-rtstruct/', views.select_rtstruct_for_comparison, name='select_rtstruct_for_comparison'),
    path('list/', views.list_rtstructs, name='list_rtstructs'),
    path('detail/<int:rtstruct_id>/', views.rtstruct_detail, name='rtstruct_detail'),
    
    # Comparison workflow
    path('select-pairs/', views.select_comparison_pairs, name='select_comparison_pairs'),
    path('create-comparisons/', views.create_comparisons, name='create_comparisons'),
    path('comparisons/', views.list_comparisons, name='list_comparisons'),
    path('comparison/<int:comparison_id>/', views.comparison_detail, name='comparison_detail'),
    path('comparison/<int:comparison_id>/delete/', views.delete_comparison, name='delete_comparison'),
    path('series/<str:series_instance_uid>/comparisons/', views.series_comparisons, name='series_comparisons'),
    
    # Metrics computation
    path('comparison/<int:comparison_id>/compute/', views.compute_metrics, name='compute_metrics'),
    path('batch-compute/', views.batch_compute_metrics, name='batch_compute_metrics'),
    path('bulk-compute-async/', views.bulk_compute_metrics_async, name='bulk_compute_metrics_async'),
    path('bulk-compute-status/<str:task_id>/', views.bulk_compute_status, name='bulk_compute_status'),
]
