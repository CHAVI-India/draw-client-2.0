"""
C-STORE handler for receiving DICOM files.
"""

import os
import logging
import time
from pathlib import Path
from datetime import datetime
from threading import Lock

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

# Series reception tracking for detecting series completion
# Structure: {ae_title: {'current_series_uid': str, 'instance_count': int, 'sop_uids': set, 'last_received': datetime}}
_series_reception_state = {}
_series_state_lock = Lock()


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
    logger.info(f"[TIMING] C-STORE handler started at {time.time()}")
    
    calling_ae = event.assoc.requestor.ae_title
    remote_ip = event.assoc.requestor.address
    
    try:
        # Use cached config from service to avoid DB query on every file
        # The service config is refreshed periodically by the service itself
        t1 = time.time()
        fresh_config = service.config
        logger.info(f"[TIMING] Got config in {(time.time() - t1)*1000:.2f}ms")
        
        # Validate calling AE if required
        t2 = time.time()
        ae_valid = service._validate_calling_ae(calling_ae)
        logger.info(f"[TIMING] AE validation took {(time.time() - t2)*1000:.2f}ms")
        if not ae_valid:
            logger.warning(f"C-STORE rejected: Calling AE '{calling_ae}' not authorized")
            service._log_transaction(
                'C-STORE',
                'REJECTED',
                event,
                error_message=f"Calling AE '{calling_ae}' not authorized"
            )
            return 0xA700  # Refused: Out of Resources
        
        # Validate remote IP if required
        t3 = time.time()
        if not service._validate_remote_ip(remote_ip):
            logger.info(f"[TIMING] IP validation took {(time.time() - t3)*1000:.2f}ms")
            logger.warning(f"C-STORE rejected: Remote IP '{remote_ip}' not authorized")
            service._log_transaction(
                'C-STORE',
                'REJECTED',
                event,
                error_message=f"Remote IP '{remote_ip}' not authorized"
            )
            return 0xA700  # Refused: Out of Resources
        
        logger.info(f"[TIMING] IP validation took {(time.time() - t3)*1000:.2f}ms")
        
        # OPTIMIZATION: Only decode dataset if validation or metadata extraction is needed
        # This avoids the expensive decode operation when not required
        t4 = time.time()
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
            logger.info(f"[TIMING] Needs decoding check took {(time.time() - t4)*1000:.2f}ms")
            t5 = time.time()
            
            # CRITICAL FIX: Access event.encoded_dataset() first to trigger efficient byte reception
            # Then decode from bytes, which is much faster than event.dataset property
            from pydicom import dcmread
            from io import BytesIO
            
            encoded_data = event.encoded_dataset()
            logger.info(f"[TIMING] Received encoded data ({len(encoded_data)} bytes) in {(time.time() - t5)*1000:.2f}ms")
            
            t5b = time.time()
            ds = dcmread(BytesIO(encoded_data), force=True)
            ds.file_meta = event.file_meta
            logger.info(f"[TIMING] Dataset decode from bytes took {(time.time() - t5b)*1000:.2f}ms")
            logger.info(f"[TIMING] About to start DICOM validation")
            
            # Validate DICOM if required (use fresh config)
            t5a = time.time()
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
            logger.info(f"[TIMING] DICOM validation took {(time.time() - t5a)*1000:.2f}ms")
            
            # Extract DICOM metadata
            t5b = time.time()
            patient_id = getattr(ds, 'PatientID', None)
            study_uid = getattr(ds, 'StudyInstanceUID', None)
            series_uid = getattr(ds, 'SeriesInstanceUID', None)
            sop_instance_uid = getattr(ds, 'SOPInstanceUID', None)
            sop_class_uid = getattr(ds, 'SOPClassUID', None)
            logger.info(f"[TIMING] Metadata extraction took {(time.time() - t5b)*1000:.2f}ms")
        else:
            logger.info(f"[TIMING] Skipped decoding (took {(time.time() - t4)*1000:.2f}ms to check)")
        
        # Check storage limits - simple flag check (updated by periodic task every 10 min)
        t6 = time.time()
        if fresh_config.storage_limit_exceeded:
            logger.info(f"[TIMING] Storage limits check took {(time.time() - t6)*1000:.2f}ms")
            logger.error("C-STORE rejected: Storage limit reached (checked by periodic task)")
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
        
        logger.info(f"[TIMING] Storage limits check took {(time.time() - t6)*1000:.2f}ms")

        # Determine storage path (pass ds which may be None)
        t7 = time.time()
        storage_path = _get_storage_path(service, ds, fresh_config)
        os.makedirs(storage_path, exist_ok=True)
        logger.info(f"[TIMING] Get storage path took {(time.time() - t7)*1000:.2f}ms")
        
        # Determine filename (pass ds which may be None)
        t8 = time.time()
        filename = _get_filename(service, ds, fresh_config)
        file_path = os.path.join(storage_path, filename)
        logger.info(f"[TIMING] Get filename took {(time.time() - t8)*1000:.2f}ms")
        
        # OPTIMIZATION: Write raw encoded dataset directly to file
        # This is MUCH faster than ds.save_as() as it skips decode/re-encode
        t9 = time.time()
        with open(file_path, 'wb') as f:
            # Write preamble, prefix, file meta information and raw dataset
            f.write(event.encoded_dataset())
        logger.info(f"[TIMING] File write took {(time.time() - t9)*1000:.2f}ms")
        
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
        
        # NOTE: We do NOT delete the cache here to avoid expensive filesystem scans
        # The cache will expire naturally after 30 seconds, which is acceptable
        # for performance. Storage usage will be slightly stale but accurate enough.
        
        # Trigger DICOM Handler integration for immediate processing (when ds is available)
        # This enables immediate processing for C-Store requests, bypassing the 10-minute delay
        if ds is not None:
            _trigger_dicom_handler_integration(service, file_path, ds, calling_ae)
        else:
            logger.debug("[C-STORE] Skipping immediate processing trigger - DICOM dataset not decoded")
        
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
        from django.core.cache import cache as django_cache
        
        # Use cached config from service to avoid DB query on every file
        dicom_config = service.config
        
        # Cache SystemConfiguration to avoid DB query on every file
        system_config_cache_key = 'system_configuration_storage_path'
        storage_path = django_cache.get(system_config_cache_key)
        
        if storage_path is None:
            # Cache miss - query database
            system_config = SystemConfiguration.objects.get(pk=1)
            storage_path = system_config.folder_configuration
            # Cache for 60 seconds
            django_cache.set(system_config_cache_key, storage_path, 60)
        
        max_storage_gb = dicom_config.max_storage_size_gb
        
        if not storage_path:
            return True
        
        # Try to get cached storage usage
        t_cache = time.time()
        current_usage_gb = cache.get(STORAGE_CACHE_KEY)
        logger.info(f"[TIMING] Cache lookup took {(time.time() - t_cache)*1000:.2f}ms, result: {current_usage_gb}")
        
        if current_usage_gb is None:
            # Cache miss - perform actual filesystem scan
            logger.warning(f"[PERFORMANCE] Cache miss for storage usage - performing expensive filesystem scan")
            t_scan = time.time()
            usage = get_storage_usage(storage_path)
            logger.warning(f"[PERFORMANCE] Filesystem scan took {(time.time() - t_scan)*1000:.2f}ms for {usage['total_files']} files")
            current_usage_gb = usage['total_gb']
            
            # Cache the result for 30 seconds
            t_set = time.time()
            cache.set(STORAGE_CACHE_KEY, current_usage_gb, STORAGE_CACHE_TIMEOUT)
            logger.info(f"[TIMING] Cache set took {(time.time() - t_set)*1000:.2f}ms")
            logger.debug(f"Storage check (cached): {current_usage_gb}GB used / {max_storage_gb}GB max")
        else:
            # Cache hit - use cached value (no filesystem scan)
            logger.info(f"[PERFORMANCE] Cache HIT - using cached storage value: {current_usage_gb}GB")
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


