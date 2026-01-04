"""
Views for DICOM Query/Retrieve functionality.
"""

import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.db.models import Q

from .models import (
    RemoteDicomNode,
    DicomQuery,
    DicomQueryResult,
    DicomRetrieveJob
)
from .forms_qr import RemoteDicomNodeForm, DicomQueryForm
from .query_retrieve_service import get_qr_service_instance

logger = logging.getLogger(__name__)


# ============================================================================
# Remote Node Management Views
# ============================================================================

@login_required
def remote_nodes_list(request):
    """List all remote DICOM nodes."""
    nodes = RemoteDicomNode.objects.all()
    
    context = {
        'nodes': nodes,
        'page_title': 'Remote DICOM Nodes',
    }
    return render(request, 'dicom_server/qr/remote_nodes_list.html', context)


@login_required
def remote_node_add(request):
    """Add a new remote DICOM node."""
    if request.method == 'POST':
        form = RemoteDicomNodeForm(request.POST)
        if form.is_valid():
            node = form.save()
            messages.success(request, f'Remote node "{node.name}" added successfully.')
            return redirect('dicom_server:remote_nodes_list')
    else:
        # Get local DICOM server AE title to use as default move destination
        from .models import DicomServerConfig
        config = DicomServerConfig.objects.get_or_create(pk=1)[0]
        form = RemoteDicomNodeForm(initial={'move_destination_ae': config.ae_title})
    
    context = {
        'form': form,
        'page_title': 'Add Remote DICOM Node',
        'action': 'Add',
    }
    return render(request, 'dicom_server/qr/remote_node_form.html', context)


@login_required
def remote_node_edit(request, node_id):
    """Edit an existing remote DICOM node."""
    node = get_object_or_404(RemoteDicomNode, pk=node_id)
    
    if request.method == 'POST':
        form = RemoteDicomNodeForm(request.POST, instance=node)
        if form.is_valid():
            node = form.save()
            messages.success(request, f'Remote node "{node.name}" updated successfully.')
            return redirect('dicom_server:remote_nodes_list')
    else:
        form = RemoteDicomNodeForm(instance=node)
    
    context = {
        'form': form,
        'node': node,
        'page_title': f'Edit {node.name}',
        'action': 'Update',
    }
    return render(request, 'dicom_server/qr/remote_node_form.html', context)


@login_required
def remote_node_delete(request, node_id):
    """Delete a remote DICOM node."""
    node = get_object_or_404(RemoteDicomNode, pk=node_id)
    
    if request.method == 'POST':
        node_name = node.name
        node.delete()
        messages.success(request, f'Remote node "{node_name}" deleted successfully.')
        return redirect('dicom_server:remote_nodes_list')
    
    context = {
        'node': node,
        'page_title': f'Delete {node.name}',
    }
    return render(request, 'dicom_server/qr/remote_node_confirm_delete.html', context)


@login_required
@require_http_methods(["POST"])
def remote_node_test(request, node_id):
    """Test connection to a remote DICOM node."""
    node = get_object_or_404(RemoteDicomNode, pk=node_id)
    
    try:
        qr_service = get_qr_service_instance()
        success, message = qr_service.test_connection(node)
        
        return JsonResponse({
            'success': success,
            'message': message,
            'last_connection': node.last_successful_connection.isoformat() if node.last_successful_connection else None
        })
    except Exception as e:
        logger.error(f"Error testing connection to {node.name}: {str(e)}")
        return JsonResponse({
            'success': False,
            'message': f'Error: {str(e)}'
        }, status=500)


# ============================================================================
# Query Views
# ============================================================================

@login_required
def query_interface(request):
    """Main query interface."""
    nodes = RemoteDicomNode.objects.filter(is_active=True, supports_c_find=True)
    
    if not nodes.exists():
        messages.warning(request, 'No active remote nodes configured. Please add a remote node first.')
        return redirect('dicom_server:remote_nodes_list')
    
    # Get selected node from session or use first node
    selected_node_id = request.session.get('selected_node_id')
    if selected_node_id:
        try:
            selected_node = RemoteDicomNode.objects.get(pk=selected_node_id)
        except RemoteDicomNode.DoesNotExist:
            selected_node = nodes.first()
    else:
        selected_node = nodes.first()
    
    if request.method == 'POST':
        form = DicomQueryForm(request.POST)
        node_id = request.POST.get('remote_node')
        
        if node_id:
            try:
                selected_node = RemoteDicomNode.objects.get(pk=node_id)
                request.session['selected_node_id'] = selected_node.id
            except RemoteDicomNode.DoesNotExist:
                pass
        
        if form.is_valid():
            try:
                qr_service = get_qr_service_instance()
                query_level = form.cleaned_data['query_level']
                query_params = form.get_query_params()
                
                # Perform query
                query_obj = qr_service.query(
                    selected_node,
                    query_level,
                    query_params,
                    user=request.user
                )
                
                messages.success(
                    request,
                    f'Query completed: {query_obj.results_count} results found in {query_obj.duration_seconds:.2f}s'
                )
                return redirect('dicom_server:query_results', query_id=query_obj.query_id)
                
            except Exception as e:
                logger.error(f"Query failed: {str(e)}")
                messages.error(request, f'Query failed: {str(e)}')
    else:
        form = DicomQueryForm()
    
    context = {
        'form': form,
        'nodes': nodes,
        'selected_node': selected_node,
        'page_title': 'DICOM Query',
    }
    return render(request, 'dicom_server/qr/query_interface.html', context)


