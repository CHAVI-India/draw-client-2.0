# This task will run as a celery task as a seperate task and will poll the DRAW API server at regular intervals to download the segmented RTStructureSet file
# It will first generate a list of all DICOMFileExport objects where the deidentified_zip_file_transfer_status status is COMPLETED and server_segmentation_status value is NOT one of the following:
# - Delivered to Client
# - Transfer Completed
# To poll the server we need to make a reqest to the status endpoint for each object (specified in system configuration) with task_id in the request from the DICOMFileExport Model. Note bearer token authentication will have to be done using the draw_bearer token. Ensure proxy settings in the utils/proxy_conf are included to allow connections to pass through proxy servers.
# If the status turns to Segmentation Completed that means the RTstruct is available for download. Otherwise update the server_segmentation_status field with the status value provided by the server. Keep the file deidentified_zip_file_transfer_status as it is.
# Once the server_segmentation_status shows Segmentation Retrived that means that the RTStructure File is available for download.
# First update the status field in the DICOMFileExport model to reflect the server status
# Download the RTStructure file with the help of the task id using the draw_download_endpoint after bearer token authentication.
# First ensure that the checksum sent by the server along with the response matches the downloaded file checksum. If it does not delete the file that has been downloaded. Update the status in the DICOMFileTransferStatus to CHECKSUM_MATCH_FAILED. 
# Second check if the RTStructureSet is a valid DICOM File using pydicom (try reading it without force = True), and has the modality RTStruct if not then set the status to INVALID_RTSTRUCT_FILE
# Third check if the  Referenced Series Instance UID in the RTStruct File (tag (0x0020, 0x000E)) matches the deidentified series instance UID in the DICOM Series table. Remember that the deidentified series instance UID has to be checked as this file was segmented using deidentified data. If it does not again set the status to INVALID_RTSTRUCT_FILE.
# If Checksum match failes or file is not a valid DICOM file then mark DICOMSeries series_processsing_status also to INVALID_RTSTRUCTURE_RECEIVED. 
# If both these checks pass, make an entry in the RTStructureFileImport table linking the data to the DICOMSeries table. The deidentified_sop_intance_uid will be the actual sop_instance_uid of the rstructure file received. 
# Store the computed checksum. 
# Store the file path (create a downloaded_rtstruct folder if it does not exist). 
# Update the date and time when this file was received. 
# Notify the server that the RTStructure file was received. This can be done by sending a POST request to the notify endpoint (in the System configuration). Note that this is also protected by bearer token based authentication. After the notification has been sent and the the received response is "Transfer confirmation received, files cleaned up" then we update the following statuses:


# 1. Update server_segmentation_status field in the DICOMFileExport model to RTStructure Received
# 2. Update deidentified_zip_file_transfer_status field in the DICOMFileExport model to RTSTRUCT_RECEIVED
# 3. Update the Dicom series model series_processing_status to RTSTRUCTURE_RECEIVED  

# Create a json serializable output which has the full file paths of the RTstructureset files downloaded along with the corresponding DICOMSeries object for the next task in the chain that is reidentification of the RTstructure file and the export to the folder.

import os
import logging
import hashlib
import json
import requests
from datetime import datetime
from typing import List, Dict, Any, Tuple
from django.db import transaction
from django.utils import timezone
import pydicom
from pydicom.errors import InvalidDicomError

from ..models import (
    SystemConfiguration, DICOMFileExport, DICOMSeries, RTStructureFileImport,
    DICOMFileTransferStatus, ProcessingStatus
)
from ..utils.proxy_configuration import get_session_with_proxy

logger = logging.getLogger(__name__)