def _track_series_reception_and_trigger(ae_title, series_uid, sop_uid, file_path):
    """
    Track series reception and trigger Task2 when a series is complete.
    
    Machines send series sequentially - when we receive a new Series UID for an AE Title,
    the previous series is complete and we can trigger Task2 immediately.
    
    Args:
        ae_title: The calling AE Title
        series_uid: Current series instance UID
        sop_uid: SOP Instance UID of the received file
        file_path: Path to the saved DICOM file
    
    Returns:
        dict: Result with information about any triggered series
    """
    global _series_reception_state, _series_state_lock
    
    triggered_series = None
    
    with _series_state_lock:
        ae_state = _series_reception_state.get(ae_title, {})
        current_series = ae_state.get('current_series_uid')
        
        # If this is a NEW series for this AE Title, the previous one is complete
        if current_series and current_series != series_uid:
            # Previous series is complete - trigger Task2
            logger.info(f"[C-STORE] Series change detected for AE '{ae_title}': "
                       f"'{current_series[:8]}...' -> '{series_uid[:8]}...'")
            triggered_series = _trigger_task2_for_series(ae_title, current_series)
        
        # Update tracking state for current series
        if current_series != series_uid:
            # New series started
            ae_state = {
                'current_series_uid': series_uid,
                'instance_count': 1,
                'sop_uids': {sop_uid},
                'last_received': timezone.now(),
                'file_paths': [file_path]
            }
        else:
            # Continuing same series
            ae_state['instance_count'] += 1
            ae_state['sop_uids'].add(sop_uid)
            ae_state['last_received'] = timezone.now()
            ae_state['file_paths'].append(file_path)
        
        _series_reception_state[ae_title] = ae_state
        
        logger.info(f"[C-STORE] AE '{ae_title}' tracking series '{series_uid[:8]}...': "
                   f"{ae_state['instance_count']} instances received")
    
    return {
        'current_series': series_uid,
        'instance_count': ae_state['instance_count'],
        'triggered_series': triggered_series
    }


