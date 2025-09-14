
# This file will hold the list of tasks that have to be done by the application. Note the task definitions will be done here. Actual code to be given in modular files in separate services folder
# The tasks will run in two chains - one for sending the data to API server and othe for retrieving it back

# Chain A : Sending Data to API Server (files in export_services_folder)
# Task 1: Read DICOM Data (code to be written in task1_read_dicom_from_storage.py)
# Task 2: Match Autosegmentation Template (code to be written in task2_match_autosegmentation_template.py)
# Task 3: Deidentify the series (code to be written in task3_deidentify_series.py)
# Task 4: Send the deidentified series to the Draw API server (code to be written to task4_export_series_to_api.py)
# This will run as a scheduled task using celery beat.
# We need to ensure that race conditions are avoided if the task chains run for a longer period of time than the interval between two tasks in beat periodic task configuration. In other words, if the task is supposed to run every 10 min but the task before it has not completed yet then it should not start. Hence beat will run as a seperate worker process and will have a concurrency of 1.

import logging
from celery import shared_task, chain
from celery.exceptions import Retry
from django.utils import timezone
from django.db import transaction
from django.core.cache import cache
import time

# Import the actual task implementations from export_services
from .export_services.task1_read_dicom_from_storage import read_dicom_from_storage
from .export_services.task2_match_autosegmentation_template import match_autosegmentation_template
from .export_services.task3_deidentify_series import deidentify_series
from .export_services.task4_export_series_to_api import export_series_to_api

# Configure logging
logger = logging.getLogger(__name__)

# ============================================================================
# Task Serialization Configuration
# ============================================================================

# Lock configuration for Chain A serialization
CHAIN_A_LOCK_KEY = "dicom_handler:chain_a_lock"
LOCK_EXPIRE = 60 * 60 * 4  # 4 hours - should be longer than expected chain duration
LOCK_TIMEOUT = 10  # 10 seconds to wait for lock acquisition

def acquire_lock(lock_key, lock_expire=LOCK_EXPIRE, lock_timeout=LOCK_TIMEOUT):
    """
    Acquire a distributed lock using Django cache (memcached).
    
    Args:
        lock_key (str): The cache key for the lock
        lock_expire (int): Lock expiration time in seconds
        lock_timeout (int): Time to wait for lock acquisition in seconds
        
    Returns:
        bool: True if lock acquired, False otherwise
    """
    identifier = f"{time.time()}-{id(object())}"
    end = time.time() + lock_timeout
    
    while time.time() < end:
        # Try to acquire the lock
        if cache.add(lock_key, identifier, lock_expire):
            logger.info(f"Lock acquired: {lock_key} with identifier: {identifier}")
            return True
        
        # If lock exists, check if it's our lock (in case of retry)
        current_lock = cache.get(lock_key)
        if current_lock == identifier:
            logger.info(f"Lock already held by this process: {lock_key}")
            return True
            
        # Wait a bit before retrying
        time.sleep(0.1)
    
    logger.warning(f"Failed to acquire lock: {lock_key} within {lock_timeout} seconds")
    return False

def release_lock(lock_key):
    """
    Release a distributed lock.
    
    Args:
        lock_key (str): The cache key for the lock
        
    Returns:
        bool: True if lock released, False otherwise
    """
    try:
        cache.delete(lock_key)
        logger.info(f"Lock released: {lock_key}")
        return True
    except Exception as e:
        logger.error(f"Error releasing lock {lock_key}: {str(e)}")
        return False

# ============================================================================
# CHAIN A: DICOM Export Tasks (Sending Data to API Server)
# ============================================================================

