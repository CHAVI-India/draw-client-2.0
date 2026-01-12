"""
C-MOVE handler for DICOM retrieve operations.
Allows remote systems to retrieve DICOM files from this SCP.
"""

import logging
import os
from pathlib import Path

from pydicom import dcmread
from pydicom.dataset import Dataset
from pynetdicom import AE
from pynetdicom.sop_class import CTImageStorage, MRImageStorage, RTStructureSetStorage, RTPlanStorage, RTDoseStorage
from pynetdicom import AllStoragePresentationContexts

logger = logging.getLogger(__name__)


def handle_c_move(service, event):
    """
    Handle C-MOVE request - retrieve DICOM files and send to destination.
    
    C-MOVE retrieves files from this SCP and sends them to a third-party destination.
    The destination AE must be configured and reachable.
    
    Args:
        service: DicomSCPService instance
        event: C-MOVE event from pynetdicom
    
    Yields:
        tuple: (status, identifier) for each sub-operation
    """
    calling_ae = event.assoc.requestor.ae_title
    remote_ip = event.assoc.requestor.address
    
    logger.info(f"C-MOVE request from {calling_ae} ({remote_ip})")
    
    # Get the query dataset
    query_ds = event.identifier
    
    # Get the destination AE title (where to send the files)
    move_destination = event.move_destination
    
    if not move_destination:
        logger.error("C-MOVE rejected: No destination AE specified")
        service._log_transaction(
            'C-MOVE',
            'REJECTED',
            event,
            error_message="No destination AE specified"
        )
        yield (0xA801, None)  # Refused: Move Destination unknown
        return
    
    try:
        # Determine query level
        query_level = getattr(query_ds, 'QueryRetrieveLevel', 'STUDY')
        
        logger.debug(f"C-MOVE query level: {query_level}, destination: {move_destination}")
        
        # Search for matching DICOM files
        matches = _search_dicom_storage(service, query_ds, query_level)
        
        if not matches:
            logger.info("C-MOVE: No matches found")
            service._log_transaction(
                'C-MOVE',
                'SUCCESS',
                event,
                patient_id=getattr(query_ds, 'PatientID', None),
                study_instance_uid=getattr(query_ds, 'StudyInstanceUID', None),
                series_instance_uid=getattr(query_ds, 'SeriesInstanceUID', None)
            )
            # First yield must be number of sub-operations (0 for no matches)
            yield 0
            return
        
        # Get destination AE configuration
        dest_config = _get_destination_config(service, move_destination)
        
        if not dest_config:
            logger.error(f"C-MOVE rejected: Destination AE '{move_destination}' not configured")
            service._log_transaction(
                'C-MOVE',
                'REJECTED',
                event,
                error_message=f"Destination AE '{move_destination}' not configured"
            )
            yield 0xA801  # Refused: Move Destination unknown
            return
        
        # First yield: destination address, port, and kwargs with presentation contexts
        # pynetdicom will create the association itself, so we need to provide contexts
        # Use StoragePresentationContexts (not All) to stay under 128 context limit
        from pynetdicom import StoragePresentationContexts
        
        logger.info(f"Yielding destination: {dest_config['host']}:{dest_config['port']} (AE: {dest_config['ae_title']})")
        logger.info(f"Our AE Title for C-STORE: {service.config.ae_title}")
        
        yield (dest_config['host'], dest_config['port'], {
            'contexts': StoragePresentationContexts,
            'ae_title': dest_config['ae_title']  # Called AE title (destination)
        })
        
        # Second yield: number of sub-operations (total files to send)
        num_sub_operations = len(matches)
        yield num_sub_operations
        
        # Yield datasets for pynetdicom to send via C-STORE
        success_count = 0
        failure_count = 0
        warning_count = 0
        
        for file_path in matches:
            try:
                # Read the DICOM file and yield it for pynetdicom to send
                ds = dcmread(file_path)
                
                # Yield the dataset - pynetdicom will send it via C-STORE
                # For C-MOVE, we just yield the dataset and pynetdicom handles the rest
                yield (0xFF00, ds)  # Pending with dataset
                
                # Count as success - pynetdicom will handle actual status tracking
                success_count += 1
                    
            except Exception as e:
                logger.error(f"Error reading file {file_path}: {str(e)}")
                failure_count += 1
        
        # Log the transaction
        final_status = 'SUCCESS' if failure_count == 0 else 'FAILURE'
        service._log_transaction(
            'C-MOVE',
            final_status,
            event,
            patient_id=getattr(query_ds, 'PatientID', None),
            study_instance_uid=getattr(query_ds, 'StudyInstanceUID', None),
            series_instance_uid=getattr(query_ds, 'SeriesInstanceUID', None)
        )
        
        logger.info(f"C-MOVE completed: {success_count} success, {failure_count} failures, {warning_count} warnings")
        
    except Exception as e:
        logger.error(f"C-MOVE failed: {str(e)}")
        service._log_transaction(
            'C-MOVE',
            'FAILURE',
            event,
            error_message=str(e)
        )
        service.service_status.total_errors += 1
        service.service_status.save()
        yield (0xC000, None)  # Error: Cannot understand


