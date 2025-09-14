# Task 4: Send the deidentified series to the Draw API server (code to be written to task4_export_series_to_api.py)
# For each Zip file which has been deidentified, send it to the DRAW API Server. First we will update the status for the DICOMFileExport model to PENDING_TRANSFER_TO_DRAW_SERVER
# Prior to each transfer ensure that the API endpoint is accepting file transfer by polling the healthcheck end point. This will be available at <draw_base_url>/api/health. If the response returns a 200 then the API is ready to accept file transfer. If the response is 503 then it means that the API endpoint is not accepting connections. In this case wait for 1 minute and try again. If the response is 503 for 3 consecutive times then raise an exception. Also update the status of the DICOMSeries model to PENDING_TRANSFER_TO_DRAW_SERVER. 
# If we get a  200 response then the authentication will need to be done using the draw_bearer_token token from the SystemConfiguration model. If the bearer token is expired then the token will need to be refreshed using the draw_refresh_token from the SystemConfiguration model. 
# If authentication fails again then raise an exception and update the status of the DICOMSeries model to FAILED_TRANSFER_TO_DRAW_SERVER.
# Calculate the zip file checksum prior to sending it and update the checksum value in the database. (DICOMFileExport model). This checksum value has to be sent as the API payload along with the file. 
# The API endpoint for file transfer will be available at <draw_base_url>/api/upload/ or the URL endpoint in the System configuration. The file will need to be sent as a multipart/form-data request with the following fields:
# - file - The zip file to be sent to the DRAW API server
# - checksum - The checksum of the zip file to be sent to the DRAW API server
# After the transfer is completed the server will issue a task_id which needs to be stored in the task_id field of the DICOMFileExport model. At this time update the DICOMSeries model status to SENT_TO_DRAW_SERVER. Ensure that the date time fields in the DICOMFIleExport are also updated at this time. The status will be returned from the API server at the endpoint <draw_base_url>/api/upload/{task_id}/status/ or the URL endpoint in the System configuration. The deidentified_zip_file_transfer_status field in the DICOMFileExport model should be updated to COMPLETED. 
# If the upload fails then the status should be updated to FAILED. Also the DICOMSeries model status should be updated to FAILED_TRANSFER_TO_DRAW_SERVER.
# Delete the zip file after successful transfer
# Ensure logging of all operations while masking sensitive information.

import os
import logging
import hashlib
import time
import requests
from datetime import datetime, timezone
from django.db import transaction
from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone as django_timezone
import json
from ..models import (
    DICOMSeries, DICOMFileExport, ProcessingStatus,
    DICOMFileTransferStatus, SystemConfiguration
)
from ..utils.proxy_configuration import get_session_with_proxy

# Configure logging with masking for sensitive information
logger = logging.getLogger(__name__)

# Constants
HEALTH_CHECK_RETRIES = 3
HEALTH_CHECK_WAIT_TIME = 60  # seconds
REQUEST_TIMEOUT = 300  # 5 minutes timeout for file uploads

def mask_sensitive_data(data, field_name=""):
    """
    Mask sensitive DICOM data for logging purposes
    """
    if not data:
        return "***EMPTY***"
    
    # Mask patient identifiable information
    sensitive_fields = [
        'patient_name', 'patient_id', 'patient_birth_date',
        'PatientName', 'PatientID', 'PatientBirthDate',
        'institution_name', 'InstitutionName', 'token', 'bearer'
    ]
    
    if any(field in field_name.lower() for field in ['name', 'id', 'birth', 'token', 'bearer']):
        return f"***{field_name.upper()}_MASKED***"
    
    # For UIDs, show only first and last 4 characters
    if 'uid' in field_name.lower() and len(str(data)) > 8:
        return f"{str(data)[:4]}...{str(data)[-4:]}"
    
    # For file paths, show only filename
    if 'path' in field_name.lower():
        return f"***PATH***/{os.path.basename(str(data))}"
    
    return str(data)

