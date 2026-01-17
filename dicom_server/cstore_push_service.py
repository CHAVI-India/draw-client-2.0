"""
C-STORE Push Service for sending DICOM files to remote nodes.
Provides standalone C-STORE SCU functionality for manual file transfers.
"""

import logging
import os
from pathlib import Path

from pydicom import dcmread
from pynetdicom import AE, StoragePresentationContexts
from django.utils import timezone

logger = logging.getLogger(__name__)


def send_dicom_files_to_node(remote_node, file_paths, calling_ae_title=None):
    """
    Send DICOM files to a remote node via C-STORE.
    
    Args:
        remote_node: RemoteDicomNode instance
        file_paths: List of file paths to send
        calling_ae_title: Optional AE title to use (defaults to server config)
    
    Returns:
        dict: Results with success/failure counts and details
    """
    from .models import DicomServerConfig, DicomTransaction
    
    results = {
        'success': False,
        'total_files': len(file_paths),
        'sent_count': 0,
        'failed_count': 0,
        'details': [],
        'error_message': None
    }
    
    try:
        # Validate remote node configuration
        if not remote_node.host or not remote_node.port:
            results['error_message'] = "Remote node missing host or port configuration"
            return results
        
        if not remote_node.incoming_ae_title:
            results['error_message'] = "Remote node missing AE title configuration"
            return results
        
        # Get our AE title
        if not calling_ae_title:
            try:
                config = DicomServerConfig.objects.get(pk=1)
                calling_ae_title = config.ae_title
            except DicomServerConfig.DoesNotExist:
                calling_ae_title = "DRAW_SCU"
        
        logger.info(f"Initiating C-STORE push to {remote_node.name} ({remote_node.incoming_ae_title}@{remote_node.host}:{remote_node.port})")
        logger.info(f"Sending {len(file_paths)} files as {calling_ae_title}")
        
        # Create Application Entity for sending
        # Use StoragePresentationContexts instead of AllStoragePresentationContexts
        # to stay within the 128 presentation context limit
        ae = AE(ae_title=calling_ae_title)
        ae.requested_contexts = StoragePresentationContexts
        
        # Associate with destination
        assoc = ae.associate(
            remote_node.host,
            remote_node.port,
            ae_title=remote_node.incoming_ae_title
        )
        
        if not assoc.is_established:
            results['error_message'] = f"Failed to establish association with {remote_node.name}"
            logger.error(results['error_message'])
            return results
        
        logger.info(f"Association established with {remote_node.name}")
        
        # Send each file
        for file_path in file_paths:
            file_result = {
                'file_path': file_path,
                'success': False,
                'error': None
            }
            
            try:
                if not os.path.exists(file_path):
                    file_result['error'] = "File not found"
                    results['failed_count'] += 1
                    results['details'].append(file_result)
                    continue
                
                # Read DICOM file
                ds = dcmread(file_path)
                
                # Send via C-STORE
                status = assoc.send_c_store(ds)
                
                if status and status.Status == 0x0000:
                    file_result['success'] = True
                    results['sent_count'] += 1
                    logger.debug(f"Successfully sent: {os.path.basename(file_path)}")
                    
                    # Log transaction
                    _log_cstore_transaction(
                        calling_ae_title,
                        remote_node,
                        ds,
                        file_path,
                        'SUCCESS'
                    )
                else:
                    status_code = status.Status if status else 'Unknown'
                    file_result['error'] = f"C-STORE failed with status: {status_code}"
                    results['failed_count'] += 1
                    logger.warning(f"Failed to send {os.path.basename(file_path)}: {file_result['error']}")
                    
                    # Log failed transaction
                    _log_cstore_transaction(
                        calling_ae_title,
                        remote_node,
                        ds,
                        file_path,
                        'FAILURE',
                        error_message=file_result['error']
                    )
                    
            except Exception as e:
                file_result['error'] = str(e)
                results['failed_count'] += 1
                logger.error(f"Error sending {file_path}: {str(e)}")
            
            results['details'].append(file_result)
        
        # Release association
        assoc.release()
        logger.info(f"Association released. Sent {results['sent_count']}/{results['total_files']} files")
        
        # Update remote node last successful connection timestamp
        remote_node.last_successful_connection = timezone.now()
        remote_node.save(update_fields=['last_successful_connection'])
        
        results['success'] = results['sent_count'] > 0
        
    except Exception as e:
        results['error_message'] = str(e)
        logger.error(f"C-STORE push failed: {str(e)}")
    
    return results


def send_files_to_node(remote_node, file_paths, calling_ae_title=None):
    """
    Alias for send_dicom_files_to_node for consistency.
    
    Args:
        remote_node: RemoteDicomNode instance
        file_paths: List of file paths to send
        calling_ae_title: Optional AE title to use
    
    Returns:
        dict: Results with success/failure counts
    """
    return send_dicom_files_to_node(remote_node, file_paths, calling_ae_title)


