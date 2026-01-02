"""
C-FIND handler for DICOM query operations.
"""

import logging
import os
from pathlib import Path

from pydicom import dcmread
from pydicom.dataset import Dataset

logger = logging.getLogger(__name__)


def handle_c_find(service, event):
    """
    Handle C-FIND request - query for DICOM studies/series.
    
    Args:
        service: DicomSCPService instance
        event: C-FIND event from pynetdicom
    
    Yields:
        tuple: (status, identifier) for each matching result
    """
    calling_ae = event.assoc.requestor.ae_title
    remote_ip = event.assoc.requestor.address
    
    logger.info(f"C-FIND request from {calling_ae} ({remote_ip})")
    
    # Get the query dataset
    query_ds = event.identifier
    
    try:
        # Determine query level
        query_level = getattr(query_ds, 'QueryRetrieveLevel', 'STUDY')
        
        logger.debug(f"C-FIND query level: {query_level}")
        
        # Search for matching DICOM files in storage
        matches = _search_dicom_storage(service, query_ds, query_level)
        
        # Yield each match
        for match in matches:
            yield (0xFF00, match)  # Pending status with match
        
        # Log successful query
        service._log_transaction(
            'C-FIND',
            'SUCCESS',
            event,
            patient_id=getattr(query_ds, 'PatientID', None),
            study_instance_uid=getattr(query_ds, 'StudyInstanceUID', None),
            series_instance_uid=getattr(query_ds, 'SeriesInstanceUID', None)
        )
        
    except Exception as e:
        logger.error(f"C-FIND failed: {str(e)}")
        service._log_transaction(
            'C-FIND',
            'FAILURE',
            event,
            error_message=str(e)
        )
        service.service_status.total_errors += 1
        service.service_status.save()


def _search_dicom_storage(service, query_ds, query_level):
    """
    Search DICOM storage for matching files.
    
    This is a basic implementation that scans the storage directory.
    For production use, consider implementing a database index.
    """
    matches = []
    storage_path = service.config.storage_root_path
    
    if not os.path.exists(storage_path):
        return matches
    
    # Extract query parameters
    patient_id = getattr(query_ds, 'PatientID', None)
    study_uid = getattr(query_ds, 'StudyInstanceUID', None)
    series_uid = getattr(query_ds, 'SeriesInstanceUID', None)
    
    # Scan storage directory for DICOM files
    for root, dirs, files in os.walk(storage_path):
        for filename in files:
            if filename.endswith('.dcm'):
                file_path = os.path.join(root, filename)
                
                try:
                    ds = dcmread(file_path, stop_before_pixels=True)
                    
                    # Check if this file matches the query
                    if _matches_query(ds, patient_id, study_uid, series_uid, query_level):
                        # Create response dataset based on query level
                        response_ds = _create_response_dataset(ds, query_level)
                        matches.append(response_ds)
                        
                        # Limit results to avoid overwhelming the client
                        if len(matches) >= 100:
                            logger.warning("C-FIND result limit reached (100 matches)")
                            return matches
                            
                except Exception as e:
                    logger.debug(f"Error reading DICOM file {file_path}: {str(e)}")
                    continue
    
    logger.info(f"C-FIND found {len(matches)} matches")
    return matches


def _matches_query(ds, patient_id, study_uid, series_uid, query_level):
    """
    Check if a DICOM dataset matches the query parameters.
    """
    # Patient ID matching
    if patient_id and hasattr(ds, 'PatientID'):
        if patient_id != ds.PatientID:
            return False
    
    # Study UID matching
    if study_uid and hasattr(ds, 'StudyInstanceUID'):
        if study_uid != ds.StudyInstanceUID:
            return False
    
    # Series UID matching (only for SERIES level queries)
    if query_level == 'SERIES' and series_uid and hasattr(ds, 'SeriesInstanceUID'):
        if series_uid != ds.SeriesInstanceUID:
            return False
    
    return True


def _create_response_dataset(ds, query_level):
    """
    Create a response dataset based on query level.
    """
    response = Dataset()
    
    # Common attributes
    if hasattr(ds, 'PatientID'):
        response.PatientID = ds.PatientID
    if hasattr(ds, 'PatientName'):
        response.PatientName = ds.PatientName
    if hasattr(ds, 'PatientBirthDate'):
        response.PatientBirthDate = ds.PatientBirthDate
    if hasattr(ds, 'PatientSex'):
        response.PatientSex = ds.PatientSex
    
    # Study level attributes
    if hasattr(ds, 'StudyInstanceUID'):
        response.StudyInstanceUID = ds.StudyInstanceUID
    if hasattr(ds, 'StudyDate'):
        response.StudyDate = ds.StudyDate
    if hasattr(ds, 'StudyTime'):
        response.StudyTime = ds.StudyTime
    if hasattr(ds, 'StudyDescription'):
        response.StudyDescription = ds.StudyDescription
    if hasattr(ds, 'AccessionNumber'):
        response.AccessionNumber = ds.AccessionNumber
    
    # Series level attributes (if query level is SERIES)
    if query_level == 'SERIES':
        if hasattr(ds, 'SeriesInstanceUID'):
            response.SeriesInstanceUID = ds.SeriesInstanceUID
        if hasattr(ds, 'SeriesNumber'):
            response.SeriesNumber = ds.SeriesNumber
        if hasattr(ds, 'SeriesDescription'):
            response.SeriesDescription = ds.SeriesDescription
        if hasattr(ds, 'Modality'):
            response.Modality = ds.Modality
    
    # Set query retrieve level
    response.QueryRetrieveLevel = query_level
    
    return response