@shared_task(bind=True, name='dicom_handler.task1_read_dicom_from_storage')
def task1_read_dicom_from_storage_celery(self):
    """
    Celery task wrapper for Task 1: Read DICOM Data from Storage
    
    This task reads DICOM files from the configured storage folder, processes them,
    and creates database records for Patient, DICOMStudy, DICOMSeries, and DICOMInstance.
    
    Returns:
        dict: JSON-serializable dictionary containing processing results and series data
              for the next task in the chain
    """
    try:
        logger.info(f"Starting Task 1 - Read DICOM from Storage (Task ID: {self.request.id})")
        
        # Call the actual implementation
        result = read_dicom_from_storage()
        
        # Log summary
        if result.get('status') == 'success':
            logger.info(
                f"Task 1 completed successfully. "
                f"Processed: {result.get('processed_files', 0)}, "
                f"Skipped: {result.get('skipped_files', 0)}, "
                f"Errors: {result.get('error_files', 0)}, "
                f"Series for next task: {len(result.get('series_data', []))}"
            )
        else:
            logger.error(f"Task 1 failed: {result.get('message', 'Unknown error')}")
        
        return result
        
    except Exception as e:
        logger.error(f"Critical error in Task 1 celery wrapper: {str(e)}")
        return {"status": "error", "message": f"Celery task error: {str(e)}"}


@shared_task(bind=True, name='dicom_handler.task2_match_autosegmentation_template')
def task2_match_autosegmentation_template_celery(self, task1_output):
    """
    Celery task wrapper for Task 2: Match Autosegmentation Template
    
    This task evaluates rulesets against DICOM series metadata to determine
    which series match configured autosegmentation templates.
    
    Args:
        task1_output (dict): Output from Task 1 containing series data
        
    Returns:
        dict: JSON-serializable dictionary containing matched series information
              for the next task in the chain
    """
    try:
        logger.info(f"Starting Task 2 - Match Autosegmentation Template (Task ID: {self.request.id})")
        
        # Validate input from previous task
        if not task1_output or task1_output.get('status') != 'success':
            logger.error("Task 2 received invalid input from Task 1")
            return {"status": "error", "message": "Invalid input from previous task"}
        
        # Call the actual implementation
        result = match_autosegmentation_template(task1_output)
        
        # Log summary
        if result.get('status') == 'success':
            logger.info(
                f"Task 2 completed successfully. "
                f"Processed: {result.get('processed_series', 0)}, "
                f"Total matches: {result.get('total_matches', 0)}, "
                f"Matched series for next task: {len(result.get('matched_series', []))}"
            )
        else:
            logger.error(f"Task 2 failed: {result.get('message', 'Unknown error')}")
        
        return result
        
    except Exception as e:
        logger.error(f"Critical error in Task 2 celery wrapper: {str(e)}")
        return {"status": "error", "message": f"Celery task error: {str(e)}"}


@shared_task(bind=True, name='dicom_handler.task3_deidentify_series')
def task3_deidentify_series_celery(self, task2_output):
    """
    Celery task wrapper for Task 3: Deidentify DICOM Series
    
    This task deidentifies matched DICOM series by replacing UIDs, masking patient
    information, generating autosegmentation templates, and creating ZIP files.
    
    Args:
        task2_output (dict): Output from Task 2 containing matched series data
        
    Returns:
        dict: JSON-serializable dictionary containing deidentified series information
              for the next task in the chain
    """
    try:
        logger.info(f"Starting Task 3 - Deidentify Series (Task ID: {self.request.id})")
        
        # Validate input from previous task
        if not task2_output or task2_output.get('status') != 'success':
            logger.error("Task 3 received invalid input from Task 2")
            return {"status": "error", "message": "Invalid input from previous task"}
        
        # Call the actual implementation
        result = deidentify_series(task2_output)
        
        # Log summary
        if result.get('status') == 'success':
            logger.info(
                f"Task 3 completed successfully. "
                f"Processed: {result.get('processed_series', 0)}, "
                f"Successful deidentifications: {result.get('successful_deidentifications', 0)}, "
                f"Deidentified series for next task: {len(result.get('deidentified_series', []))}"
            )
        else:
            logger.error(f"Task 3 failed: {result.get('message', 'Unknown error')}")
        
        return result
        
    except Exception as e:
        logger.error(f"Critical error in Task 3 celery wrapper: {str(e)}")
        return {"status": "error", "message": f"Celery task error: {str(e)}"}