def _trigger_task2_for_series(ae_title, series_uid):
    """
    Trigger the processing chain for a completed series.
    
    Marks the series as fully read and triggers Task2->Task3->Task4 chain
    for autosegmentation, deidentification, and export.
    
    Args:
        ae_title: The calling AE Title
        series_uid: The completed series instance UID
    
    Returns:
        dict: Trigger result with chain ID
    """
    try:
        from celery import chain
        from dicom_handler.models import DICOMSeries, ProcessingStatus
        from dicom_handler.tasks import (
            task2_match_autosegmentation_template_celery,
            task3_deidentify_series_celery,
            task4_export_series_to_api_celery
        )
        
        # Find the series in database
        try:
            series = DICOMSeries.objects.get(series_instance_uid=series_uid)
        except DICOMSeries.DoesNotExist:
            logger.warning(f"[C-STORE] Cannot trigger chain: Series '{series_uid[:8]}...' not found in database")
            return {'status': 'error', 'reason': 'series_not_found'}
        
        # Mark series as fully read and update status to prevent Task1 reprocessing
        series.series_files_fully_read = True
        series.series_processsing_status = ProcessingStatus.RULE_MATCHED  # Chain triggered, not UNPROCESSED
        series.save()
        
        logger.info(f"[C-STORE] Series '{series_uid[:8]}...' marked as complete ({series.instance_count} instances). "
                   f"Triggering processing chain (Task2→Task3→Task4).")
        
        # Prepare series data for Task2 in the format it expects
        # Task2 expects: {"status": "success", "series_data": [...]}
        task_input = {
            "status": "success",
            'series_data': [{
                'series_instance_uid': series_uid,
                'series_root_path': series.series_root_path,
                'study_instance_uid': series.study.study_instance_uid,
                'patient_id': series.study.patient.patient_id,
                'modality': series.study.study_modality,
                'instance_count': series.instance_count,
                'first_instance_path': series.dicominstance_set.first().instance_path if series.dicominstance_set.exists() else None
            }]
        }
        
        # Create the Celery chain: Task2 -> Task3 -> Task4
        task_chain = chain(
            task2_match_autosegmentation_template_celery.s(task_input),
            task3_deidentify_series_celery.s(),
            task4_export_series_to_api_celery.s()
        )
        
        # Execute the chain
        async_result = task_chain.apply_async()
        
        logger.info(f"[C-STORE] Processing chain triggered for series '{series_uid[:8]}...' with chain_id: {async_result.id}")
        
        return {
            'status': 'triggered',
            'series_uid': series_uid,
            'chain_id': async_result.id,
            'instance_count': series.instance_count
        }
        
    except Exception as e:
        logger.error(f"[C-STORE] Error triggering chain for series '{series_uid[:8]}...': {str(e)}")
        return {'status': 'error', 'message': str(e)}