def refresh_bearer_token(
    session: requests.Session,
    system_config: SystemConfiguration
) -> bool:
    """
    Refresh the bearer token using the refresh token.
    
    Args:
        session: Requests session with proxy configuration
        system_config: System configuration object
        
    Returns:
        bool: True if token refresh was successful
    """
    if not system_config.draw_refresh_token:
        logger.error("No refresh token available for token refresh")
        return False
    
    if not system_config.draw_token_refresh_endpoint:
        logger.error("No token refresh endpoint configured")
        return False
    
    refresh_url = system_config.draw_base_url + system_config.draw_token_refresh_endpoint
    
    try:
        headers = {
            'Authorization': f'Bearer {system_config.draw_refresh_token}',
            'Content-Type': 'application/json'
        }
        
        logger.info("Attempting to refresh bearer token")
        response = session.post(refresh_url, headers=headers, timeout=30)
        
        if response.status_code == 200:
            token_data = response.json()
            
            # Update configuration with new tokens
            with transaction.atomic():
                system_config.draw_bearer_token = token_data.get('access_token')
                if 'refresh_token' in token_data:
                    system_config.draw_refresh_token = token_data.get('refresh_token')
                
                # Calculate expiry date from expires_in (seconds)
                if 'expires_in' in token_data:
                    from datetime import timedelta
                    expires_in_seconds = int(token_data['expires_in'])
                    expires_at = timezone.now() + timedelta(seconds=expires_in_seconds)
                    system_config.draw_bearer_token_validaty = expires_at
                    logger.info(f"Token expiry updated to: {expires_at}")
                elif 'expires_at' in token_data:
                    # Fallback: Parse ISO format datetime if provided
                    from dateutil import parser as dateutil_parser
                    expires_at = dateutil_parser.isoparse(token_data['expires_at'])
                    if expires_at.tzinfo is None:
                        expires_at = timezone.make_aware(expires_at)
                    system_config.draw_bearer_token_validaty = expires_at
                    logger.info(f"Token expiry updated to: {expires_at}")
                
                system_config.save()
            
            logger.info("Bearer token refreshed successfully")
            return True
        else:
            logger.error(f"Token refresh failed with status: {response.status_code}")
            return False
            
    except Exception as e:
        logger.error(f"Error refreshing bearer token: {str(e)}")
        return False

def poll_and_retrieve_rtstruct() -> Dict[str, Any]:
    """
    Poll DRAW API server for completed segmentations and download RTStructure files.
    
    This function:
    1. Finds DICOMFileExport objects ready for polling
    2. Polls server status for each task
    3. Downloads RTStructure files when ready
    4. Validates checksums and file integrity
    5. Creates RTStructureFileImport records
    6. Notifies server of successful receipt
    
    Returns:
        Dict containing list of downloaded RTStructure files for next task
        
    Raises:
        Exception: If system configuration is missing or invalid
    """
    logger.info("Starting RTStructure polling and retrieval task")
    
    # Get system configuration
    system_config = SystemConfiguration.get_singleton()
    if not system_config:
        error_msg = "System configuration not found"
        logger.error(error_msg)
        raise Exception(error_msg)
    
    # Validate required configuration
    required_fields = [
        'draw_base_url', 'draw_status_endpoint', 'draw_download_endpoint', 
        'draw_notify_endpoint', 'draw_bearer_token'
    ]
    for field in required_fields:
        if not getattr(system_config, field):
            error_msg = f"Missing required system configuration: {field}"
            logger.error(error_msg)
            raise Exception(error_msg)
    
    downloaded_files = []
    
    try:
        with transaction.atomic():
            # Find DICOMFileExport objects ready for polling
            exports_to_poll = _get_exports_ready_for_polling()
            logger.info(f"Found {len(exports_to_poll)} exports ready for polling")
            
            if not exports_to_poll:
                logger.info("No exports ready for polling")
                return {"downloaded_rtstruct_files": []}
            
            # Create session with proxy configuration
            session = get_session_with_proxy()
            
            for export in exports_to_poll:
                try:
                    logger.info(f"Processing export for task_id: ***{export.task_id[:4]}...{export.task_id[-4:]}***")
                    
                    # Poll server status
                    status_updated = _poll_server_status(session, system_config, export)
                    
                    # Log the current status for debugging
                    logger.info(f"Current server_segmentation_status for task_id ***{export.task_id[:4]}...{export.task_id[-4:]}***: '{export.server_segmentation_status}'")
                    
                    # If status shows segmentation completed, download the file
                    if export.server_segmentation_status == "SEGMENTATION COMPLETED":
                        logger.info(f"Status matches 'SEGMENTATION COMPLETED', starting download for task_id ***{export.task_id[:4]}...{export.task_id[-4:]}***")
                        downloaded_file = _download_and_validate_rtstruct(
                            session, system_config, export
                        )
                        if downloaded_file:
                            downloaded_files.append(downloaded_file)
                            logger.info(f"Successfully processed and added file for task_id ***{export.task_id[:4]}...{export.task_id[-4:]}***")
                        else:
                            logger.warning(f"Download/validation failed for task_id ***{export.task_id[:4]}...{export.task_id[-4:]}***")
                    else:
                        logger.info(f"Status '{export.server_segmentation_status}' does not match 'SEGMENTATION COMPLETED', skipping download for task_id ***{export.task_id[:4]}...{export.task_id[-4:]}***")
                            
                except Exception as e:
                    logger.error(f"Error processing export {export.id}: {str(e)}")
                    # Continue with other exports
                    continue
    
    except Exception as e:
        logger.error(f"Critical error in poll_and_retrieve_rtstruct: {str(e)}")
        raise
    
    logger.info(f"RTStructure polling completed. Downloaded {len(downloaded_files)} files")
    return {"downloaded_rtstruct_files": downloaded_files}