@login_required
def query_results(request, query_id):
    """Display query results."""
    query = get_object_or_404(DicomQuery, query_id=query_id)
    results = query.results.all()
    
    # Pagination
    from django.core.paginator import Paginator
    paginator = Paginator(results, 50)  # Show 50 results per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'query': query,
        'results': page_obj,
        'page_title': f'Query Results - {query.remote_node.name}',
    }
    return render(request, 'dicom_server/qr/query_results.html', context)


@login_required
def query_history(request):
    """Display query history."""
    queries = DicomQuery.objects.filter(initiated_by=request.user).select_related('remote_node')
    
    # Filter by status if provided
    status_filter = request.GET.get('status')
    if status_filter:
        queries = queries.filter(status=status_filter)
    
    # Pagination
    from django.core.paginator import Paginator
    paginator = Paginator(queries, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'queries': page_obj,
        'status_filter': status_filter,
        'page_title': 'Query History',
    }
    return render(request, 'dicom_server/qr/query_history.html', context)


# ============================================================================
# Retrieve Views
# ============================================================================

@login_required
@require_http_methods(["POST"])
def retrieve_study(request, result_id):
    """Initiate retrieve operation for a study."""
    result = get_object_or_404(DicomQueryResult, pk=result_id)
    
    try:
        qr_service = get_qr_service_instance()
        remote_node = result.query.remote_node
        
        # Determine retrieve method
        if remote_node.supports_c_move:
            retrieve_method = 'move'
        elif remote_node.supports_c_get:
            retrieve_method = 'get'
        else:
            return JsonResponse({
                'success': False,
                'message': 'Remote node does not support retrieve operations'
            }, status=400)
        
        # Initiate retrieve
        if retrieve_method == 'move':
            job = qr_service.retrieve_move(
                remote_node,
                result.study_instance_uid,
                user=request.user
            )
        else:
            job = qr_service.retrieve_get(
                remote_node,
                result.study_instance_uid,
                user=request.user
            )
        
        # Link job to query result
        job.query_result = result
        job.save()
        
        return JsonResponse({
            'success': True,
            'message': f'Retrieve job initiated ({retrieve_method.upper()})',
            'job_id': str(job.job_id)
        })
        
    except Exception as e:
        logger.error(f"Retrieve failed: {str(e)}")
        return JsonResponse({
            'success': False,
            'message': f'Retrieve failed: {str(e)}'
        }, status=500)


@login_required
@require_http_methods(["POST"])
def retrieve_series(request, result_id):
    """Initiate retrieve operation for a series."""
    result = get_object_or_404(DicomQueryResult, pk=result_id)
    
    if not result.series_instance_uid:
        return JsonResponse({
            'success': False,
            'message': 'Series UID not available'
        }, status=400)
    
    try:
        qr_service = get_qr_service_instance()
        remote_node = result.query.remote_node
        
        # Determine retrieve method
        if remote_node.supports_c_move:
            retrieve_method = 'move'
        elif remote_node.supports_c_get:
            retrieve_method = 'get'
        else:
            return JsonResponse({
                'success': False,
                'message': 'Remote node does not support retrieve operations'
            }, status=400)
        
        # Initiate retrieve
        if retrieve_method == 'move':
            job = qr_service.retrieve_move(
                remote_node,
                result.study_instance_uid,
                series_uid=result.series_instance_uid,
                user=request.user
            )
        else:
            job = qr_service.retrieve_get(
                remote_node,
                result.study_instance_uid,
                series_uid=result.series_instance_uid,
                user=request.user
            )
        
        # Link job to query result
        job.query_result = result
        job.save()
        
        return JsonResponse({
            'success': True,
            'message': f'Retrieve job initiated ({retrieve_method.upper()})',
            'job_id': str(job.job_id)
        })
        
    except Exception as e:
        logger.error(f"Retrieve failed: {str(e)}")
        return JsonResponse({
            'success': False,
            'message': f'Retrieve failed: {str(e)}'
        }, status=500)


@login_required
def retrieve_jobs(request):
    """Display retrieve job history."""
    jobs = DicomRetrieveJob.objects.filter(initiated_by=request.user).select_related('remote_node')
    
    # Filter by status if provided
    status_filter = request.GET.get('status')
    if status_filter:
        jobs = jobs.filter(status=status_filter)
    
    # Pagination
    from django.core.paginator import Paginator
    paginator = Paginator(jobs, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'jobs': page_obj,
        'status_filter': status_filter,
        'page_title': 'Retrieve Jobs',
    }
    return render(request, 'dicom_server/qr/retrieve_jobs.html', context)


@login_required
def retrieve_job_status(request, job_id):
    """Get status of a retrieve job (AJAX)."""
    job = get_object_or_404(DicomRetrieveJob, job_id=job_id)
    
    return JsonResponse({
        'status': job.status,
        'progress_percent': job.progress_percent,
        'total_instances': job.total_instances,
        'completed_instances': job.completed_instances,
        'failed_instances': job.failed_instances,
        'error_message': job.error_message,
    })
