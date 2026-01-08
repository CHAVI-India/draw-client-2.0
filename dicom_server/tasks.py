"""
Celery tasks for DICOM server operations.
Handles async database operations to avoid blocking DICOM transfers.
"""

from celery import shared_task
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)


@shared_task(ignore_result=True, max_retries=3, default_retry_delay=1)
def log_dicom_transaction_async(transaction_data):
    """
    Asynchronously log a DICOM transaction to the database.
    
    This task runs in a Celery worker, preventing database writes from
    blocking DICOM C-STORE operations.
    
    Args:
        transaction_data (dict): Transaction data to log
        
    Returns:
        None (ignore_result=True for performance)
    """
    try:
        from .models import DicomTransaction
        DicomTransaction.objects.create(**transaction_data)
        logger.debug(f"Logged {transaction_data.get('transaction_type')} transaction async")
    except Exception as e:
        logger.error(f"Failed to log transaction async: {str(e)}")
        # Retry on database errors
        raise


@shared_task(ignore_result=True, max_retries=3, default_retry_delay=1)
def update_service_status_async(status_updates):
    """
    Asynchronously update DICOM service status statistics.
    
    Args:
        status_updates (dict): Status fields to update
            - total_files_received: int
            - total_bytes_received: int
            - total_errors: int
            - last_file_received_at: datetime
    """
    try:
        from .models import DicomServiceStatus
        from django.db.models import F
        
        status = DicomServiceStatus.objects.get(pk=1)
        
        # Use F() expressions for atomic updates
        if 'total_files_received' in status_updates:
            status.total_files_received = F('total_files_received') + status_updates['total_files_received']
        
        if 'total_bytes_received' in status_updates:
            status.total_bytes_received = F('total_bytes_received') + status_updates['total_bytes_received']
        
        if 'total_errors' in status_updates:
            status.total_errors = F('total_errors') + status_updates['total_errors']
        
        if 'last_file_received_at' in status_updates:
            status.last_file_received_at = status_updates['last_file_received_at']
        
        status.save()
        logger.debug("Updated service status async")
        
    except Exception as e:
        logger.error(f"Failed to update service status async: {str(e)}")
        raise


@shared_task(ignore_result=True, max_retries=3, default_retry_delay=1)
def update_storage_cache_async(file_size):
    """
    Asynchronously update storage cache in DicomServerConfig.
    
    Args:
        file_size (int): Size of file in bytes to add to cache
    """
    try:
        from .models import DicomServerConfig
        from django.db.models import F
        
        DicomServerConfig.objects.filter(pk=1).update(
            cached_storage_usage_bytes=F('cached_storage_usage_bytes') + file_size
        )
        logger.debug(f"Updated storage cache async: +{file_size} bytes")
        
    except Exception as e:
        logger.error(f"Failed to update storage cache async: {str(e)}")
        raise
