"""
C-STORE handler for receiving DICOM files.
"""

import os
import logging
import time
from pathlib import Path
from datetime import datetime

from pydicom import dcmread
from pydicom.errors import InvalidDicomError
from django.utils import timezone
from django.db import transaction as db_transaction
from django.core.cache import cache

from ..models import DicomTransaction
from ..storage_cleanup import check_and_cleanup_if_needed, get_storage_usage
from dicom_handler.models import SystemConfiguration

logger = logging.getLogger(__name__)

# Cache configuration for storage checks
STORAGE_CACHE_KEY = 'dicom_storage_usage_gb'
STORAGE_CACHE_TIMEOUT = 30  # Cache storage usage for 30 seconds


def handle_c_store(service, event):
    """
    Handle C-STORE request - receive and store DICOM file.
    
    PERFORMANCE OPTIMIZED:
    - Uses event.encoded_dataset() to write raw bytes directly to file
    - Avoids expensive decode/re-encode cycle
    - Only decodes dataset when validation or metadata extraction is required
    
    Args:
        service: DicomSCPService instance
        event: C-STORE event from pynetdicom
    
    Returns:
        int: DICOM status code (0x0000 for success)
    """
    start_time = time.time()
    
    calling_ae = event.assoc.requestor.ae_title
    remote_ip = event.assoc.requestor.address
    
    try:
        # Get fresh config for validation and processing settings
        from ..models import DicomServerConfig
        fresh_config = DicomServerConfig.objects.get(pk=1)
        
        # Validate calling AE if required
        if not service._validate_calling_ae(calling_ae):
            logger.warning(f"C-STORE rejected: Calling AE '{calling_ae}' not authorized")
            service._log_transaction(
                'C-STORE',
                'REJECTED',
                event,
                error_message=f"Calling AE '{calling_ae}' not authorized"
            )
            return 0xA700  # Refused: Out of Resources
        
        # Validate remote IP if required
        if not service._validate_remote_ip(remote_ip):
            logger.warning(f"C-STORE rejected: Remote IP '{remote_ip}' not authorized")
            service._log_transaction(
                'C-STORE',
                'REJECTED',
                event,
                error_message=f"Remote IP '{remote_ip}' not authorized"
            )
            return 0xA700  # Refused: Out of Resources
        
        # OPTIMIZATION: Only decode dataset if validation or metadata extraction is needed
        # This avoids the expensive decode operation when not required
        ds = None
        patient_id = None
        study_uid = None
        series_uid = None
        sop_instance_uid = None
        sop_class_uid = None
        
        # Check if we need to decode the dataset
        needs_decoding = (
            fresh_config.validate_dicom_on_receive or
            fresh_config.storage_structure != 'flat' or
            fresh_config.file_naming_convention != 'timestamp'
        )
        
        if needs_decoding:
            # Decode dataset only when necessary
            ds = event.dataset
            ds.file_meta = event.file_meta
            
            # Validate DICOM if required (use fresh config)
            if fresh_config.validate_dicom_on_receive:
                if not _validate_dicom_dataset(ds):
                    logger.error("C-STORE rejected: Invalid DICOM dataset")
                    if fresh_config.reject_invalid_dicom:
                        service._log_transaction(
                            'C-STORE',
                            'REJECTED',
                            event,
                            error_message="Invalid DICOM dataset"
                        )
                        # Update error count asynchronously to avoid blocking
                        from ..tasks import update_service_status_async
                        update_service_status_async.delay({'total_errors': 1})
                        return 0xC000  # Error: Cannot understand
            
            # Extract DICOM metadata
            patient_id = getattr(ds, 'PatientID', None)
            study_uid = getattr(ds, 'StudyInstanceUID', None)
            series_uid = getattr(ds, 'SeriesInstanceUID', None)
            sop_instance_uid = getattr(ds, 'SOPInstanceUID', None)
            sop_class_uid = getattr(ds, 'SOPClassUID', None)
        
        # Check storage limits
        if not _check_storage_limits(service):
            logger.error("C-STORE rejected: Storage limit reached")
            service._log_transaction(
                'C-STORE',
                'REJECTED',
                event,
                patient_id=patient_id,
                study_instance_uid=study_uid,
                series_instance_uid=series_uid,
                sop_instance_uid=sop_instance_uid,
                sop_class_uid=sop_class_uid,
                error_message="Storage limit reached"
            )
            return 0xA700  # Refused: Out of Resources
        
        # Determine storage path (pass ds which may be None)
        storage_path = _get_storage_path(service, ds, fresh_config)
        os.makedirs(storage_path, exist_ok=True)
        
        # Determine filename (pass ds which may be None)
        filename = _get_filename(service, ds, fresh_config)
        file_path = os.path.join(storage_path, filename)
        
        # OPTIMIZATION: Write raw encoded dataset directly to file
        # This is MUCH faster than ds.save_as() as it skips decode/re-encode
        with open(file_path, 'wb') as f:
            # Write preamble, prefix, file meta information and raw dataset
            f.write(event.encoded_dataset())
        
        file_size = os.path.getsize(file_path)
        
        # Calculate transfer speed
        duration = time.time() - start_time
        transfer_speed_mbps = (file_size / (1024 * 1024)) / duration if duration > 0 else 0
        
        # Log the transaction (use fresh config)
        if fresh_config.log_received_files:
            logger.info(f"C-STORE: Received {filename} from {calling_ae} ({file_size} bytes)")
        
        service._log_transaction(
            'C-STORE',
            'SUCCESS',
            event,
            patient_id=patient_id,
            study_instance_uid=study_uid,
            series_instance_uid=series_uid,
            sop_instance_uid=sop_instance_uid,
            sop_class_uid=sop_class_uid,
            file_path=file_path,
            file_size_bytes=file_size,
            transfer_syntax=str(event.context.transfer_syntax),
            duration_seconds=duration,
            transfer_speed_mbps=transfer_speed_mbps
        )
        
        # Update service statistics asynchronously (non-blocking)
        from ..tasks import update_service_status_async, update_storage_cache_async
        
        update_service_status_async.delay({
            'total_files_received': 1,
            'total_bytes_received': file_size,
            'last_file_received_at': timezone.now()
        })
        
        # Incrementally update storage cache asynchronously (non-blocking)
        update_storage_cache_async.delay(file_size)
        
        # Invalidate memcached storage check to force refresh on next check
        # This ensures the cache stays reasonably accurate after file additions
        cache.delete(STORAGE_CACHE_KEY)
        
        # Note: DICOM Handler integration is handled by the dicom_handler app
        # Files stored here will be automatically picked up by the handler's polling mechanism
        
        return 0x0000  # Success
        
    except InvalidDicomError as e:
        logger.error(f"C-STORE failed: Invalid DICOM - {str(e)}")
        service._log_transaction(
            'C-STORE',
            'FAILURE',
            event,
            error_message=f"Invalid DICOM: {str(e)}"
        )
        # Update error count asynchronously to avoid blocking
        from ..tasks import update_service_status_async
        update_service_status_async.delay({'total_errors': 1})
        return 0xC000  # Error: Cannot understand
        
    except Exception as e:
        logger.error(f"C-STORE failed: {str(e)}")
        service._log_transaction(
            'C-STORE',
            'FAILURE',
            event,
            error_message=str(e)
        )
        # Update error count asynchronously to avoid blocking
        from ..tasks import update_service_status_async
        update_service_status_async.delay({'total_errors': 1})
        return 0xC000  # Error: Cannot understand


