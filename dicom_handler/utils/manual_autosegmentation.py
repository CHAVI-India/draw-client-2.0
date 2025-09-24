# This file will hold the code to trigger a manual autosegmentation.
# The workflow will be as follows:
# 1. The user will select one or more series for autosegmentation from the list of series on the series_processing_status page.
# 2. They will click a button that allows them to associate an existing autosegmentation template for the given series. This will be done on a modal box where for each series the user will be able to select the template. Users can associate different templates with different series but each series will be associated with a single template. The modal dialog that opens should should key information like patient name, patient id, modality, study date, study description etc and provide a drop down list of templates from the system for each series. The user will then assign the template to be used for each series. 
# 3. On clicking the next button the information needs to be sent to the task chain for performing the autosegementation. 
#    a. The file path
#    b. The uid mappings
#    c. The date mappings
#    d. The output path
# Note that the key difference is that when task3_runs it runs after task2 which passes information about the template file to be created for the series during task3. IN this task, the user has selected the template so that the template file needs to be read and the template file needs to be created for the series.
# 4. The system will then do the following in sequence:
#    a. Pass the series information to the celery task specifically the task3_deidentify_series
#    b. The task will then deidentify the series and save it to the storage. 
#    c. The task will then create the template file for the series and save it to the storage. 
#    d. The task will then update the processing status of the series to DEIDENTIFIED
#    e. The task will then trigger the task 4 that is export series to the api.
#    f. Appropriate status updates are to be applied to the DICOMSeries, DICOMFileExport models. 

import logging
import json
from typing import List, Dict, Any, Optional
from django.db import transaction
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.utils import timezone
from celery import chain

from ..models import (
    DICOMSeries, DICOMStudy, Patient, AutosegmentationTemplate,
    ProcessingStatus, DICOMFileExport, DICOMFileTransferStatus
)
from ..export_services.task3_deidentify_series import deidentify_series
from ..export_services.task4_export_series_to_api import export_series_to_api

# Configure logging with masking for sensitive information
logger = logging.getLogger(__name__)

def mask_sensitive_data(data, field_name=""):
    """
    Mask sensitive DICOM data for logging purposes following development rules
    """
    if not data:
        return "***EMPTY***"
    
    # Mask patient identifiable information
    if any(field in field_name.lower() for field in ['name', 'id', 'birth', 'patient']):
        return f"***{field_name.upper()}_MASKED***"
    
    # For UIDs, show only first and last 4 characters
    if 'uid' in field_name.lower() and len(str(data)) > 8:
        return f"{str(data)[:4]}...{str(data)[-4:]}"
    
    return str(data)

def get_series_for_manual_selection(series_uids: List[str]) -> Dict[str, Any]:
    """
    Retrieve series information for manual template selection modal
    
    Args:
        series_uids: List of series instance UIDs to retrieve information for
        
    Returns:
        Dictionary containing series information and available templates
    """
    logger.info(f"Retrieving series information for manual template selection: {len(series_uids)} series")
    
    try:
        series_data = []
        
        for series_uid in series_uids:
            try:
                series = DICOMSeries.objects.select_related('study__patient').get(
                    series_instance_uid=series_uid
                )
                
                # Get first DICOM instance to extract metadata
                first_instance = series.dicominstance_set.first()
                
                series_info = {
                    'series_instance_uid': series_uid,
                    'series_root_path': series.series_root_path,
                    'patient_name': series.study.patient.patient_name or 'Unknown',
                    'patient_id': series.study.patient.patient_id or 'Unknown',
                    'study_date': series.study.study_date.strftime('%Y-%m-%d') if series.study.study_date else 'Unknown',
                    'study_description': series.study.study_description or 'No description',
                    'modality': series.study.study_modality or 'Unknown',
                    'instance_count': series.instance_count or 0,
                    'processing_status': series.series_processsing_status,
                    'first_instance_path': first_instance.instance_path if first_instance else None
                }
                
                series_data.append(series_info)
                logger.debug(f"Retrieved series info: {mask_sensitive_data(series_uid, 'series_uid')}")
                
            except DICOMSeries.DoesNotExist:
                logger.warning(f"Series not found: {mask_sensitive_data(series_uid, 'series_uid')}")
                continue
            except Exception as e:
                logger.error(f"Error retrieving series {mask_sensitive_data(series_uid, 'series_uid')}: {str(e)}")
                continue
        
        # Get all available autosegmentation templates
        templates = AutosegmentationTemplate.objects.all().values(
            'id', 'template_name', 'template_description'
        )
        
        result = {
            'status': 'success',
            'series_data': series_data,
            'available_templates': list(templates),
            'total_series': len(series_data)
        }
        
        logger.info(f"Successfully retrieved {len(series_data)} series for manual selection")
        return result
        
    except Exception as e:
        logger.error(f"Critical error retrieving series for manual selection: {str(e)}")
        return {
            'status': 'error',
            'message': str(e),
            'series_data': [],
            'available_templates': []
        }