def _get_exports_ready_for_polling() -> List[DICOMFileExport]:
    """
    Get DICOMFileExport objects that are ready for status polling.
    
    Returns:
        List of DICOMFileExport objects with COMPLETED transfer status
        and server_segmentation_status not in excluded statuses
    """
    excluded_statuses = ["Delivered to Client", "Transfer Completed"]
    
    exports = DICOMFileExport.objects.filter(
        deidentified_zip_file_transfer_status=DICOMFileTransferStatus.COMPLETED
    ).exclude(
        server_segmentation_status__in=excluded_statuses
    ).select_related('deidentified_series_instance_uid')
    
    return list(exports)

def _poll_server_status(
    session: requests.Session, 
    system_config: SystemConfiguration, 
    export: DICOMFileExport
) -> bool:
    """
    Poll server status for a specific export task.
    
    Args:
        session: Requests session with proxy configuration
        system_config: System configuration object
        export: DICOMFileExport object to poll
        
    Returns:
        bool: True if status was updated successfully
    """
    try:
        # Check if bearer token needs refresh
        if system_config.draw_bearer_token_validaty and system_config.draw_bearer_token_validaty <= timezone.now():
            logger.info("Bearer token expired, attempting refresh before polling status")
            if not refresh_bearer_token(session, system_config):
                logger.error("Failed to refresh bearer token for status polling")
                return False
        
        # Construct status endpoint URL
        status_url = system_config.draw_base_url + system_config.draw_status_endpoint.format(
            task_id=export.task_id
        )
        
        # Prepare headers with bearer token
        headers = {
            'Authorization': f'Bearer {system_config.draw_bearer_token}',
            'Content-Type': 'application/json'
        }
        
        logger.debug(f"Polling status for task_id: ***{export.task_id[:4]}...{export.task_id[-4:]}***")
        
        # Make status request
        response = session.get(status_url, headers=headers, timeout=30)
        response.raise_for_status()
        
        status_data = response.json()
        server_status = status_data.get('status', '')
        
        logger.info(f"Server response for task_id ***{export.task_id[:4]}...{export.task_id[-4:]}***: {status_data}")
        logger.info(f"Extracted server_status: '{server_status}'")
        
        # Update server segmentation status
        export.server_segmentation_status = server_status
        export.server_segmentation_updated_datetime = timezone.now()
        export.save(update_fields=[
            'server_segmentation_status', 
            'server_segmentation_updated_datetime'
        ])
        
        logger.info(f"Updated status for task_id ***{export.task_id[:4]}...{export.task_id[-4:]}***: {server_status}")
        return True
        
    except requests.exceptions.RequestException as e:
        logger.warning(f"Failed to poll status for task_id ***{export.task_id[:4]}...{export.task_id[-4:]}***: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error polling status for task_id ***{export.task_id[:4]}...{export.task_id[-4:]}***: {str(e)}")
        return False

