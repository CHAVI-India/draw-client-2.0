"""
Service management utilities for DICOM SCP service.
Provides functions to start, stop, and manage the DICOM service.
"""

import logging
import os
import signal
import psutil
from django.utils import timezone

from .models import DicomServerConfig, DicomServiceStatus
from .dicom_scp_service import get_service_instance

logger = logging.getLogger(__name__)


def start_service():
    """
    Start the DICOM SCP service.
    
    Returns:
        tuple: (success: bool, message: str)
    """
    try:
        # Check if service is already running
        if is_service_running():
            return False, "DICOM service is already running"
        
        # Get service instance and start
        service = get_service_instance()
        success = service.start()
        
        if success:
            config = DicomServerConfig.objects.get(pk=1)
            return True, f"DICOM service started successfully on {config.host}:{config.port}"
        else:
            return False, "Failed to start DICOM service. Check logs for details."
            
    except DicomServerConfig.DoesNotExist:
        return False, "DICOM server configuration not found. Please configure the service first."
    except Exception as e:
        logger.error(f"Error starting DICOM service: {str(e)}")
        return False, f"Error starting DICOM service: {str(e)}"


def stop_service():
    """
    Stop the DICOM SCP service.
    
    Returns:
        tuple: (success: bool, message: str)
    """
    try:
        # Check if service is running
        if not is_service_running():
            return False, "DICOM service is not running"
        
        # Get service instance and stop
        service = get_service_instance()
        success = service.stop()
        
        if success:
            return True, "DICOM service stopped successfully"
        else:
            return False, "Failed to stop DICOM service. Check logs for details."
            
    except Exception as e:
        logger.error(f"Error stopping DICOM service: {str(e)}")
        return False, f"Error stopping DICOM service: {str(e)}"


def restart_service():
    """
    Restart the DICOM SCP service.
    
    Returns:
        tuple: (success: bool, message: str)
    """
    try:
        service = get_service_instance()
        success = service.restart()
        
        if success:
            config = DicomServerConfig.objects.get(pk=1)
            return True, f"DICOM service restarted successfully on {config.host}:{config.port}"
        else:
            return False, "Failed to restart DICOM service. Check logs for details."
            
    except Exception as e:
        logger.error(f"Error restarting DICOM service: {str(e)}")
        return False, f"Error restarting DICOM service: {str(e)}"


def is_service_running():
    """
    Check if the DICOM SCP service is currently running.
    
    Returns:
        bool: True if service is running, False otherwise
    """
    try:
        service_status = DicomServiceStatus.objects.get(pk=1)
        
        # Check if status says it's running
        if not service_status.is_running:
            return False
        
        # For thread-based service, check if the service instance is running
        service = get_service_instance()
        if service.is_running:
            return True
        
        # If service instance says not running, update database
        if service_status.is_running:
            service_status.is_running = False
            service_status.active_connections = 0
            service_status.save()
        
        return False
        
    except DicomServiceStatus.DoesNotExist:
        return False
    except Exception as e:
        logger.error(f"Error checking service status: {str(e)}")
        return False


def get_service_status():
    """
    Get detailed service status information.
    
    Returns:
        dict: Service status information
    """
    try:
        service_status = DicomServiceStatus.objects.get(pk=1)
        config = DicomServerConfig.objects.get(pk=1)
        
        is_running = is_service_running()
        
        status_info = {
            'is_running': is_running,
            'is_enabled': config.service_enabled,
            'ae_title': config.ae_title,
            'host': config.host,
            'port': config.port,
            'uptime': service_status.uptime_formatted if is_running else 'Not running',
            'active_connections': service_status.active_connections,
            'total_connections': service_status.total_connections,
            'total_files_received': service_status.total_files_received,
            'total_bytes_received': service_status.total_bytes_received,
            'total_errors': service_status.total_errors,
            'average_file_size_mb': service_status.average_file_size_mb,
            'storage_usage_gb': config.storage_usage_gb,
            'storage_available_gb': config.storage_available_gb,
            'storage_usage_percent': config.storage_usage_percent,
            'last_started': service_status.service_started_at,
            'last_stopped': service_status.service_stopped_at,
        }
        
        return status_info
        
    except Exception as e:
        logger.error(f"Error getting service status: {str(e)}")
        return {
            'is_running': False,
            'error': str(e)
        }


def auto_start_service():
    """
    Auto-start the DICOM service if configured to do so.
    This should be called during Django startup.
    
    Returns:
        bool: True if service was started, False otherwise
    """
    try:
        config = DicomServerConfig.objects.get(pk=1)
        
        if config.service_enabled and config.auto_start:
            logger.info("Auto-starting DICOM service...")
            success, message = start_service()
            
            if success:
                logger.info(f"DICOM service auto-started: {message}")
                return True
            else:
                logger.warning(f"Failed to auto-start DICOM service: {message}")
                return False
        
        return False
        
    except DicomServerConfig.DoesNotExist:
        logger.warning("DICOM server configuration not found. Cannot auto-start service.")
        return False
    except Exception as e:
        logger.error(f"Error during auto-start: {str(e)}")
        return False


def cleanup_stale_status():
    """
    Clean up stale service status if the process is no longer running.
    This should be called during Django startup.
    """
    try:
        service_status = DicomServiceStatus.objects.get(pk=1)
        
        if service_status.is_running and service_status.process_id:
            try:
                process = psutil.Process(service_status.process_id)
                if not process.is_running():
                    logger.info("Cleaning up stale DICOM service status")
                    service_status.is_running = False
                    service_status.active_connections = 0
                    service_status.save()
            except psutil.NoSuchProcess:
                logger.info("Cleaning up stale DICOM service status")
                service_status.is_running = False
                service_status.active_connections = 0
                service_status.save()
                
    except DicomServiceStatus.DoesNotExist:
        pass
    except Exception as e:
        logger.error(f"Error cleaning up stale status: {str(e)}")