def validate_template_associations(template_associations: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Validate template associations before processing
    
    Args:
        template_associations: List of dictionaries with series_uid and template_id mappings
        
    Returns:
        Dictionary with validation results
    """
    logger.info(f"Validating {len(template_associations)} template associations")
    logger.info(f"Template associations data: {template_associations}")
    
    validation_errors = []
    validated_associations = []
    
    try:
        for association in template_associations:
            series_uid = association.get('series_uid')
            template_id = association.get('template_id')
            
            logger.info(f"Validating association: series_uid={mask_sensitive_data(series_uid, 'series_uid')}, template_id={template_id}")
            
            if not series_uid:
                validation_errors.append("Missing series_uid in association")
                logger.warning("Missing series_uid in association")
                continue
                
            if not template_id:
                validation_errors.append(f"Missing template_id for series {mask_sensitive_data(series_uid, 'series_uid')}")
                logger.warning(f"Missing template_id for series {mask_sensitive_data(series_uid, 'series_uid')}")
                continue
            
            # Validate series exists
            try:
                series = DICOMSeries.objects.get(series_instance_uid=series_uid)
                logger.info(f"Series found: {mask_sensitive_data(series_uid, 'series_uid')}, status: {series.series_processsing_status}")
                    
            except DICOMSeries.DoesNotExist:
                error_msg = f"Series not found: {mask_sensitive_data(series_uid, 'series_uid')}"
                validation_errors.append(error_msg)
                logger.warning(error_msg)
                continue
            
            # Validate template exists
            try:
                template = AutosegmentationTemplate.objects.get(id=template_id)
                logger.info(f"Template found: {template_id} - {template.template_name}")
            except AutosegmentationTemplate.DoesNotExist:
                error_msg = f"Template not found: {template_id}"
                validation_errors.append(error_msg)
                logger.warning(error_msg)
                continue
            
            # Add to validated associations
            validated_associations.append({
                'series_uid': series_uid,
                'template_id': template_id,
                'template_name': template.template_name,
                'series_root_path': series.series_root_path
            })
        
        if validation_errors:
            logger.warning(f"Validation failed with {len(validation_errors)} errors: {validation_errors}")
            return {
                'status': 'error',
                'errors': validation_errors,
                'validated_associations': []
            }
        
        logger.info(f"Successfully validated {len(validated_associations)} template associations")
        return {
            'status': 'success',
            'validated_associations': validated_associations,
            'errors': []
        }
        
    except Exception as e:
        logger.error(f"Critical error during validation: {str(e)}")
        return {
            'status': 'error',
            'message': str(e),
            'errors': [str(e)],
            'validated_associations': []
        }

def trigger_manual_autosegmentation_chain(template_associations: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Trigger the manual autosegmentation chain for selected series with templates
    
    This function bypasses task2 (automatic template matching) and directly calls
    task3 (deidentify_series) and task4 (export_series_to_api) with manually selected templates.
    
    Args:
        template_associations: List of dictionaries containing:
            - series_uid: Series Instance UID
            - template_id: Selected template ID
            
    Returns:
        Dictionary containing processing results
    """
    logger.info(f"Starting manual autosegmentation chain for {len(template_associations)} series")
    
    try:
        # Validate template associations
        validation_result = validate_template_associations(template_associations)
        if validation_result['status'] != 'success':
            return validation_result
        
        validated_associations = validation_result['validated_associations']
        
        # Update series status to indicate manual processing started
        with transaction.atomic():
            for association in validated_associations:
                try:
                    series = DICOMSeries.objects.get(series_instance_uid=association['series_uid'])
                    
                    # Clear any existing matched templates and add the manually selected one
                    series.matched_templates.clear()
                    template = AutosegmentationTemplate.objects.get(id=association['template_id'])
                    series.matched_templates.add(template)
                    
                    # Update processing status
                    series.series_processsing_status = ProcessingStatus.RULE_MATCHED
                    series.save()
                    
                    logger.info(f"Updated series {mask_sensitive_data(association['series_uid'], 'series_uid')} "
                              f"with manual template: {template.template_name}")
                    
                except Exception as e:
                    logger.error(f"Error updating series {mask_sensitive_data(association['series_uid'], 'series_uid')}: {str(e)}")
                    raise
        
        # Prepare data structure similar to task2 output for task3 input
        task2_output_format = {
            'status': 'success',
            'processed_series': len(validated_associations),
            'total_matches': len(validated_associations),
            'matched_series': []
        }
        
        # Convert validated associations to task2 output format
        for association in validated_associations:
            matched_series_info = {
                'series_instance_uid': association['series_uid'],
                'series_root_path': association['series_root_path'],
                'matched_ruleset_id': None,  # No ruleset for manual selection
                'associated_template_id': association['template_id'],
                'associated_template_name': association['template_name']
            }
            task2_output_format['matched_series'].append(matched_series_info)
        
        logger.info("Triggering task3 (deidentify_series) with manual template selections")
        
        # Call task3 directly with the prepared data
        task3_result = deidentify_series(task2_output_format)
        
        if task3_result.get('status') != 'success':
            logger.error(f"Task3 (deidentify_series) failed: {task3_result.get('message', 'Unknown error')}")
            return {
                'status': 'error',
                'message': f"Deidentification failed: {task3_result.get('message', 'Unknown error')}",
                'task3_result': task3_result
            }
        
        logger.info(f"Task3 completed successfully. Processed: {task3_result.get('processed_series', 0)}, "
                   f"Successful: {task3_result.get('successful_deidentifications', 0)}")
        
        # Call task4 (export_series_to_api) with task3 output
        logger.info("Triggering task4 (export_series_to_api)")
        task4_result = export_series_to_api(task3_result)
        
        if task4_result.get('status') != 'success':
            logger.warning(f"Task4 (export_series_to_api) had issues: {task4_result.get('message', 'Unknown error')}")
        else:
            logger.info(f"Task4 completed successfully. Processed: {task4_result.get('processed_series', 0)}, "
                       f"Successful exports: {task4_result.get('successful_exports', 0)}")
        
        # Compile final results
        result = {
            'status': 'success',
            'message': 'Manual autosegmentation chain completed',
            'processed_series': len(validated_associations),
            'deidentification_results': task3_result,
            'export_results': task4_result,
            'execution_time': timezone.now().isoformat()
        }
        
        logger.info(f"Manual autosegmentation chain completed successfully for {len(validated_associations)} series")
        return result
        
    except Exception as e:
        logger.error(f"Critical error in manual autosegmentation chain: {str(e)}")
        
        # Update series status to failed for any that were being processed
        try:
            for association in template_associations:
                series_uid = association.get('series_uid')
                if series_uid:
                    try:
                        series = DICOMSeries.objects.get(series_instance_uid=series_uid)
                        series.series_processsing_status = ProcessingStatus.DEIDENTIFICATION_FAILED
                        series.save()
                    except DICOMSeries.DoesNotExist:
                        pass
        except Exception as cleanup_error:
            logger.error(f"Error during cleanup: {str(cleanup_error)}")
        
        return {
            'status': 'error',
            'message': str(e),
            'processed_series': 0
        }

def trigger_manual_autosegmentation_async(template_associations: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Trigger manual autosegmentation chain asynchronously using Celery
    
    This function creates a Celery chain similar to the automatic pipeline but
    bypasses task2 and directly processes manually selected templates.
    
    Args:
        template_associations: List of template associations
        
    Returns:
        Dictionary with chain execution information
    """
    logger.info(f"Starting async manual autosegmentation chain for {len(template_associations)} series")
    
    try:
        # Import celery tasks
        from ..tasks import task3_deidentify_series_celery, task4_export_series_to_api_celery
        
        # Validate template associations
        validation_result = validate_template_associations(template_associations)
        if validation_result['status'] != 'success':
            return validation_result
        
        validated_associations = validation_result['validated_associations']
        
        # Update series status and prepare task2-like output
        with transaction.atomic():
            for association in validated_associations:
                series = DICOMSeries.objects.get(series_instance_uid=association['series_uid'])
                series.matched_templates.clear()
                template = AutosegmentationTemplate.objects.get(id=association['template_id'])
                series.matched_templates.add(template)
                series.series_processsing_status = ProcessingStatus.RULE_MATCHED
                series.save()
        
        # Prepare task2 output format
        task2_output_format = {
            'status': 'success',
            'processed_series': len(validated_associations),
            'total_matches': len(validated_associations),
            'matched_series': [
                {
                    'series_instance_uid': assoc['series_uid'],
                    'series_root_path': assoc['series_root_path'],
                    'matched_ruleset_id': None,
                    'associated_template_id': assoc['template_id'],
                    'associated_template_name': assoc['template_name']
                }
                for assoc in validated_associations
            ]
        }
        
        # Create manual processing chain (task3 -> task4)
        manual_chain = chain(
            task3_deidentify_series_celery.s(task2_output_format),
            task4_export_series_to_api_celery.s()
        )
        
        # Execute chain asynchronously
        async_result = manual_chain.apply_async()
        
        logger.info(f"Manual autosegmentation chain initiated. Chain ID: {async_result.id}")
        
        return {
            'status': 'initiated',
            'message': 'Manual autosegmentation chain started successfully',
            'chain_id': async_result.id,
            'processed_series': len(validated_associations),
            'start_time': timezone.now().isoformat(),
            'note': 'Chain is running asynchronously. Check chain_id for completion status.'
        }
        
    except Exception as e:
        logger.error(f"Critical error in async manual autosegmentation chain: {str(e)}")
        return {
            'status': 'error',
            'message': str(e),
            'processed_series': 0
        }

def get_manual_processing_status(series_uids: List[str]) -> Dict[str, Any]:
    """
    Get current processing status for manually selected series
    
    Args:
        series_uids: List of series instance UIDs to check status for
        
    Returns:
        Dictionary containing status information for each series
    """
    logger.info(f"Checking processing status for {len(series_uids)} series")
    
    try:
        series_status = []
        
        for series_uid in series_uids:
            try:
                series = DICOMSeries.objects.select_related('study__patient').get(
                    series_instance_uid=series_uid
                )
                
                # Get export information if available
                export_info = None
                try:
                    file_export = DICOMFileExport.objects.get(deidentified_series_instance_uid=series)
                    export_info = {
                        'zip_file_path': file_export.deidentified_zip_file_path,
                        'transfer_status': file_export.deidentified_zip_file_transfer_status,
                        'transfer_datetime': file_export.deidentified_zip_file_transfer_datetime.isoformat() 
                                           if file_export.deidentified_zip_file_transfer_datetime else None,
                        'task_id': file_export.task_id
                    }
                except DICOMFileExport.DoesNotExist:
                    pass
                
                # Get matched templates
                matched_templates = list(series.matched_templates.values('id', 'template_name'))
                
                status_info = {
                    'series_instance_uid': series_uid,
                    'patient_name': mask_sensitive_data(series.study.patient.patient_name, 'patient_name'),
                    'processing_status': series.series_processsing_status,
                    'matched_templates': matched_templates,
                    'export_info': export_info,
                    'last_updated': series.updated_at.isoformat()
                }
                
                series_status.append(status_info)
                
            except DICOMSeries.DoesNotExist:
                series_status.append({
                    'series_instance_uid': series_uid,
                    'error': 'Series not found'
                })
        
        return {
            'status': 'success',
            'series_status': series_status,
            'total_series': len(series_status)
        }
        
    except Exception as e:
        logger.error(f"Error checking processing status: {str(e)}")
        return {
            'status': 'error',
            'message': str(e),
            'series_status': []
        }

# Utility functions for frontend integration

def get_available_templates() -> List[Dict[str, Any]]:
    """
    Get all available autosegmentation templates for dropdown selection
    
    Returns:
        List of template dictionaries
    """
    try:
        templates = AutosegmentationTemplate.objects.all().values(
            'id', 'template_name', 'template_description', 'created_at'
        )
        
        template_list = []
        for template in templates:
            template_list.append({
                'id': str(template['id']),
                'name': template['template_name'],
                'description': template['template_description'],
                'created_at': template['created_at'].isoformat()
            })
        
        logger.info(f"Retrieved {len(template_list)} available templates")
        return template_list
        
    except Exception as e:
        logger.error(f"Error retrieving available templates: {str(e)}")
        return []

def cancel_manual_processing(series_uids: List[str]) -> Dict[str, Any]:
    """
    Cancel manual processing for selected series (reset status)
    
    Args:
        series_uids: List of series instance UIDs to cancel processing for
        
    Returns:
        Dictionary with cancellation results
    """
    logger.info(f"Cancelling manual processing for {len(series_uids)} series")
    
    try:
        cancelled_count = 0
        errors = []
        
        with transaction.atomic():
            for series_uid in series_uids:
                try:
                    series = DICOMSeries.objects.get(series_instance_uid=series_uid)
                    
                    # Only cancel if not already completed
                    if series.series_processsing_status not in [
                        ProcessingStatus.SENT_TO_DRAW_SERVER,
                        ProcessingStatus.RTSTRUCTURE_RECEIVED,
                        ProcessingStatus.RTSTRUCTURE_EXPORTED
                    ]:
                        series.series_processsing_status = ProcessingStatus.UNPROCESSED
                        series.matched_templates.clear()
                        series.save()
                        cancelled_count += 1
                        logger.info(f"Cancelled processing for series: {mask_sensitive_data(series_uid, 'series_uid')}")
                    else:
                        errors.append(f"Cannot cancel series {mask_sensitive_data(series_uid, 'series_uid')} - already completed")
                        
                except DICOMSeries.DoesNotExist:
                    errors.append(f"Series not found: {mask_sensitive_data(series_uid, 'series_uid')}")
        
        return {
            'status': 'success',
            'cancelled_count': cancelled_count,
            'errors': errors,
            'message': f'Cancelled processing for {cancelled_count} series'
        }
        
    except Exception as e:
        logger.error(f"Error cancelling manual processing: {str(e)}")
        return {
            'status': 'error',
            'message': str(e),
            'cancelled_count': 0
        }