def _search_dicom_storage(service, query_ds, query_level):
    """
    Search DICOM storage using database models and return file paths.
    Uses DICOMInstance model for accurate file tracking with SOP Instance UIDs.
    Supports PATIENT, STUDY, SERIES, and IMAGE query levels.
    
    Returns:
        list: List of file paths matching the query
    """
    from dicom_handler.models import DICOMInstance, DICOMSeries
    
    matches = []
    
    # Extract query parameters
    patient_id = getattr(query_ds, 'PatientID', None)
    study_uid = getattr(query_ds, 'StudyInstanceUID', None)
    series_uid = getattr(query_ds, 'SeriesInstanceUID', None)
    sop_instance_uid = getattr(query_ds, 'SOPInstanceUID', None)
    
    try:
        # Query database for matching instances using DICOMInstance model
        # This provides accurate SOP Instance UID tracking
        queryset = DICOMInstance.objects.select_related(
            'series_instance_uid__study__patient'
        ).all()
        
        # Apply filters based on query parameters and query level
        if patient_id:
            queryset = queryset.filter(
                series_instance_uid__study__patient__patient_id__iexact=patient_id
            )
        
        if study_uid:
            queryset = queryset.filter(
                series_instance_uid__study__study_instance_uid__iexact=study_uid
            )
        
        if series_uid:
            queryset = queryset.filter(
                series_instance_uid__series_instance_uid__iexact=series_uid
            )
        
        if sop_instance_uid:
            queryset = queryset.filter(sop_instance_uid__iexact=sop_instance_uid)
        
        # Limit results based on query level to prevent overwhelming the system
        # All query levels now have the same limit
        queryset = queryset[:10000]
        
        # Collect file paths from instances
        for instance in queryset:
            if instance.instance_path and os.path.exists(instance.instance_path):
                matches.append(instance.instance_path)
            else:
                logger.warning(f"File not found for SOP Instance UID: {instance.sop_instance_uid}")
        
        logger.info(f"C-MOVE found {len(matches)} matching files from database at {query_level} level")
        return matches
        
    except Exception as e:
        logger.error(f"Error querying database for C-MOVE: {str(e)}")
        return []




def _get_destination_config(service, ae_title):
    """
    Get destination AE configuration from database using RemoteDicomNode model.
    
    Returns:
        dict: Destination configuration or None
    """
    try:
        from ..models import RemoteDicomNode
        
        # Look for a RemoteDicomNode with matching incoming_ae_title (for receiving C-STORE)
        # The destination should be configured to receive files from us
        dest = RemoteDicomNode.objects.filter(
            incoming_ae_title=ae_title,
            allow_incoming=True,
            is_active=True
        ).first()
        
        if dest and dest.host and dest.port:
            return {
                'ae_title': dest.incoming_ae_title,
                'host': dest.host,
                'port': dest.port
            }
        
        logger.warning(f"Destination AE '{ae_title}' not found, not active, or missing host/port configuration")
        return None
        
    except Exception as e:
        logger.error(f"Error getting destination config: {str(e)}")
        return None


def _send_file_to_destination(service, file_path, dest_ae, dest_host, dest_port):
    """
    Send a DICOM file to the destination AE using C-STORE.
    
    Args:
        service: DicomSCPService instance
        file_path: Path to DICOM file to send
        dest_ae: Destination AE title
        dest_host: Destination host/IP
        dest_port: Destination port
    
    Returns:
        int: DICOM status code
    """
    try:
        # Read the DICOM file
        ds = dcmread(file_path)
        
        # Create Application Entity for sending
        ae = AE(ae_title=service.config.ae_title)
        
        logger.info(f"Creating AE for C-STORE to destination: {dest_ae} at {dest_host}:{dest_port}")
        logger.info(f"Our AE Title: {service.config.ae_title}")
        
        # Add ALL storage presentation contexts
        # AllStoragePresentationContexts is a list of PresentationContext objects
        ae.requested_contexts = AllStoragePresentationContexts
        
        logger.info(f"Added {len(ae.requested_contexts)} presentation contexts")
        logger.debug(f"Requested contexts: {[cx.abstract_syntax for cx in ae.requested_contexts[:5]]}...")
        
        # Associate with destination
        logger.info(f"Attempting to associate with {dest_ae} at {dest_host}:{dest_port}")
        assoc = ae.associate(dest_host, dest_port, ae_title=dest_ae)
        
        if assoc.is_established:
            # Send the file
            status = assoc.send_c_store(ds)
            
            # Release the association
            assoc.release()
            
            if status:
                logger.debug(f"C-STORE to {dest_ae} successful: {file_path}")
                return status.Status
            else:
                logger.error(f"C-STORE to {dest_ae} failed: {file_path}")
                return 0xC000  # Error
        else:
            logger.error(f"Failed to associate with {dest_ae} at {dest_host}:{dest_port}")
            return 0xA801  # Refused: Move Destination unknown
            
    except Exception as e:
        logger.error(f"Error sending file to destination: {str(e)}")
        return 0xC000  # Error