def _validate_dicom_dataset(ds):
    """
    Validate DICOM dataset has required tags.
    """
    required_tags = ['PatientID', 'StudyInstanceUID', 'SeriesInstanceUID', 'SOPInstanceUID']
    
    for tag in required_tags:
        if not hasattr(ds, tag):
            logger.warning(f"DICOM validation failed: Missing required tag {tag}")
            return False
    
    return True


def _check_storage_limits(service):
    """
    Check if storage limits have been reached.
    Uses memcached to avoid expensive filesystem scans on every file.
    Cache is valid for 30 seconds, then refreshed on next check.
    
    OPTIMIZATION: Uses cached config from service to avoid repeated DB queries
    """
    try:
        from ..models import DicomServerConfig
        
        # Use cached config from service to avoid DB query on every file
        # Only fetch fresh config if cache is stale
        if hasattr(service, 'config') and service.config:
            dicom_config = service.config
        else:
            dicom_config = DicomServerConfig.objects.get(pk=1)
        
        system_config = SystemConfiguration.objects.get(pk=1)
        storage_path = system_config.folder_configuration
        max_storage_gb = dicom_config.max_storage_size_gb
        
        if not storage_path:
            return True
        
        # Try to get cached storage usage
        current_usage_gb = cache.get(STORAGE_CACHE_KEY)
        
        if current_usage_gb is None:
            # Cache miss - perform actual filesystem scan
            usage = get_storage_usage(storage_path)
            current_usage_gb = usage['total_gb']
            
            # Cache the result for 30 seconds
            cache.set(STORAGE_CACHE_KEY, current_usage_gb, STORAGE_CACHE_TIMEOUT)
            logger.debug(f"Storage check (cached): {current_usage_gb}GB used / {max_storage_gb}GB max")
        else:
            # Cache hit - use cached value (no filesystem scan)
            logger.debug(f"Storage check (from cache): {current_usage_gb}GB used / {max_storage_gb}GB max")
        
        # Check if limit reached
        if current_usage_gb >= max_storage_gb:
            if dicom_config.enable_storage_cleanup:
                # Attempt automatic cleanup
                logger.warning(f"Storage limit reached: {current_usage_gb}GB / {max_storage_gb}GB. Attempting cleanup...")
                cleanup_performed = check_and_cleanup_if_needed(service)
                
                if cleanup_performed:
                    # Re-check storage after cleanup and update cache
                    usage = get_storage_usage(storage_path)
                    current_usage_gb = usage['total_gb']
                    cache.set(STORAGE_CACHE_KEY, current_usage_gb, STORAGE_CACHE_TIMEOUT)
                    
                    if current_usage_gb >= max_storage_gb:
                        logger.error("Storage still full after cleanup")
                        return False
                    else:
                        logger.info(f"Cleanup successful, storage now at {current_usage_gb}GB / {max_storage_gb}GB")
                else:
                    logger.error("Cleanup failed or not enough old files to delete")
                    return False
            else:
                logger.error(f"Storage limit reached: {current_usage_gb}GB / {max_storage_gb}GB")
                return False
                
    except Exception as e:
        logger.warning(f"Error checking storage limits: {str(e)}")
    
    return True