def finalize_series_for_ae_title(ae_title):
    """
    Finalize any pending series for an AE Title when association closes.
    
    Called when a C-STORE association is released to ensure the last series
    is marked as complete and Task2 is triggered.
    
    Args:
        ae_title: The calling AE Title whose association is closing
    
    Returns:
        dict: Finalization result with triggered series info
    """
    global _series_reception_state, _series_state_lock
    
    triggered_series = None
    
    with _series_state_lock:
        ae_state = _series_reception_state.get(ae_title)
        if ae_state:
            current_series = ae_state.get('current_series_uid')
            if current_series:
                logger.info(f"[C-STORE] Association closed for AE '{ae_title}', "
                           f"finalizing series '{current_series[:8]}...'")
                triggered_series = _trigger_task2_for_series(ae_title, current_series)
            
            # Clear the AE state
            del _series_reception_state[ae_title]
    
    return {
        'status': 'finalized',
        'ae_title': ae_title,
        'triggered_series': triggered_series
    }


def _process_cstore_file_to_database(file_path, ds, ae_title=None):
    """
    Process a C-Store DICOM file and create database records.
    
    This function creates database records (Patient, Study, Series, Instance) for
    the incoming DICOM file. When a series change is detected (new Series UID from
    the same AE Title), it triggers Task2 for the completed series.
    
    Args:
        file_path: Path to the saved DICOM file
        ds: DICOM dataset (already decoded by handle_c_store)
        ae_title: The calling AE Title (for series tracking)
    
    Returns:
        dict: Processing result with series information
    """
    try:
        from datetime import datetime
        from django.db import transaction
        from dicom_handler.models import (
            SystemConfiguration, Patient, DICOMStudy, DICOMSeries,
            DICOMInstance, ProcessingStatus
        )
        
        logger.info(f"[C-STORE] Starting database registration for file: {file_path}")
        
        # Validate required tags
        required_tags = ['PatientID', 'StudyInstanceUID', 'SeriesInstanceUID', 'SOPInstanceUID', 'Modality']
        for tag in required_tags:
            if not hasattr(ds, tag):
                logger.warning(f"[C-STORE] Missing required tag {tag}, skipping processing chain trigger")
                return {"status": "skipped", "reason": f"missing_tag_{tag}"}
        
        # Only process CT/MR/PT modalities (same as task1)
        modality = ds.Modality
        if modality not in ['CT', 'MR', 'PT']:
            logger.info(f"[C-STORE] Skipping modality {modality} - not CT/MR/PT")
            return {"status": "skipped", "reason": "unsupported_modality"}
        
        # Extract metadata
        patient_id = getattr(ds, 'PatientID', '')
        patient_name = str(getattr(ds, 'PatientName', ''))
        patient_gender = getattr(ds, 'PatientSex', '')
        patient_birth_date = getattr(ds, 'PatientBirthDate', None)
        
        study_instance_uid = getattr(ds, 'StudyInstanceUID', '')
        study_date = getattr(ds, 'StudyDate', None)
        study_time = getattr(ds, 'StudyTime', None)
        study_description = getattr(ds, 'StudyDescription', '')
        study_protocol = getattr(ds, 'ProtocolName', '')
        accession_number = getattr(ds, 'AccessionNumber', '')
        study_id = getattr(ds, 'StudyID', '')
        
        series_instance_uid = getattr(ds, 'SeriesInstanceUID', '')
        series_date = getattr(ds, 'SeriesDate', None)
        series_description = getattr(ds, 'SeriesDescription', '')
        frame_of_reference_uid = getattr(ds, 'FrameOfReferenceUID', '')
        sop_instance_uid = getattr(ds, 'SOPInstanceUID', '')
        
        # Track series reception and trigger Task2 if previous series is complete
        tracking_result = None
        if ae_title:
            tracking_result = _track_series_reception_and_trigger(
                ae_title, series_instance_uid, sop_instance_uid, file_path
            )
        
        # Get series root path
        series_root_path = os.path.dirname(file_path)
        
        # Convert dates
        if patient_birth_date:
            try:
                patient_birth_date = datetime.strptime(str(patient_birth_date), '%Y%m%d').date()
            except:
                patient_birth_date = None
        
        if study_date:
            try:
                study_date = datetime.strptime(str(study_date), '%Y%m%d').date()
            except:
                study_date = None
        
        study_time_parsed = None
        if study_time:
            try:
                time_str = str(study_time)
                if '.' in time_str:
                    time_str = time_str.split('.')[0]
                time_str = time_str.ljust(6, '0')
                study_time_parsed = datetime.strptime(time_str[:6], '%H%M%S').time()
            except:
                study_time_parsed = None
        
        if series_date:
            try:
                series_date = datetime.strptime(str(series_date), '%Y%m%d').date()
            except:
                series_date = None
        
        # Create database records within transaction
        with transaction.atomic():
            # Get or create patient
            patient, _ = Patient.objects.get_or_create(
                patient_id=patient_id,
                defaults={
                    'patient_name': patient_name,
                    'patient_gender': patient_gender,
                    'patient_date_of_birth': patient_birth_date
                }
            )
            
            # Get or create study
            study, _ = DICOMStudy.objects.get_or_create(
                patient=patient,
                study_instance_uid=study_instance_uid,
                defaults={
                    'study_date': study_date,
                    'study_time': study_time_parsed,
                    'study_description': study_description,
                    'study_protocol': study_protocol,
                    'study_modality': modality,
                    'accession_number': accession_number,
                    'study_id': study_id
                }
            )
            
            # Get or create series
            series, created = DICOMSeries.objects.get_or_create(
                study=study,
                series_instance_uid=series_instance_uid,
                defaults={
                    'series_root_path': series_root_path,
                    'frame_of_reference_uid': frame_of_reference_uid,
                    'series_description': series_description,
                    'series_date': series_date,
                    'series_processsing_status': ProcessingStatus.UNPROCESSED,
                    'instance_count': 0,
                    'series_files_fully_read': False
                }
            )
            
            # Check if instance already exists
            instance_exists = DICOMInstance.objects.filter(sop_instance_uid=sop_instance_uid).exists()
            if instance_exists:
                logger.info(f"[C-STORE] Instance {sop_instance_uid[:8]}... already exists, skipping")
                return {"status": "skipped", "reason": "duplicate_instance"}
            
            # Create instance
            DICOMInstance.objects.create(
                series_instance_uid=series,
                sop_instance_uid=sop_instance_uid,
                instance_path=file_path
            )
            
            # Update instance count
            series.instance_count = DICOMInstance.objects.filter(series_instance_uid=series).count()
            series.save()
            
            logger.info(f"[C-STORE] Created/updated series {series_instance_uid[:8]}... with {series.instance_count} instances")
        
        # Track series reception state (triggers Task2 when series changes)
        if tracking_result and tracking_result.get('triggered_series'):
            triggered = tracking_result['triggered_series']
            logger.info(f"[C-STORE] Previous series '{triggered['series_uid'][:8]}...' was completed and Task2 triggered")
        
        return {
            "status": "success",
            "series_uid": series_instance_uid,
            "instance_count": series.instance_count,
            "note": "DB records created. Task2 triggered when series changes."
        }
        
    except Exception as e:
        logger.error(f"[C-STORE] Error in immediate processing: {str(e)}")
        import traceback
        traceback.print_exc()
        return {"status": "error", "message": str(e)}


def _trigger_dicom_handler_integration(service, file_path, ds, ae_title=None):
    """
    Trigger integration with DICOM Handler processing chain.
    
    For C-Store requests, tracks series reception by AE Title and triggers Task2
    when a series change is detected (indicating the previous series is complete).
    This avoids the 10-minute delay for sequential series transfers.
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
                
                # Skip copy if source and destination are the same file
                if os.path.abspath(file_path) == os.path.abspath(dest_path):
                    logger.debug(f"File already in handler folder, skipping copy: {dest_path}")
                else:
                    shutil.copy2(file_path, dest_path)
                    logger.info(f"Copied DICOM file to handler folder: {dest_path}")
        
        if fresh_config.trigger_processing_chain:
            # For C-Store requests, immediately process and track series
            # Task2 is triggered when series change is detected (avoids 10-min delay)
            _process_cstore_file_to_database(file_path, ds, ae_title)
            
    except Exception as e:
        logger.error(f"Failed to trigger DICOM Handler integration: {str(e)}")