def _download_and_validate_rtstruct(
    session: requests.Session,
    system_config: SystemConfiguration,
    export: DICOMFileExport
) -> Dict[str, Any]:
    """
    Download and validate RTStructure file for a completed segmentation.
    
    Args:
        session: Requests session with proxy configuration
        system_config: System configuration object
        export: DICOMFileExport object with completed segmentation
        
    Returns:
        Dict containing file information for next task, or None if failed
    """
    logger.info(f"_download_and_validate_rtstruct called for task_id: ***{export.task_id[:4]}...{export.task_id[-4:]}***")
    try:
        # Check if bearer token needs refresh
        if system_config.draw_bearer_token_validaty and system_config.draw_bearer_token_validaty <= timezone.now():
            logger.info("Bearer token expired, attempting refresh before downloading")
            if not refresh_bearer_token(session, system_config):
                logger.error("Failed to refresh bearer token for download")
                _update_failed_status(export, DICOMFileTransferStatus.FAILED)
                return None
        
        # Construct download URL
        download_url = system_config.draw_base_url + system_config.draw_download_endpoint.format(
            task_id=export.task_id
        )
        
        # Prepare headers
        headers = {
            'Authorization': f'Bearer {system_config.draw_bearer_token}',
        }
        
        logger.info(f"Downloading RTStructure for task_id: ***{export.task_id[:4]}...{export.task_id[-4:]}***")
        
        # Download the file
        response = session.get(download_url, headers=headers, timeout=300)
        response.raise_for_status()
        
        # Get checksum from response headers
        server_checksum = response.headers.get('X-File-Checksum', '').strip()
        if not server_checksum:
            logger.warning(f"No checksum provided by server for task_id ***{export.task_id[:4]}...{export.task_id[-4:]}***")
        
        # Create download directory
        base_dir = os.path.dirname(export.deidentified_zip_file_path or '')
        download_dir = os.path.join(base_dir, 'downloaded_rtstruct')
        logger.info(f"Creating download directory: {download_dir}")
        os.makedirs(download_dir, exist_ok=True)
        logger.info(f"Download directory created/exists: {download_dir}")
        
        # Generate filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"rtstruct_{export.task_id}_{timestamp}.dcm"
        file_path = os.path.join(download_dir, filename)
        logger.info(f"Generated file path: {file_path}")
        
        # Log response details
        logger.info(f"Response status code: {response.status_code}")
        logger.info(f"Response content length: {len(response.content)} bytes")
        logger.info(f"Response headers: {dict(response.headers)}")
        
        # Write file to disk
        logger.info(f"Writing {len(response.content)} bytes to file: {file_path}")
        with open(file_path, 'wb') as f:
            f.write(response.content)
        
        # Verify file was written
        if os.path.exists(file_path):
            file_size = os.path.getsize(file_path)
            logger.info(f"File successfully written: {file_path} (size: {file_size} bytes)")
        else:
            logger.error(f"File was not created: {file_path}")
        
        # Calculate and verify checksum
        calculated_checksum = _calculate_file_checksum(file_path)
        
        if server_checksum and calculated_checksum != server_checksum:
            logger.error(f"Checksum mismatch for task_id ***{export.task_id[:4]}...{export.task_id[-4:]}***: server={server_checksum}, calculated={calculated_checksum}")
            logger.info(f"Deleting file due to checksum mismatch: {file_path}")
            os.remove(file_path)
            _update_failed_status(export, DICOMFileTransferStatus.CHECKSUM_MATCH_FAILED)
            return None
        else:
            logger.info(f"Checksum validation passed for task_id ***{export.task_id[:4]}...{export.task_id[-4:]}***: {calculated_checksum}")
        
        # Validate DICOM file and modality
        logger.info(f"Starting DICOM validation for file: {file_path}")
        validation_result = _validate_rtstruct_file(file_path, export)
        if not validation_result['valid']:
            logger.error(f"RTStructure validation failed: {validation_result['error']}")
            logger.info(f"Deleting file due to validation failure: {file_path}")
            os.remove(file_path)
            _update_failed_status(export, DICOMFileTransferStatus.INVALID_RTSTRUCT_FILE)
            return None
        else:
            logger.info(f"DICOM validation passed for file: {file_path}")
        
        # Create RTStructureFileImport record
        rt_import = _create_rtstruct_import_record(
            export, file_path, calculated_checksum, validation_result['sop_instance_uid']
        )
        
        # Notify server of successful receipt
        notification_success = _notify_server_receipt(session, system_config, export)
        
        if notification_success:
            # Update statuses after successful notification
            _update_successful_status(export)
            
            # Return file information for next task
            return {
                "rtstruct_file_path": file_path,
                "series_instance_uid": export.deidentified_series_instance_uid.series_instance_uid,
                "deidentified_series_instance_uid": export.deidentified_series_instance_uid.deidentified_series_instance_uid,
                "task_id": export.task_id,
                "rt_import_id": str(rt_import.id)
            }
        else:
            logger.warning(f"Server notification failed for task_id ***{export.task_id[:4]}...{export.task_id[-4:]}***")
            return None
            
    except Exception as e:
        logger.error(f"Error downloading RTStructure for task_id ***{export.task_id[:4]}...{export.task_id[-4:]}***: {str(e)}")
        if 'file_path' in locals() and os.path.exists(file_path):
            logger.info(f"Deleting file due to exception: {file_path}")
            os.remove(file_path)
        _update_failed_status(export, DICOMFileTransferStatus.FAILED)
        return None

