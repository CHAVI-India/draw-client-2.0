from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Count, Q
from django.utils import timezone
from datetime import timedelta
from .models import DicomServerConfig, AllowedAETitle, DicomTransaction, DicomServiceStatus
from .forms import DicomServerConfigForm, AllowedAETitleForm


@login_required
def dicom_server_dashboard(request):
    """
    Main dashboard for DICOM server management.
    Shows service status, configuration, and recent activity.
    """
    config, created = DicomServerConfig.objects.get_or_create(pk=1)
    service_status, created = DicomServiceStatus.objects.get_or_create(pk=1)
    
    # Get recent transactions (last 24 hours)
    last_24h = timezone.now() - timedelta(hours=24)
    recent_transactions = DicomTransaction.objects.filter(
        timestamp__gte=last_24h
    ).order_by('-timestamp')[:50]
    
    # Get transaction statistics
    transaction_stats = DicomTransaction.objects.filter(
        timestamp__gte=last_24h
    ).aggregate(
        total=Count('transaction_id'),
        success=Count('transaction_id', filter=Q(status='SUCCESS')),
        failure=Count('transaction_id', filter=Q(status='FAILURE')),
        c_store=Count('transaction_id', filter=Q(transaction_type='C-STORE')),
        c_echo=Count('transaction_id', filter=Q(transaction_type='C-ECHO')),
    )
    
    # Get allowed AE titles
    allowed_ae_titles = AllowedAETitle.objects.filter(is_active=True).order_by('ae_title')
    
    context = {
        'config': config,
        'service_status': service_status,
        'recent_transactions': recent_transactions,
        'transaction_stats': transaction_stats,
        'allowed_ae_titles': allowed_ae_titles,
    }
    
    return render(request, 'dicom_server/dashboard.html', context)


@login_required
def dicom_server_config(request):
    """
    DICOM server configuration page.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    config, created = DicomServerConfig.objects.get_or_create(pk=1)
    
    if request.method == 'POST':
        form = DicomServerConfigForm(request.POST, instance=config)
        if form.is_valid():
            saved_config = form.save()
            # Log the saved values
            logger.info(f"Configuration saved - CT: {saved_config.support_ct_image_storage}, MR: {saved_config.support_mr_image_storage}, RT Struct: {saved_config.support_rt_structure_storage}")
            # Verify it was actually saved to DB
            config.refresh_from_db()
            logger.info(f"After refresh - CT: {config.support_ct_image_storage}, MR: {config.support_mr_image_storage}, RT Struct: {config.support_rt_structure_storage}")
            messages.success(request, 'DICOM server configuration updated successfully.')
            return redirect('dicom_server:config')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = DicomServerConfigForm(instance=config)
    
    context = {
        'form': form,
        'config': config,
    }
    
    return render(request, 'dicom_server/config.html', context)


@login_required
def allowed_ae_titles(request):
    """
    Manage allowed AE titles.
    """
    ae_titles = AllowedAETitle.objects.all().order_by('ae_title')
    
    if request.method == 'POST':
        form = AllowedAETitleForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, f'AE Title "{form.cleaned_data["ae_title"]}" added successfully.')
            return redirect('dicom_server:allowed_ae_titles')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = AllowedAETitleForm()
    
    context = {
        'ae_titles': ae_titles,
        'form': form,
    }
    
    return render(request, 'dicom_server/allowed_ae_titles.html', context)


@login_required
def delete_ae_title(request, ae_title_id):
    """
    Delete an allowed AE title.
    """
    ae_title = get_object_or_404(AllowedAETitle, pk=ae_title_id)
    ae_title_name = ae_title.ae_title
    ae_title.delete()
    messages.success(request, f'AE Title "{ae_title_name}" deleted successfully.')
    return redirect('dicom_server:allowed_ae_titles')


@login_required
def toggle_ae_title(request, ae_title_id):
    """
    Toggle active status of an AE title.
    """
    ae_title = get_object_or_404(AllowedAETitle, pk=ae_title_id)
    ae_title.is_active = not ae_title.is_active
    ae_title.save()
    status = 'activated' if ae_title.is_active else 'deactivated'
    messages.success(request, f'AE Title "{ae_title.ae_title}" {status} successfully.')
    return redirect('dicom_server:allowed_ae_titles')


@login_required
def transaction_log(request):
    """
    View transaction log with filtering.
    """
    transactions = DicomTransaction.objects.all().order_by('-timestamp')
    
    # Apply filters
    transaction_type = request.GET.get('type')
    status = request.GET.get('status')
    ae_title = request.GET.get('ae_title')
    
    if transaction_type:
        transactions = transactions.filter(transaction_type=transaction_type)
    if status:
        transactions = transactions.filter(status=status)
    if ae_title:
        transactions = transactions.filter(calling_ae_title=ae_title)
    
    # Pagination (show 100 per page)
    transactions = transactions[:100]
    
    context = {
        'transactions': transactions,
        'transaction_types': DicomTransaction.TRANSACTION_TYPE_CHOICES,
        'statuses': DicomTransaction.STATUS_CHOICES,
        'selected_type': transaction_type,
        'selected_status': status,
        'selected_ae_title': ae_title,
    }
    
    return render(request, 'dicom_server/transaction_log.html', context)


@login_required
def service_control(request):
    """
    Start/stop/restart DICOM service.
    """
    from .service_manager import start_service, stop_service, restart_service
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'start':
            success, message = start_service()
            if success:
                messages.success(request, message)
            else:
                messages.error(request, message)
                
        elif action == 'stop':
            success, message = stop_service()
            if success:
                messages.success(request, message)
            else:
                messages.error(request, message)
                
        elif action == 'restart':
            success, message = restart_service()
            if success:
                messages.success(request, message)
            else:
                messages.error(request, message)
    
    return redirect('dicom_server:dashboard')


@login_required
def service_status_api(request):
    """
    API endpoint for real-time service status updates.
    """
    service_status, created = DicomServiceStatus.objects.get_or_create(pk=1)
    config, created = DicomServerConfig.objects.get_or_create(pk=1)
    
    data = {
        'is_running': service_status.is_running,
        'uptime': service_status.uptime_formatted,
        'active_connections': service_status.active_connections,
        'total_connections': service_status.total_connections,
        'total_files_received': service_status.total_files_received,
        'total_bytes_received': service_status.total_bytes_received,
        'total_errors': service_status.total_errors,
        'average_file_size_mb': service_status.average_file_size_mb,
        'storage_usage_gb': config.storage_usage_gb,
        'storage_available_gb': config.storage_available_gb,
        'storage_usage_percent': config.storage_usage_percent,
    }
    
    return JsonResponse(data)