def calculate_file_checksum(file_path):
    """
    Calculate SHA256 checksum of a file
    Returns: Checksum string or None if error
    """
    try:
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            # Read file in chunks to handle large files
            for chunk in iter(lambda: f.read(4096), b""):
                sha256_hash.update(chunk)
        
        checksum = sha256_hash.hexdigest()
        logger.debug(f"Calculated checksum for {mask_sensitive_data(file_path, 'file_path')}: {checksum[:8]}...")
        return checksum
        
    except Exception as e:
        logger.error(f"Error calculating checksum for {mask_sensitive_data(file_path, 'file_path')}: {str(e)}")
        return None

def check_api_health(base_url, session):
    """
    Check if the DRAW API server is ready to accept file transfers
    Returns: True if healthy, False otherwise
    """
    health_url = f"{base_url.rstrip('/')}/api/health"
    
    try:
        response = session.get(health_url, timeout=30)
        
        if response.status_code == 200:
            logger.info("API health check passed - server ready for file transfer")
            return True
        elif response.status_code == 503:
            logger.warning("API health check failed - server not ready (503)")
            return False
        else:
            logger.warning(f"API health check returned unexpected status: {response.status_code}")
            return False
            
    except requests.exceptions.RequestException as e:
        logger.error(f"API health check failed with exception: {str(e)}")
        return False

def refresh_bearer_token(config, session):
    """
    Refresh the bearer token using the refresh token
    Returns: True if successful, False otherwise
    """
    if not config.draw_refresh_token:
        logger.error("No refresh token available for token refresh")
        return False
    
    refresh_url = f"{config.draw_base_url.rstrip('/')}/api/auth/refresh"
    
    try:
        headers = {
            'Authorization': f'Bearer {config.draw_refresh_token}',
            'Content-Type': 'application/json'
        }
        
        response = session.post(refresh_url, headers=headers, timeout=30)
        
        if response.status_code == 200:
            token_data = response.json()
            
            # Update configuration with new tokens
            with transaction.atomic():
                config.draw_bearer_token = token_data.get('access_token')
                if 'refresh_token' in token_data:
                    config.draw_refresh_token = token_data.get('refresh_token')
                if 'expires_at' in token_data:
                    config.draw_bearer_token_validaty = datetime.fromisoformat(token_data['expires_at'])
                config.save()
            
            logger.info("Bearer token refreshed successfully")
            return True
        else:
            logger.error(f"Token refresh failed with status: {response.status_code}")
            return False
            
    except Exception as e:
        logger.error(f"Error refreshing bearer token: {str(e)}")
        return False

def upload_file_to_api(file_path, checksum, config, session):
    """
    Upload ZIP file to DRAW API server
    Returns: Dictionary with upload result
    """
    upload_url = f"{config.draw_base_url.rstrip('/')}{config.draw_upload_endpoint}"
    
    try:
        # Prepare headers with authentication
        headers = {
            'Authorization': f'Bearer {config.draw_bearer_token}'
        }
        
        # Prepare multipart form data
        with open(file_path, 'rb') as file_obj:
            files = {
                'file': (os.path.basename(file_path), file_obj, 'application/zip')
            }
            data = {
                'checksum': checksum
            }
            
            # Add client_id if configured
            if config.client_id:
                data['client_id'] = config.client_id
            
            logger.info(f"Starting file upload: {mask_sensitive_data(file_path, 'file_path')}")
            
            response = session.post(
                upload_url,
                headers=headers,
                files=files,
                data=data,
                timeout=REQUEST_TIMEOUT
            )
        
        if response.status_code in [200, 201, 202]:
            result_data = response.json()
            # Try different field names for task ID
            task_id = result_data.get('task_id') or result_data.get('transaction_token')
            
            if task_id:
                logger.info(f"File upload successful. Task ID: {task_id}")
                return {
                    'success': True,
                    'task_id': task_id,
                    'response_data': result_data
                }
            else:
                logger.error("Upload successful but no task_id or transaction_token returned")
                return {
                    'success': False,
                    'error': 'No task_id or transaction_token in response'
                }
        else:
            logger.error(f"File upload failed with status: {response.status_code}")
            try:
                error_data = response.json()
                logger.error(f"Upload error details: {error_data}")
            except:
                logger.error(f"Upload error response: {response.text}")
            
            return {
                'success': False,
                'error': f'HTTP {response.status_code}',
                'response': response.text
            }
            
    except requests.exceptions.Timeout:
        logger.error(f"File upload timed out after {REQUEST_TIMEOUT} seconds")
        return {
            'success': False,
            'error': 'Upload timeout'
        }
    except Exception as e:
        logger.error(f"Error uploading file: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }

def update_export_record_status(export_record, status, task_id=None, error_message=None):
    """
    Update DICOMFileExport record with new status and details
    """
    try:
        with transaction.atomic():
            export_record.deidentified_zip_file_transfer_status = status
            
            if task_id:
                export_record.task_id = task_id
            
            if status == DICOMFileTransferStatus.COMPLETED:
                export_record.deidentified_zip_file_transfer_datetime = django_timezone.now()
            
            export_record.save()
            
            logger.debug(f"Updated export record status to: {status}")
            return True
            
    except Exception as e:
        logger.error(f"Error updating export record status: {str(e)}")
        return False

def update_series_status(series, status):
    """
    Update DICOMSeries processing status
    """
    try:
        with transaction.atomic():
            series.series_processsing_status = status
            series.save()
            
            logger.debug(f"Updated series status to: {status} for series: {mask_sensitive_data(series.series_instance_uid, 'series_uid')}")
            return True
            
    except Exception as e:
        logger.error(f"Error updating series status: {str(e)}")
        return False

def cleanup_zip_file(file_path):
    """
    Delete ZIP file after successful transfer
    """
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"Cleaned up ZIP file: {mask_sensitive_data(file_path, 'file_path')}")
            return True
        else:
            logger.warning(f"ZIP file not found for cleanup: {mask_sensitive_data(file_path, 'file_path')}")
            return False
            
    except Exception as e:
        logger.error(f"Error cleaning up ZIP file {mask_sensitive_data(file_path, 'file_path')}: {str(e)}")
        return False