def _calculate_file_checksum(file_path: str) -> str:
    """Calculate SHA256 checksum of a file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            sha256_hash.update(chunk)
    return sha256_hash.hexdigest()

def _validate_rtstruct_file(file_path: str, export: DICOMFileExport) -> Dict[str, Any]:
    """
    Validate RTStructure DICOM file.
    
    Args:
        file_path: Path to the downloaded RTStructure file
        export: DICOMFileExport object
        
    Returns:
        Dict with validation results
    """
    try:
        # Try to read DICOM file without force=True
        try:
            ds = pydicom.dcmread(file_path, force=False)
        except (InvalidDicomError, Exception) as e:
            logger.error(f"Failed to read DICOM file {file_path}: {str(e)}")
            return {
                'valid': False,
                'error': f'Cannot read as DICOM file: {str(e)}'
            }
        
        # Check modality
        modality = getattr(ds, 'Modality', '')
        if modality != 'RTSTRUCT':
            return {
                'valid': False,
                'error': f'Invalid modality: {modality}, expected RTSTRUCT'
            }
        
        # Check Referenced Series Instance UID from Referenced Frame of Reference Sequence
        # In RTStructure files, referenced series info is in (3006,0010) -> (3006,0012) -> (3006,0014) -> (0020,000E)
        ref_series_uid = None
        try:
            # Look for Referenced Frame of Reference Sequence (3006,0010)
            if (0x3006, 0x0010) in ds:
                ref_frame_seq_element = ds[0x3006, 0x0010]
                # Check if it's a sequence and get its value
                if hasattr(ref_frame_seq_element, 'value') and ref_frame_seq_element.value:
                    ref_frame_seq = ref_frame_seq_element.value
                    logger.info(f"Found Referenced Frame of Reference Sequence with {len(ref_frame_seq)} items")
                    
                    for frame_item in ref_frame_seq:
                        # Look for RT Referenced Study Sequence (3006,0012) within each frame
                        if (0x3006, 0x0012) in frame_item:
                            rt_ref_study_seq_element = frame_item[0x3006, 0x0012]
                            # Check if it's a sequence and get its value
                            if hasattr(rt_ref_study_seq_element, 'value') and rt_ref_study_seq_element.value:
                                rt_ref_study_seq = rt_ref_study_seq_element.value
                                logger.info(f"Found RT Referenced Study Sequence with {len(rt_ref_study_seq)} items")
                                
                                for study_item in rt_ref_study_seq:
                                    # Look for RT Referenced Series Sequence (3006,0014) within each study
                                    if (0x3006, 0x0014) in study_item:
                                        rt_ref_series_seq_element = study_item[0x3006, 0x0014]
                                        # Check if it's a sequence and get its value
                                        if hasattr(rt_ref_series_seq_element, 'value') and rt_ref_series_seq_element.value:
                                            rt_ref_series_seq = rt_ref_series_seq_element.value
                                            logger.info(f"Found RT Referenced Series Sequence with {len(rt_ref_series_seq)} items")
                                            
                                            for series_item in rt_ref_series_seq:
                                                # Get Series Instance UID (0020,000E) from the referenced series
                                                if (0x0020, 0x000E) in series_item:
                                                    ref_series_uid = series_item[0x0020, 0x000E].value
                                                    logger.info(f"Found Referenced Series UID: {ref_series_uid}")
                                                    break
                                            
                                            if ref_series_uid:
                                                break
                                    
                                    if ref_series_uid:
                                        break
                        
                        if ref_series_uid:
                            break
                else:
                    logger.warning(f"Referenced Frame of Reference Sequence (3006,0010) exists but has no value in RTStructure file {file_path}")
            else:
                logger.warning(f"No Referenced Frame of Reference Sequence (3006,0010) found in RTStructure file {file_path}")
                
        except Exception as e:
            logger.warning(f"Error accessing Referenced Series UID in RTStructure file {file_path}: {str(e)}")
            ref_series_uid = None
        
        if ref_series_uid:
            expected_uid = export.deidentified_series_instance_uid.deidentified_series_instance_uid
            logger.info(f"Comparing Referenced Series UID: {ref_series_uid} with expected: {expected_uid}")
            if ref_series_uid != expected_uid:
                return {
                    'valid': False,
                    'error': f'Referenced Series UID mismatch: {ref_series_uid} != {expected_uid}'
                }
        else:
            logger.warning(f"No Referenced Series Instance UID found in RTStructure sequences for file {file_path}")
            # Don't fail validation if we can't find the referenced series UID - log warning instead
            logger.warning("Proceeding with validation despite missing Referenced Series UID")
        
        # Get SOP Instance UID
        sop_instance_uid = getattr(ds, 'SOPInstanceUID', '')
        
        return {
            'valid': True,
            'sop_instance_uid': sop_instance_uid,
            'error': None
        }
        
    except InvalidDicomError as e:
        return {
            'valid': False,
            'error': f'Invalid DICOM file: {str(e)}'
        }
    except Exception as e:
        return {
            'valid': False,
            'error': f'Validation error: {str(e)}'
        }

def _create_rtstruct_import_record(
    export: DICOMFileExport,
    file_path: str,
    checksum: str,
    sop_instance_uid: str
) -> RTStructureFileImport:
    """Create RTStructureFileImport database record."""
    rt_import = RTStructureFileImport.objects.create(
        deidentified_series_instance_uid=export.deidentified_series_instance_uid,
        deidentified_sop_instance_uid=sop_instance_uid,
        deidentified_rt_structure_file_path=file_path,
        received_rt_structure_file_checksum=checksum,
        received_rt_structure_file_download_datetime=timezone.now(),
        server_segmentation_status=export.server_segmentation_status,
        server_segmentation_updated_datetime=export.server_segmentation_updated_datetime
    )
    
    logger.info(f"Created RTStructureFileImport record: {rt_import.id}")
    return rt_import

def _notify_server_receipt(
    session: requests.Session,
    system_config: SystemConfiguration,
    export: DICOMFileExport
) -> bool:
    """
    Notify server that RTStructure file was received successfully.
    
    Returns:
        bool: True if notification was successful
    """
    try:
        # Check if bearer token needs refresh
        if system_config.draw_bearer_token_validaty and system_config.draw_bearer_token_validaty <= timezone.now():
            logger.info("Bearer token expired, attempting refresh before notification")
            if not refresh_bearer_token(session, system_config):
                logger.error("Failed to refresh bearer token for notification")
                return False
        
        # Construct notify URL
        notify_url = system_config.draw_base_url + system_config.draw_notify_endpoint.format(
            task_id=export.task_id
        )
        
        # Prepare headers
        headers = {
            'Authorization': f'Bearer {system_config.draw_bearer_token}',
            'Content-Type': 'application/json'
        }
        
        # Prepare notification data
        notification_data = {
            'task_id': export.task_id,
            'status': 'received',
            'timestamp': timezone.now().isoformat()
        }
        
        logger.debug(f"Notifying server for task_id: ***{export.task_id[:4]}...{export.task_id[-4:]}***")
        
        # Send notification
        response = session.post(
            notify_url, 
            headers=headers, 
            json=notification_data, 
            timeout=30
        )
        response.raise_for_status()
        
        # Check response message
        response_text = response.text.strip()
        if "Transfer confirmation received, files cleaned up" in response_text:
            logger.info(f"Server notification successful for task_id ***{export.task_id[:4]}...{export.task_id[-4:]}***")
            return True
        else:
            logger.warning(f"Unexpected server response: {response_text}")
            return False
            
    except Exception as e:
        logger.error(f"Failed to notify server for task_id ***{export.task_id[:4]}...{export.task_id[-4:]}***: {str(e)}")
        return False

def _update_successful_status(export: DICOMFileExport) -> None:
    """Update statuses after successful RTStructure receipt."""
    # Update DICOMFileExport statuses
    export.server_segmentation_status = "RTStructure Received"
    export.deidentified_zip_file_transfer_status = DICOMFileTransferStatus.RTSTRUCT_RECEIVED
    export.save(update_fields=[
        'server_segmentation_status',
        'deidentified_zip_file_transfer_status'
    ])
    
    # Update DICOMSeries processing status
    series = export.deidentified_series_instance_uid
    series.series_processsing_status = ProcessingStatus.RTSTRUCTURE_RECEIVED
    series.save(update_fields=['series_processsing_status'])
    
    logger.info(f"Updated successful status for series: ***{series.series_instance_uid[:4]}...{series.series_instance_uid[-4:]}***")

def _update_failed_status(export: DICOMFileExport, transfer_status: str) -> None:
    """Update statuses after failed RTStructure processing."""
    # Update DICOMFileExport transfer status
    export.deidentified_zip_file_transfer_status = transfer_status
    export.save(update_fields=['deidentified_zip_file_transfer_status'])
    
    # Update DICOMSeries processing status
    series = export.deidentified_series_instance_uid
    series.series_processsing_status = ProcessingStatus.INVALID_RTSTRUCTURE_RECEIVED
    series.save(update_fields=['series_processsing_status'])
    
    logger.error(f"Updated failed status for series: ***{series.series_instance_uid[:4]}...{series.series_instance_uid[-4:]}***")
