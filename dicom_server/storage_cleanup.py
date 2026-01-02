"""
Storage cleanup utilities for DICOM server.
Handles automatic deletion of old files when storage limits are reached.
"""

import os
import logging
from datetime import datetime, timedelta
from django.utils import timezone
from pathlib import Path

logger = logging.getLogger(__name__)


def cleanup_old_files(storage_path, retention_days, target_free_gb=10):
    """
    Clean up old files from storage to free up space.
    
    Args:
        storage_path: Root path of DICOM storage
        retention_days: Minimum age in days before files can be deleted
        target_free_gb: Target amount of space to free up in GB
        
    Returns:
        dict: Cleanup statistics (files_deleted, space_freed_gb, errors)
    """
    stats = {
        'files_deleted': 0,
        'space_freed_bytes': 0,
        'space_freed_gb': 0,
        'errors': 0,
        'deleted_files': []
    }
    
    if not os.path.exists(storage_path):
        logger.warning(f"Storage path does not exist: {storage_path}")
        return stats
    
    # Calculate cutoff date
    cutoff_date = timezone.now() - timedelta(days=retention_days)
    cutoff_timestamp = cutoff_date.timestamp()
    
    logger.info(f"Starting storage cleanup: retention={retention_days} days, target={target_free_gb}GB")
    
    # Collect all DICOM files with their modification times
    file_list = []
    for root, dirs, files in os.walk(storage_path):
        for filename in files:
            if filename.endswith('.dcm'):
                filepath = os.path.join(root, filename)
                try:
                    file_stat = os.stat(filepath)
                    file_list.append({
                        'path': filepath,
                        'mtime': file_stat.st_mtime,
                        'size': file_stat.st_size
                    })
                except Exception as e:
                    logger.error(f"Error accessing file {filepath}: {str(e)}")
                    stats['errors'] += 1
    
    # Sort by modification time (oldest first)
    file_list.sort(key=lambda x: x['mtime'])
    
    # Delete old files until we reach target or run out of old files
    target_bytes = target_free_gb * (1024**3)
    
    for file_info in file_list:
        # Stop if we've freed enough space
        if stats['space_freed_bytes'] >= target_bytes:
            break
        
        # Only delete files older than retention period
        if file_info['mtime'] < cutoff_timestamp:
            try:
                os.remove(file_info['path'])
                stats['files_deleted'] += 1
                stats['space_freed_bytes'] += file_info['size']
                stats['deleted_files'].append(file_info['path'])
                
                logger.debug(f"Deleted old file: {file_info['path']}")
                
            except Exception as e:
                logger.error(f"Error deleting file {file_info['path']}: {str(e)}")
                stats['errors'] += 1
    
    # Clean up empty directories
    _cleanup_empty_directories(storage_path)
    
    # Calculate GB freed
    stats['space_freed_gb'] = round(stats['space_freed_bytes'] / (1024**3), 2)
    
    logger.info(f"Cleanup complete: deleted {stats['files_deleted']} files, "
                f"freed {stats['space_freed_gb']}GB, {stats['errors']} errors")
    
    return stats


def _cleanup_empty_directories(storage_path):
    """
    Remove empty directories from storage path.
    
    Args:
        storage_path: Root path to clean up
    """
    for root, dirs, files in os.walk(storage_path, topdown=False):
        for dirname in dirs:
            dirpath = os.path.join(root, dirname)
            try:
                # Only remove if directory is empty
                if not os.listdir(dirpath):
                    os.rmdir(dirpath)
                    logger.debug(f"Removed empty directory: {dirpath}")
            except Exception as e:
                logger.debug(f"Could not remove directory {dirpath}: {str(e)}")


def get_storage_usage(storage_path):
    """
    Calculate current storage usage.
    
    Args:
        storage_path: Root path of DICOM storage
        
    Returns:
        dict: Storage statistics (total_files, total_bytes, total_gb)
    """
    stats = {
        'total_files': 0,
        'total_bytes': 0,
        'total_gb': 0
    }
    
    if not os.path.exists(storage_path):
        return stats
    
    for root, dirs, files in os.walk(storage_path):
        for filename in files:
            if filename.endswith('.dcm'):
                filepath = os.path.join(root, filename)
                try:
                    stats['total_files'] += 1
                    stats['total_bytes'] += os.path.getsize(filepath)
                except Exception as e:
                    logger.error(f"Error accessing file {filepath}: {str(e)}")
    
    stats['total_gb'] = round(stats['total_bytes'] / (1024**3), 2)
    
    return stats


def check_and_cleanup_if_needed(service):
    """
    Check storage usage and perform cleanup if needed.
    
    Args:
        service: DicomSCPService instance
        
    Returns:
        bool: True if cleanup was performed, False otherwise
    """
    try:
        from dicom_handler.models import SystemConfiguration
        
        # Get storage path from SystemConfiguration
        system_config = SystemConfiguration.objects.get(pk=1)
        storage_path = system_config.folder_configuration
        
        if not storage_path:
            logger.warning("Storage path not configured")
            return False
        
        # Check if cleanup is enabled
        if not service.config.enable_storage_cleanup:
            return False
        
        # Get current usage
        usage = get_storage_usage(storage_path)
        current_gb = usage['total_gb']
        max_gb = service.config.max_storage_size_gb
        
        # Check if we're over the limit
        if current_gb >= max_gb:
            logger.warning(f"Storage limit reached: {current_gb}GB / {max_gb}GB")
            
            # Calculate how much space we need to free
            # Free up 20% of max storage or 10GB, whichever is larger
            target_free_gb = max(10, max_gb * 0.2)
            
            # Perform cleanup
            cleanup_stats = cleanup_old_files(
                storage_path,
                service.config.storage_retention_days,
                target_free_gb
            )
            
            # Log cleanup action
            from .models import DicomTransaction
            DicomTransaction.objects.create(
                transaction_type='CLEANUP',
                status='SUCCESS' if cleanup_stats['errors'] == 0 else 'PARTIAL',
                calling_ae_title='SYSTEM',
                remote_ip='127.0.0.1',
                files_processed=cleanup_stats['files_deleted'],
                error_message=f"Freed {cleanup_stats['space_freed_gb']}GB, {cleanup_stats['errors']} errors" if cleanup_stats['errors'] > 0 else None
            )
            
            return True
        
        return False
        
    except Exception as e:
        logger.error(f"Error in storage cleanup check: {str(e)}")
        return False