def export_series_to_api(task3_output):
    """
    Main function to export deidentified series to DRAW API server
    Input: Output from task3 (deidentified series data)
    Returns: Dictionary containing export results for next task
    """
    logger.info("Starting DICOM series export to API server task")
    
    try:
        # Validate input
        if not task3_output or task3_output.get('status') != 'success':
            logger.error("Invalid input from task3 or task3 failed")
            return {"status": "error", "message": "Invalid input from previous task"}
        
        deidentified_series = task3_output.get('deidentified_series', [])
        if not deidentified_series:
            logger.info("No deidentified series to export")
            return {"status": "success", "processed_series": 0, "exported_series": []}
        
        logger.info(f"Processing {len(deidentified_series)} deidentified series for API export")
        
        # Get system configuration
        config = SystemConfiguration.get_singleton()
        if not config:
            logger.error("System configuration not found")
            return {"status": "error", "message": "System configuration not available"}
        
        if not config.draw_base_url or not config.draw_bearer_token:
            logger.error("DRAW API configuration incomplete")
            return {"status": "error", "message": "DRAW API configuration incomplete"}
        
        # Create session with proxy configuration
        session = get_session_with_proxy()
        
        exported_results = []
        processed_count = 0
        
        for series_info in deidentified_series:
            try:
                original_series_uid = series_info['original_series_uid']
                deidentified_series_uid = series_info['deidentified_series_uid']
                zip_file_path = series_info['zip_file_path']
                
                logger.info(f"Processing export for series: {mask_sensitive_data(original_series_uid, 'series_uid')}")
                
                # Get series and export record from database
                try:
                    series = DICOMSeries.objects.get(series_instance_uid=original_series_uid)
                    export_record = DICOMFileExport.objects.get(deidentified_series_instance_uid=series)
                except ObjectDoesNotExist as e:
                    logger.error(f"Database record not found for series {mask_sensitive_data(original_series_uid, 'series_uid')}: {str(e)}")
                    continue
                
                # Check if ZIP file exists
                if not os.path.exists(zip_file_path):
                    logger.error(f"ZIP file not found: {mask_sensitive_data(zip_file_path, 'file_path')}")
                    update_series_status(series, ProcessingStatus.FAILED_TRANSFER_TO_DRAW_SERVER)
                    update_export_record_status(export_record, DICOMFileTransferStatus.FAILED)
                    continue
                
                # Update status to pending transfer
                update_series_status(series, ProcessingStatus.PENDING_TRANSFER_TO_DRAW_SERVER)
                update_export_record_status(export_record, DICOMFileTransferStatus.IN_PROGRESS)
                
                # Check API health with retries
                health_check_passed = False
                for attempt in range(HEALTH_CHECK_RETRIES):
                    if check_api_health(config.draw_base_url, session):
                        health_check_passed = True
                        break
                    else:
                        if attempt < HEALTH_CHECK_RETRIES - 1:
                            logger.info(f"Health check failed, waiting {HEALTH_CHECK_WAIT_TIME} seconds before retry {attempt + 2}/{HEALTH_CHECK_RETRIES}")
                            time.sleep(HEALTH_CHECK_WAIT_TIME)
                        else:
                            logger.error(f"Health check failed after {HEALTH_CHECK_RETRIES} attempts")
                
                if not health_check_passed:
                    logger.error("API server not ready for file transfer")
                    update_series_status(series, ProcessingStatus.FAILED_TRANSFER_TO_DRAW_SERVER)
                    update_export_record_status(export_record, DICOMFileTransferStatus.FAILED)
                    continue
                
                # Calculate file checksum
                checksum = calculate_file_checksum(zip_file_path)
                if not checksum:
                    logger.error(f"Failed to calculate checksum for {mask_sensitive_data(zip_file_path, 'file_path')}")
                    update_series_status(series, ProcessingStatus.FAILED_TRANSFER_TO_DRAW_SERVER)
                    update_export_record_status(export_record, DICOMFileTransferStatus.FAILED)
                    continue
                
                # Update checksum in database
                with transaction.atomic():
                    export_record.deidentified_zip_file_checksum = checksum
                    export_record.save()
                
                # Check if bearer token needs refresh
                if config.draw_bearer_token_validaty and config.draw_bearer_token_validaty <= django_timezone.now():
                    logger.info("Bearer token expired, attempting refresh")
                    if not refresh_bearer_token(config, session):
                        logger.error("Failed to refresh bearer token")
                        update_series_status(series, ProcessingStatus.FAILED_TRANSFER_TO_DRAW_SERVER)
                        update_export_record_status(export_record, DICOMFileTransferStatus.FAILED)
                        continue
                
                # Upload file to API
                upload_result = upload_file_to_api(zip_file_path, checksum, config, session)
                
                if upload_result['success']:
                    task_id = upload_result['task_id']
                    
                    # Update database with successful transfer
                    update_series_status(series, ProcessingStatus.SENT_TO_DRAW_SERVER)
                    update_export_record_status(export_record, DICOMFileTransferStatus.COMPLETED, task_id=task_id)
                    
                    # Clean up ZIP file after successful transfer
                    cleanup_zip_file(zip_file_path)
                    
                    # Add to results for next task
                    exported_results.append({
                        'original_series_uid': original_series_uid,
                        'deidentified_series_uid': deidentified_series_uid,
                        'task_id': task_id,
                        'upload_datetime': django_timezone.now().isoformat(),
                        'checksum': checksum
                    })
                    
                    logger.info(f"Successfully exported series: {mask_sensitive_data(original_series_uid, 'series_uid')} -> Task ID: {task_id}")
                    processed_count += 1
                    
                else:
                    logger.error(f"Failed to upload series {mask_sensitive_data(original_series_uid, 'series_uid')}: {upload_result.get('error', 'Unknown error')}")
                    update_series_status(series, ProcessingStatus.FAILED_TRANSFER_TO_DRAW_SERVER)
                    update_export_record_status(export_record, DICOMFileTransferStatus.FAILED)
                    
            except Exception as e:
                logger.error(f"Error processing series {mask_sensitive_data(series_info.get('original_series_uid', 'unknown'), 'series_uid')}: {str(e)}")
                continue
        
        logger.info(f"API export completed. Processed: {processed_count}, Successful: {len(exported_results)}")
        
        return {
            "status": "success",
            "processed_series": processed_count,
            "successful_exports": len(exported_results),
            "exported_series": exported_results
        }
        
    except Exception as e:
        logger.error(f"Critical error in API export task: {str(e)}")
        return {"status": "error", "message": str(e)}