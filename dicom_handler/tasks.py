
# This file will hold the list of tasks that have to be done by the application. Note the task definitions will be done here. Actual code to be given in modular files in separate services folder
# The tasks will run in two chains - one for sending the data to API server and othe for retrieving it back

# Chain A : Sending Data to API Server (files in export_services_folder)
# Task 1: Read DICOM Data (code to be written in task1_read_dicom_from_storage.py)
# Task 2: Match Autosegmentation Template (code to be written in task2_match_autosegmentation_template.py)
# Task 3: Deidentify the series (code to be written in task3_deidentify_series.py)
# Task 4: Send the deidentified series to the Draw API server (code to be written to task4_export_series_to_api.py)

import logging
from celery import shared_task, chain
from django.utils import timezone

# Import the actual task functions from export_services
from .export_services.task1_read_dicom_from_storage import read_dicom_from_storage
from .export_services.task2_match_autosegmentation_template import match_autosegmentation_template
from .export_services.task3_deidentify_series import deidentify_series
from .export_services.task4_export_series_to_api import export_series_to_api

# Configure logging
logger = logging.getLogger(__name__)

# Individual Celery tasks for each function
@shared_task(bind=True, name='dicom_handler.task1_read_dicom')
def task1_read_dicom(self):
    """
    Celery task for reading DICOM data from storage
    """
    try:
        logger.info("Starting Task 1: Read DICOM from storage")
        result = read_dicom_from_storage()
        logger.info(f"Task 1 completed with status: {result.get('status', 'unknown')}")
        return result
    except Exception as e:
        logger.error(f"Task 1 failed with error: {str(e)}")
        self.retry(countdown=60, max_retries=3)

@shared_task(bind=True, name='dicom_handler.task2_match_template')
def task2_match_template(self, task1_output):
    """
    Celery task for matching autosegmentation templates
    """
    try:
        logger.info("Starting Task 2: Match autosegmentation template")
        result = match_autosegmentation_template(task1_output)
        logger.info(f"Task 2 completed with status: {result.get('status', 'unknown')}")
        return result
    except Exception as e:
        logger.error(f"Task 2 failed with error: {str(e)}")
        self.retry(countdown=60, max_retries=3)

@shared_task(bind=True, name='dicom_handler.task3_deidentify')
def task3_deidentify(self, task2_output):
    """
    Celery task for deidentifying DICOM series
    """
    try:
        logger.info("Starting Task 3: Deidentify series")
        result = deidentify_series(task2_output)
        logger.info(f"Task 3 completed with status: {result.get('status', 'unknown')}")
        return result
    except Exception as e:
        logger.error(f"Task 3 failed with error: {str(e)}")
        self.retry(countdown=60, max_retries=3)

@shared_task(bind=True, name='dicom_handler.task4_export_to_api')
def task4_export_to_api(self, task3_output):
    """
    Celery task for exporting series to API server
    """
    try:
        logger.info("Starting Task 4: Export series to API")
        result = export_series_to_api(task3_output)
        logger.info(f"Task 4 completed with status: {result.get('status', 'unknown')}")
        return result
    except Exception as e:
        logger.error(f"Task 4 failed with error: {str(e)}")
        self.retry(countdown=60, max_retries=3)

# Main chain task that connects all four tasks
@shared_task(bind=True, name='dicom_handler.process_dicom_chain')
def process_dicom_chain(self):
    """
    Main Celery chain task that processes DICOM data through all four stages:
    1. Read DICOM from storage
    2. Match autosegmentation templates
    3. Deidentify series
    4. Export to API server
    
    Returns: Final result from the chain execution
    """
    try:
        logger.info("Starting DICOM processing chain")
        
        # Create the task chain
        dicom_chain = chain(
            task1_read_dicom.s(),
            task2_match_template.s(),
            task3_deidentify.s(),
            task4_export_to_api.s()
        )
        
        # Execute the chain
        result = dicom_chain.apply_async()
        
        logger.info(f"DICOM processing chain initiated with ID: {result.id}")
        return {
            "status": "chain_started",
            "chain_id": result.id,
            "message": "DICOM processing chain has been started",
            "started_at": timezone.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to start DICOM processing chain: {str(e)}")
        return {
            "status": "error",
            "message": f"Chain startup failed: {str(e)}",
            "error_at": timezone.now().isoformat()
        }

# Utility task to check chain status
@shared_task(name='dicom_handler.check_chain_status')
def check_chain_status(chain_id):
    """
    Check the status of a running DICOM processing chain
    
    Args:
        chain_id: The Celery chain ID to check
        
    Returns: Dictionary with chain status information
    """
    try:
        from celery.result import AsyncResult
        
        result = AsyncResult(chain_id)
        
        return {
            "chain_id": chain_id,
            "status": result.status,
            "result": result.result if result.ready() else None,
            "successful": result.successful() if result.ready() else None,
            "failed": result.failed() if result.ready() else None,
            "checked_at": timezone.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error checking chain status for {chain_id}: {str(e)}")
        return {
            "chain_id": chain_id,
            "status": "error",
            "message": f"Status check failed: {str(e)}",
            "checked_at": timezone.now().isoformat()
        }

# Convenience task to start the full DICOM processing workflow
@shared_task(name='dicom_handler.start_dicom_workflow')
def start_dicom_workflow():
    """
    Convenience task to start the complete DICOM processing workflow
    This is the main entry point for triggering the entire chain
    
    Returns: Chain execution result
    """
    logger.info("Triggering DICOM processing workflow")
    return process_dicom_chain.delay()

# Celery Beat scheduled task for automatic DICOM processing
@shared_task(bind=True, name='dicom_handler.scheduled_dicom_workflow')
def scheduled_dicom_workflow(self):
    """
    Celery Beat scheduled task that automatically runs the DICOM processing workflow
    This task is designed to run periodically to process new DICOM files
    
    Returns: Chain execution result with scheduling information
    """
    try:
        logger.info("Starting scheduled DICOM processing workflow")
        
        # Check if there are any pending workflows already running
        from celery.result import AsyncResult
        from django_celery_beat.models import PeriodicTask
        
        # Start the workflow chain
        chain_result = process_dicom_chain.delay()
        
        logger.info(f"Scheduled DICOM workflow initiated with chain ID: {chain_result.id}")
        
        return {
            "status": "scheduled_workflow_started",
            "chain_id": chain_result.id,
            "message": "Scheduled DICOM processing workflow has been started",
            "scheduled_at": timezone.now().isoformat(),
            "task_name": "scheduled_dicom_workflow"
        }
        
    except Exception as e:
        logger.error(f"Failed to start scheduled DICOM workflow: {str(e)}")
        return {
            "status": "error",
            "message": f"Scheduled workflow startup failed: {str(e)}",
            "error_at": timezone.now().isoformat(),
            "task_name": "scheduled_dicom_workflow"
        }

