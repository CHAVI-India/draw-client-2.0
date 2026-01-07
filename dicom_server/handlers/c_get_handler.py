"""
C-GET handler for DICOM retrieve operations.
Allows remote systems to retrieve DICOM files from this SCP over the same association.
"""

import logging
import os
from pathlib import Path

from pydicom import dcmread
from pydicom.dataset import Dataset

logger = logging.getLogger(__name__)


def handle_c_get(service, event):
    """
    Handle C-GET request - retrieve DICOM files and send over same association.
    
    C-GET retrieves files from this SCP and sends them back to the requesting SCU
    over the same association (unlike C-MOVE which sends to a third party).
    
    Args:
        service: DicomSCPService instance
        event: C-GET event from pynetdicom
    
    Yields:
        tuple: (status, identifier) for each sub-operation
    """
    calling_ae = event.assoc.requestor.ae_title
    remote_ip = event.assoc.requestor.address
    
    logger.info(f"C-GET request from {calling_ae} ({remote_ip})")
    
    # Get the query dataset
    query_ds = event.identifier
    
    try:
        # Determine query level
        query_level = getattr(query_ds, 'QueryRetrieveLevel', 'STUDY')
        
        logger.debug(f"C-GET query level: {query_level}")
        
        # Search for matching DICOM files
        matches = _search_dicom_storage(service, query_ds, query_level)
        
        if not matches:
            logger.info("C-GET: No matches found")
            service._log_transaction(
                'C-GET',
                'SUCCESS',
                event,
                patient_id=getattr(query_ds, 'PatientID', None),
                study_instance_uid=getattr(query_ds, 'StudyInstanceUID', None),
                series_instance_uid=getattr(query_ds, 'SeriesInstanceUID', None)
            )
            # First yield must be number of sub-operations (0 for no matches)
            yield 0
            return
        
        # First yield: number of sub-operations (total files to send)
        num_sub_operations = len(matches)
        yield num_sub_operations
        
        # Send files back to requestor
        success_count = 0
        failure_count = 0
        warning_count = 0
        
        for file_path in matches:
            try:
                # Read the DICOM file
                ds = dcmread(file_path)
                
                # Send the dataset back to the requestor
                # The pynetdicom framework handles the C-STORE sub-operation
                status = yield (0xFF00, ds)  # Pending with dataset
                
                if status and hasattr(status, 'Status'):
                    if status.Status == 0x0000:  # Success
                        success_count += 1
                    elif status.Status in [0xB000, 0xB007, 0xB006]:  # Warning
                        warning_count += 1
                    else:  # Failure
                        failure_count += 1
                else:
                    success_count += 1
                    
            except Exception as e:
                logger.error(f"Error sending file {file_path}: {str(e)}")
                failure_count += 1
                # Yield failure status
                identifier = Dataset()
                identifier.QueryRetrieveLevel = query_level
                yield (0xC000, identifier)
        
        # Log the transaction
        final_status = 'SUCCESS' if failure_count == 0 else 'FAILURE'
        service._log_transaction(
            'C-GET',
            final_status,
            event,
            patient_id=getattr(query_ds, 'PatientID', None),
            study_instance_uid=getattr(query_ds, 'StudyInstanceUID', None),
            series_instance_uid=getattr(query_ds, 'SeriesInstanceUID', None)
        )
        
        logger.info(f"C-GET completed: {success_count} success, {failure_count} failures, {warning_count} warnings")
        
        # Final success status
        yield (0x0000, None)
        
    except Exception as e:
        logger.error(f"C-GET failed: {str(e)}")
        service._log_transaction(
            'C-GET',
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
    
    Returns:
        list: List of file paths matching the query
    """
    from dicom_handler.models import DICOMSeries
    
    matches = []
    
    # Extract query parameters
    patient_id = getattr(query_ds, 'PatientID', None)
    study_uid = getattr(query_ds, 'StudyInstanceUID', None)
    series_uid = getattr(query_ds, 'SeriesInstanceUID', None)
    
    try:
        # Query database for matching series
        queryset = DICOMSeries.objects.select_related('study__patient').all()
        
        if patient_id:
            queryset = queryset.filter(study__patient__patient_id__iexact=patient_id)
        
        if study_uid:
            queryset = queryset.filter(study__study_instance_uid__iexact=study_uid)
        
        if series_uid:
            queryset = queryset.filter(series_instance_uid__iexact=series_uid)
        
        # Get file paths from series_root_path
        for series in queryset:
            if series.series_root_path and os.path.exists(series.series_root_path):
                # Get all .dcm files in the series directory
                for root, dirs, files in os.walk(series.series_root_path):
                    for filename in files:
                        if filename.endswith('.dcm'):
                            file_path = os.path.join(root, filename)
                            matches.append(file_path)
                            
                            # Limit results
                            if len(matches) >= 1000:
                                logger.warning("C-GET result limit reached (1000 matches)")
                                return matches
        
        logger.info(f"C-GET found {len(matches)} matching files from database")
        return matches
        
    except Exception as e:
        logger.error(f"Error querying database for C-GET: {str(e)}")
        return []