def _get_storage_path(service, ds, fresh_config=None):
    """
    Determine storage path based on configuration.
    
    Args:
        service: DicomSCPService instance
        ds: DICOM dataset (may be None if not decoded)
        fresh_config: Fresh configuration (optional, will fetch if not provided)
    """
    # Get base path from SystemConfiguration and fresh config for structure
    try:
        from ..models import DicomServerConfig
        system_config = SystemConfiguration.objects.get(pk=1)
        if fresh_config is None:
            fresh_config = DicomServerConfig.objects.get(pk=1)
        base_path = system_config.folder_configuration
    except:
        base_path = '/app/datastore'  # Fallback
        if fresh_config is None:
            fresh_config = service.config  # Fallback to cached
    
    structure = fresh_config.storage_structure
    
    if structure == 'flat':
        return base_path
    
    elif structure == 'patient':
        patient_id = getattr(ds, 'PatientID', 'UNKNOWN') if ds else 'UNKNOWN'
        # Sanitize patient ID for filesystem
        patient_id = _sanitize_for_filesystem(patient_id)
        return os.path.join(base_path, patient_id)
    
    elif structure == 'study':
        study_uid = getattr(ds, 'StudyInstanceUID', 'UNKNOWN') if ds else 'UNKNOWN'
        return os.path.join(base_path, study_uid)
    
    elif structure == 'series':
        patient_id = getattr(ds, 'PatientID', 'UNKNOWN') if ds else 'UNKNOWN'
        study_uid = getattr(ds, 'StudyInstanceUID', 'UNKNOWN') if ds else 'UNKNOWN'
        series_uid = getattr(ds, 'SeriesInstanceUID', 'UNKNOWN') if ds else 'UNKNOWN'
        
        patient_id = _sanitize_for_filesystem(patient_id)
        
        return os.path.join(base_path, patient_id, study_uid, series_uid)
    
    elif structure == 'date':
        now = datetime.now()
        return os.path.join(base_path, now.strftime('%Y'), now.strftime('%m'), now.strftime('%d'))
    
    else:
        return base_path