def send_series_to_node(remote_node, series_instance_uids, calling_ae_title=None):
    """
    Send entire DICOM series to a remote node.
    
    Args:
        remote_node: RemoteDicomNode instance
        series_instance_uids: List of series instance UIDs to send
        calling_ae_title: Optional AE title to use
    
    Returns:
        dict: Results with success/failure counts
    """
    from dicom_handler.models import DICOMInstance, RTStructureFileImport
    
    file_paths = []
    
    # Collect file paths from DICOMInstance
    for series_uid in series_instance_uids:
        instances = DICOMInstance.objects.filter(
            series_instance_uid__series_instance_uid=series_uid
        )
        
        for instance in instances:
            if instance.instance_path and os.path.exists(instance.instance_path):
                file_paths.append(instance.instance_path)
        
        # Also include RT Structure files if they exist
        rt_structs = RTStructureFileImport.objects.filter(
            deidentified_series_instance_uid__series_instance_uid=series_uid,
            reidentified_rt_structure_file_path__isnull=False
        )
        
        for rt_struct in rt_structs:
            if rt_struct.reidentified_rt_structure_file_path and os.path.exists(rt_struct.reidentified_rt_structure_file_path):
                file_paths.append(rt_struct.reidentified_rt_structure_file_path)
    
    if not file_paths:
        return {
            'success': False,
            'total_files': 0,
            'sent_count': 0,
            'failed_count': 0,
            'details': [],
            'error_message': 'No files found for specified series'
        }
    
    return send_dicom_files_to_node(remote_node, file_paths, calling_ae_title)


def _log_cstore_transaction(calling_ae, remote_node, dataset, file_path, status, error_message=None):
    """
    Log C-STORE transaction to database.
    """
    from .models import DicomTransaction
    import socket
    
    try:
        file_size = os.path.getsize(file_path) if os.path.exists(file_path) else None
        
        # Convert hostname to IP address if needed
        remote_ip = remote_node.host
        if remote_ip == 'localhost':
            remote_ip = '127.0.0.1'
        elif not remote_ip.replace('.', '').isdigit():
            # Try to resolve hostname to IP
            try:
                remote_ip = socket.gethostbyname(remote_ip)
            except socket.gaierror:
                # If resolution fails, use a placeholder
                remote_ip = '0.0.0.0'
        
        DicomTransaction.objects.create(
            transaction_type='C-STORE',
            status=status,
            calling_ae_title=calling_ae,
            called_ae_title=remote_node.incoming_ae_title,
            remote_ip=remote_ip,
            remote_port=remote_node.port,
            patient_id=getattr(dataset, 'PatientID', None),
            study_instance_uid=getattr(dataset, 'StudyInstanceUID', None),
            series_instance_uid=getattr(dataset, 'SeriesInstanceUID', None),
            sop_instance_uid=getattr(dataset, 'SOPInstanceUID', None),
            sop_class_uid=getattr(dataset, 'SOPClassUID', None),
            file_path=file_path,
            file_size_bytes=file_size,
            error_message=error_message
        )
    except Exception as e:
        logger.error(f"Failed to log C-STORE transaction: {str(e)}")


def test_cstore_connection(remote_node, calling_ae_title=None):
    """
    Test C-STORE connection to a remote node using C-ECHO.
    
    Args:
        remote_node: RemoteDicomNode instance
        calling_ae_title: Optional AE title to use
    
    Returns:
        dict: Test results
    """
    from .models import DicomServerConfig
    from pynetdicom.sop_class import VerificationSOPClass
    
    result = {
        'success': False,
        'message': None
    }
    
    try:
        # Validate configuration
        if not remote_node.host or not remote_node.port:
            result['message'] = "Remote node missing host or port configuration"
            return result
        
        if not remote_node.incoming_ae_title:
            result['message'] = "Remote node missing AE title configuration"
            return result
        
        # Get our AE title
        if not calling_ae_title:
            try:
                config = DicomServerConfig.objects.get(pk=1)
                calling_ae_title = config.ae_title
            except DicomServerConfig.DoesNotExist:
                calling_ae_title = "DRAW_SCU"
        
        # Create AE and add verification context
        ae = AE(ae_title=calling_ae_title)
        ae.add_requested_context(VerificationSOPClass)
        
        # Attempt association
        assoc = ae.associate(
            remote_node.host,
            remote_node.port,
            ae_title=remote_node.incoming_ae_title
        )
        
        if assoc.is_established:
            # Send C-ECHO
            status = assoc.send_c_echo()
            assoc.release()
            
            if status and status.Status == 0x0000:
                result['success'] = True
                result['message'] = f"Successfully connected to {remote_node.name}"
                
                # Update last successful connection
                remote_node.last_successful_connection = timezone.now()
                remote_node.save(update_fields=['last_successful_connection'])
            else:
                result['message'] = f"C-ECHO failed with status: {status.Status if status else 'Unknown'}"
        else:
            result['message'] = f"Failed to establish association with {remote_node.name}"
            
    except Exception as e:
        result['message'] = f"Connection test failed: {str(e)}"
        logger.error(f"C-STORE connection test error: {str(e)}")
    
    return result