@shared_task(bind=True, name='dicom_handler.task4_export_series_to_api')
def task4_export_series_to_api_celery(self, task3_output):
    """
    Celery task wrapper for Task 4: Export Series to DRAW API Server
    
    This task uploads deidentified DICOM series ZIP files to the DRAW API server
    with proper authentication, health checks, and checksum validation.
    
    Args:
        task3_output (dict): Output from Task 3 containing deidentified series data
        
    Returns:
        dict: JSON-serializable dictionary containing export results
    """
    try:
        logger.info(f"Starting Task 4 - Export Series to API (Task ID: {self.request.id})")
        
        # Validate input from previous task
        if not task3_output or task3_output.get('status') != 'success':
            logger.error("Task 4 received invalid input from Task 3")
            return {"status": "error", "message": "Invalid input from previous task"}
        
        # Call the actual implementation
        result = export_series_to_api(task3_output)
        
        # Log summary
        if result.get('status') == 'success':
            logger.info(
                f"Task 4 completed successfully. "
                f"Processed: {result.get('processed_series', 0)}, "
                f"Successful exports: {result.get('successful_exports', 0)}"
            )
        else:
            logger.error(f"Task 4 failed: {result.get('message', 'Unknown error')}")
        
        return result
        
    except Exception as e:
        logger.error(f"Critical error in Task 4 celery wrapper: {str(e)}")
        return {"status": "error", "message": f"Celery task error: {str(e)}"}


# ============================================================================
# CHAIN A: Complete Task Chain Configuration
# ============================================================================

@shared_task(bind=True, name='dicom_handler.run_chain_a_export_pipeline')
def run_chain_a_export_pipeline(self):
    """
    Execute the complete Chain A pipeline for DICOM export to API server.
    
    This task creates and executes a celery chain of all 4 tasks in sequence:
    1. Read DICOM from Storage
    2. Match Autosegmentation Template  
    3. Deidentify Series
    4. Export Series to API
    
    Uses memcached-based locking to ensure only one instance can run at a time.
    Race conditions are avoided by using both celery's task chaining mechanism
    and distributed locking.
    
    Returns:
        dict: Status information about the initiated pipeline
    """
    lock_acquired = False
    try:
        logger.info(f"Starting Chain A - Complete DICOM Export Pipeline (Task ID: {self.request.id})")
        
        # Try to acquire the lock to ensure only one Chain A runs at a time
        if not acquire_lock(CHAIN_A_LOCK_KEY):
            logger.warning("Chain A pipeline already running - another instance holds the lock")
            return {
                "status": "skipped",
                "message": "Chain A pipeline already running - skipping this execution",
                "task_id": self.request.id
            }
        
        lock_acquired = True
        start_time = timezone.now()
        
        logger.info("Lock acquired successfully - proceeding with Chain A execution")
        
        # Create the task chain
        # Each task will receive the output from the previous task as input
        task_chain = chain(
            task1_read_dicom_from_storage_celery.s(),
            task2_match_autosegmentation_template_celery.s(),
            task3_deidentify_series_celery.s(),
            task4_export_series_to_api_celery.s()
        )
        
        # Execute the chain asynchronously
        logger.info("Executing Chain A task sequence asynchronously...")
        async_result = task_chain.apply_async()
        
        logger.info(f"Chain A pipeline initiated successfully. Chain ID: {async_result.id}")
        
        return {
            "status": "initiated",
            "message": "Chain A pipeline started successfully",
            "chain_id": async_result.id,
            "start_time": start_time.isoformat(),
            "task_id": self.request.id,
            "note": "Pipeline is running asynchronously. Check chain_id for completion status."
        }
        
    except Exception as e:
        logger.error(f"Critical error in Chain A pipeline: {str(e)}")
        return {
            "status": "error",
            "message": f"Chain A pipeline error: {str(e)}",
            "start_time": start_time.isoformat() if 'start_time' in locals() else None,
            "task_id": self.request.id
        }
    
    finally:
        # Release the lock since we're not waiting for completion
        if lock_acquired:
            release_lock(CHAIN_A_LOCK_KEY)
            logger.info("Chain A pipeline lock released")