def _get_filename(service, ds, fresh_config=None):
    """
    Determine filename based on configuration.
    
    Args:
        service: DicomSCPService instance
        ds: DICOM dataset (may be None if not decoded)
        fresh_config: Fresh configuration (optional, will fetch if not provided)
    """
    # Get fresh config for naming convention
    try:
        from ..models import DicomServerConfig
        if fresh_config is None:
            fresh_config = DicomServerConfig.objects.get(pk=1)
        naming = fresh_config.file_naming_convention
    except:
        naming = service.config.file_naming_convention if service.config else 'timestamp'
    
    if naming == 'sop_uid' and ds:
        sop_uid = getattr(ds, 'SOPInstanceUID', None)
        if sop_uid:
            return f"{sop_uid}.dcm"
    
    elif naming == 'instance_number' and ds:
        instance_number = getattr(ds, 'InstanceNumber', None)
        if instance_number:
            return f"{instance_number:04d}.dcm"
    
    elif naming == 'timestamp':
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        return f"{timestamp}.dcm"
    
    elif naming == 'sequential':
        # Generate sequential number based on existing files
        # This is a simple implementation - could be improved
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        return f"{timestamp}.dcm"
    
    # Default fallback
    if ds:
        sop_uid = getattr(ds, 'SOPInstanceUID', datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    else:
        sop_uid = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    return f"{sop_uid}.dcm"


def _sanitize_for_filesystem(value):
    """
    Sanitize string for use in filesystem paths.
    Replaces special characters with underscores.
    """
    import re
    # Replace any non-alphanumeric characters (except dash and underscore) with underscore
    sanitized = re.sub(r'[^a-zA-Z0-9_\-]', '_', str(value))
    # Remove multiple consecutive underscores
    sanitized = re.sub(r'_+', '_', sanitized)
    # Strip leading/trailing underscores
    sanitized = sanitized.strip('_')
    return sanitized if sanitized else 'UNKNOWN'


def _trigger_dicom_handler_integration(service, file_path, ds):
    """
    Trigger integration with DICOM Handler processing chain.
    """
    try:
        # Get fresh config for handler integration settings
        from ..models import DicomServerConfig
        fresh_config = DicomServerConfig.objects.get(pk=1)
        
        if fresh_config.copy_to_handler_folder:
            # Copy file to DICOM Handler folder
            from dicom_handler.models import SystemConfiguration
            system_config = SystemConfiguration.objects.get(pk=1)
            handler_folder = system_config.folder_configuration
            
            if handler_folder and os.path.exists(handler_folder):
                import shutil
                
                # Recreate directory structure in handler folder
                patient_id = getattr(ds, 'PatientID', 'UNKNOWN')
                study_uid = getattr(ds, 'StudyInstanceUID', 'UNKNOWN')
                series_uid = getattr(ds, 'SeriesInstanceUID', 'UNKNOWN')
                
                patient_id = _sanitize_for_filesystem(patient_id)
                
                dest_dir = os.path.join(handler_folder, patient_id, study_uid, series_uid)
                os.makedirs(dest_dir, exist_ok=True)
                
                filename = os.path.basename(file_path)
                dest_path = os.path.join(dest_dir, filename)
                
                shutil.copy2(file_path, dest_path)
                logger.info(f"Copied DICOM file to handler folder: {dest_path}")
        
        if fresh_config.trigger_processing_chain:
            # Trigger the DICOM processing chain
            # This would typically be done via Celery task
            logger.info("Processing chain trigger configured but not yet implemented")
            # TODO: Implement Celery task trigger for processing chain
            
    except Exception as e:
        logger.error(f"Failed to trigger DICOM Handler integration: {str(e)}")
