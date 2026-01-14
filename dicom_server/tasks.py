"""
Celery tasks for DICOM server operations.
Handles async database operations to avoid blocking DICOM transfers.
"""

from celery import shared_task
from celery.schedules import crontab
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


@shared_task(ignore_result=True, max_retries=3, default_retry_delay=1)
def update_remote_node_connection_async(node_id):
    """
    Asynchronously update the last incoming connection timestamp for a RemoteDicomNode.
    This prevents blocking C-STORE operations with synchronous database writes.
    
    Args:
        node_id (int): ID of the RemoteDicomNode to update
    """
    try:
        from .models import RemoteDicomNode
        
        RemoteDicomNode.objects.filter(pk=node_id).update(
            last_incoming_connection=timezone.now()
        )
        logger.debug(f"Updated last incoming connection for node {node_id}")
        
    except Exception as e:
        logger.error(f"Failed to update remote node connection async: {str(e)}")
        raise


@shared_task(ignore_result=True)
def check_storage_limits_periodic():
    """
    Periodic task to check storage limits and update the storage_limit_exceeded flag.
    Runs every 10 minutes to avoid expensive filesystem scans on every C-STORE operation.
    
    This task:
    1. Scans the storage directory to calculate total usage
    2. Updates cached_storage_usage_bytes
    3. Sets storage_limit_exceeded flag if limit is reached
    4. Optionally triggers cleanup if enabled
    """
    try:
        from .models import DicomServerConfig
        from .storage_cleanup import get_storage_usage, check_and_cleanup_if_needed
        from dicom_handler.models import SystemConfiguration
        
        logger.info("[STORAGE CHECK] Starting periodic storage check...")
        
        # Get configuration
        config = DicomServerConfig.objects.get(pk=1)
        system_config = SystemConfiguration.objects.get(pk=1)
        storage_path = system_config.folder_configuration
        
        if not storage_path:
            logger.warning("[STORAGE CHECK] No storage path configured, skipping check")
            return
        
        # Perform filesystem scan
        import time
        start_time = time.time()
        usage = get_storage_usage(storage_path)
        scan_duration = time.time() - start_time
        
        current_usage_gb = usage['total_gb']
        max_storage_gb = config.max_storage_size_gb
        
        logger.info(
            f"[STORAGE CHECK] Completed in {scan_duration:.2f}s: "
            f"{usage['total_files']} files, {current_usage_gb}GB / {max_storage_gb}GB "
            f"({(current_usage_gb/max_storage_gb*100):.1f}%)"
        )
        
        # Update cached values
        config.cached_storage_usage_bytes = usage['total_bytes']
        config.cached_storage_last_updated = timezone.now()
        
        # Check if limit exceeded
        if current_usage_gb >= max_storage_gb:
            logger.warning(f"[STORAGE CHECK] Storage limit exceeded: {current_usage_gb}GB / {max_storage_gb}GB")
            
            # Attempt cleanup if enabled
            if config.enable_storage_cleanup:
                logger.info("[STORAGE CHECK] Attempting automatic cleanup...")
                from .dicom_scp_service import get_service_instance
                service = get_service_instance()
                cleanup_performed = check_and_cleanup_if_needed(service)
                
                if cleanup_performed:
                    # Re-scan after cleanup
                    usage = get_storage_usage(storage_path)
                    current_usage_gb = usage['total_gb']
                    config.cached_storage_usage_bytes = usage['total_bytes']
                    logger.info(f"[STORAGE CHECK] Cleanup completed, new usage: {current_usage_gb}GB")
            
            # Set flag if still over limit
            config.storage_limit_exceeded = (current_usage_gb >= max_storage_gb)
        else:
            config.storage_limit_exceeded = False
        
        config.save()
        logger.info(f"[STORAGE CHECK] storage_limit_exceeded flag set to: {config.storage_limit_exceeded}")
        
    except Exception as e:
        logger.error(f"[STORAGE CHECK] Failed: {str(e)}", exc_info=True)
        raise