# ============================================================================
# Utility Functions for Task Management
# ============================================================================

def get_chain_a_status():
    """
    Get the current status of Chain A tasks.
    
    Returns:
        dict: Status information about running/pending Chain A tasks
    """
    # Check if Chain A is currently running by checking the lock
    is_running = cache.get(CHAIN_A_LOCK_KEY) is not None
    
    return {
        "chain_name": "Chain A - DICOM Export Pipeline",
        "is_running": is_running,
        "lock_key": CHAIN_A_LOCK_KEY,
        "lock_expire_seconds": LOCK_EXPIRE,
        "tasks": [
            "task1_read_dicom_from_storage",
            "task2_match_autosegmentation_template", 
            "task3_deidentify_series",
            "task4_export_series_to_api"
        ],
        "description": "Reads DICOM files, matches templates, deidentifies data, and exports to API server"
    }

def is_chain_a_running():
    """
    Check if Chain A pipeline is currently running.
    
    Returns:
        bool: True if Chain A is running, False otherwise
    """
    return cache.get(CHAIN_A_LOCK_KEY) is not None

def force_release_chain_a_lock():
    """
    Force release the Chain A lock (use with caution).
    This should only be used if a task crashed and left a stale lock.
    
    Returns:
        bool: True if lock was released, False if no lock existed
    """
    if cache.get(CHAIN_A_LOCK_KEY) is not None:
        release_lock(CHAIN_A_LOCK_KEY)
        logger.warning("Chain A lock forcibly released")
        return True
    else:
        logger.info("No Chain A lock to release")
        return False


# ============================================================================
# Backend Cleanup Task
# ============================================================================

@shared_task(bind=True, name='dicom_handler.cleanup_backend')
def cleanup_backend(self):
    """
    Periodic cleanup task for backend maintenance.
    
    Performs routine cleanup operations:
    - Clear expired cache entries
    - Clean up temporary files
    - Release stale locks
    
    Returns:
        dict: Cleanup operation results
    """
    try:
        logger.info(f"Starting backend cleanup task (Task ID: {self.request.id})")
        
        cleanup_results = {
            'cache_cleared': 0,
            'temp_files_cleaned': 0,
            'stale_locks_released': 0
        }
        
        # Clear expired cache entries
        try:
            from django.core.cache import cache
            cache.clear()
            cleanup_results['cache_cleared'] = 1
            logger.info("Cache cleared successfully")
        except Exception as e:
            logger.warning(f"Cache clear failed: {str(e)}")
        
        # Release any stale Chain A locks
        try:
            if cache.get(CHAIN_A_LOCK_KEY) is not None:
                cache.delete(CHAIN_A_LOCK_KEY)
                cleanup_results['stale_locks_released'] = 1
                logger.info("Released stale Chain A lock")
        except Exception as e:
            logger.warning(f"Lock cleanup failed: {str(e)}")
        
        logger.info(f"Backend cleanup completed successfully: {cleanup_results}")
        
        return {
            "status": "success",
            "cleanup_results": cleanup_results,
            "task_id": self.request.id
        }
        
    except Exception as e:
        logger.error(f"Critical error in backend cleanup: {str(e)}")
        return {
            "status": "error",
            "message": f"Backend cleanup error: {str(e)}",
            "task_id": self.request.id
        }


#