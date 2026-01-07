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

from ..models import DicomTransaction
from ..storage_cleanup import check_and_cleanup_if_needed, get_storage_usage
from dicom_handler.models import SystemConfiguration

logger = logging.getLogger(__name__)


def handle_c_store(service, event):
    """
    Handle C-STORE request - receive and store DICOM file.
    
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
        
        # Get the dataset
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
                    service.service_status.total_errors += 1
                    service.service_status.save()
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
        
        # Determine storage path
        storage_path = _get_storage_path(service, ds)
        os.makedirs(storage_path, exist_ok=True)
        
        # Determine filename
        filename = _get_filename(service, ds)
        file_path = os.path.join(storage_path, filename)
        
        # Save the DICOM file
        ds.save_as(file_path, enforce_file_format=True)
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
        
        # Update service statistics
        service.service_status.total_files_received += 1
        service.service_status.total_bytes_received += file_size
        service.service_status.last_file_received_at = timezone.now()
        service.service_status.save()
        
        # Incrementally update storage cache (fast operation) - use fresh config
        fresh_config.cached_storage_usage_bytes += file_size
        fresh_config.save(update_fields=['cached_storage_usage_bytes'])
        
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
        service.service_status.total_errors += 1
        service.service_status.save()
        return 0xC000  # Error: Cannot understand
        
    except Exception as e:
        logger.error(f"C-STORE failed: {str(e)}")
        service._log_transaction(
            'C-STORE',
            'FAILURE',
            event,
            error_message=str(e)
        )
        service.service_status.total_errors += 1
        service.service_status.save()
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
    """
    try:
        from ..models import DicomServerConfig
        
        # Always fetch fresh configuration from database to avoid stale cached values
        dicom_config = DicomServerConfig.objects.get(pk=1)
        system_config = SystemConfiguration.objects.get(pk=1)
        storage_path = system_config.folder_configuration
        
        if storage_path:
            usage = get_storage_usage(storage_path)
            current_usage_gb = usage['total_gb']
            max_storage_gb = dicom_config.max_storage_size_gb
            
            logger.info(f"Storage check: {current_usage_gb}GB used / {max_storage_gb}GB max")
            
            if current_usage_gb >= max_storage_gb:
                if dicom_config.enable_storage_cleanup:
                    # Attempt automatic cleanup
                    logger.warning(f"Storage limit reached: {current_usage_gb}GB / {max_storage_gb}GB. Attempting cleanup...")
                    cleanup_performed = check_and_cleanup_if_needed(service)
                    
                    if cleanup_performed:
                        # Re-check storage after cleanup
                        usage = get_storage_usage(storage_path)
                        current_usage_gb = usage['total_gb']
                        
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


def _get_storage_path(service, ds):
    """
    Determine storage path based on configuration.
    """
    # Get base path from SystemConfiguration and fresh config for structure
    try:
        from ..models import DicomServerConfig
        system_config = SystemConfiguration.objects.get(pk=1)
        fresh_config = DicomServerConfig.objects.get(pk=1)
        base_path = system_config.folder_configuration
    except:
        base_path = '/app/datastore'  # Fallback
        fresh_config = service.config  # Fallback to cached
    
    structure = fresh_config.storage_structure
    
    if structure == 'flat':
        return base_path
    
    elif structure == 'patient':
        patient_id = getattr(ds, 'PatientID', 'UNKNOWN')
        # Sanitize patient ID for filesystem
        patient_id = _sanitize_for_filesystem(patient_id)
        return os.path.join(base_path, patient_id)
    
    elif structure == 'study':
        study_uid = getattr(ds, 'StudyInstanceUID', 'UNKNOWN')
        return os.path.join(base_path, study_uid)
    
    elif structure == 'series':
        patient_id = getattr(ds, 'PatientID', 'UNKNOWN')
        study_uid = getattr(ds, 'StudyInstanceUID', 'UNKNOWN')
        series_uid = getattr(ds, 'SeriesInstanceUID', 'UNKNOWN')
        
        patient_id = _sanitize_for_filesystem(patient_id)
        
        return os.path.join(base_path, patient_id, study_uid, series_uid)
    
    elif structure == 'date':
        now = datetime.now()
        return os.path.join(base_path, now.strftime('%Y'), now.strftime('%m'), now.strftime('%d'))
    
    else:
        return base_path


def _get_filename(service, ds):
    """
    Determine filename based on configuration.
    """
    # Get fresh config for naming convention
    try:
        from ..models import DicomServerConfig
        fresh_config = DicomServerConfig.objects.get(pk=1)
        naming = fresh_config.file_naming_convention
    except:
        naming = service.config.file_naming_convention  # Fallback to cached
    
    if naming == 'sop_uid':
        sop_uid = getattr(ds, 'SOPInstanceUID', None)
        if sop_uid:
            return f"{sop_uid}.dcm"
    
    elif naming == 'instance_number':
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
    sop_uid = getattr(ds, 'SOPInstanceUID', datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
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
