"""
C-FIND handler for DICOM query operations.
Uses database models for efficient querying.
"""

import logging
import os
from pathlib import Path
from django.db.models import Q

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
    Search DICOM storage using database models.
    
    Queries Patient, DICOMStudy, and DICOMSeries models for efficient searching.
    """
    from dicom_handler.models import Patient, DICOMStudy, DICOMSeries
    
    matches = []
    
    # Get max_query_results from service config
    max_results = 10000  # Default fallback
    try:
        if hasattr(service, 'config') and service.config:
            max_results = service.config.max_query_results
    except Exception as e:
        logger.warning(f"Could not get max_query_results from config, using default: {e}")
    
    # Extract query parameters
    query_params = {
        'PatientID': getattr(query_ds, 'PatientID', None),
        'PatientName': getattr(query_ds, 'PatientName', None),
        'StudyInstanceUID': getattr(query_ds, 'StudyInstanceUID', None),
        'StudyDate': getattr(query_ds, 'StudyDate', None),
        'StudyTime': getattr(query_ds, 'StudyTime', None),
        'StudyDescription': getattr(query_ds, 'StudyDescription', None),
        'AccessionNumber': getattr(query_ds, 'AccessionNumber', None),
        'ModalitiesInStudy': getattr(query_ds, 'ModalitiesInStudy', None),
        'SeriesInstanceUID': getattr(query_ds, 'SeriesInstanceUID', None),
        'SeriesNumber': getattr(query_ds, 'SeriesNumber', None),
        'SeriesDescription': getattr(query_ds, 'SeriesDescription', None),
        'Modality': getattr(query_ds, 'Modality', None),
        'SOPInstanceUID': getattr(query_ds, 'SOPInstanceUID', None),
    }
    
    try:
        if query_level == 'PATIENT':
            matches = _query_patients(query_params, max_results)
        elif query_level == 'STUDY':
            matches = _query_studies(query_params, max_results)
        elif query_level == 'SERIES':
            matches = _query_series(query_params, max_results)
        elif query_level == 'IMAGE':
            matches = _query_images(query_params, max_results)
        else:
            logger.warning(f"Unsupported query level: {query_level}")
            return matches
        
        logger.info(f"C-FIND found {len(matches)} matches at {query_level} level")
        return matches
        
    except Exception as e:
        logger.error(f"Error querying database: {str(e)}")
        return []


def _query_patients(query_params, max_results=10000):
    """
    Query Patient model and return matching DICOM datasets.
    """
    from dicom_handler.models import Patient
    
    queryset = Patient.objects.all()
    
    # Apply filters with wildcard support
    if query_params.get('PatientID'):
        queryset = _apply_wildcard_filter(queryset, 'patient_id', query_params['PatientID'])
    
    if query_params.get('PatientName'):
        queryset = _apply_wildcard_filter(queryset, 'patient_name', str(query_params['PatientName']))
    
    # Limit results
    queryset = queryset[:max_results]
    
    # Convert to DICOM datasets
    matches = []
    for patient in queryset:
        ds = Dataset()
        
        # Set QueryRetrieveLevel
        ds.QueryRetrieveLevel = 'PATIENT'
        
        if patient.patient_id:
            ds.PatientID = patient.patient_id
        else:
            ds.PatientID = ''
            
        if patient.patient_name:
            ds.PatientName = patient.patient_name
        else:
            ds.PatientName = ''
            
        if patient.patient_date_of_birth:
            ds.PatientBirthDate = patient.patient_date_of_birth.strftime('%Y%m%d')
        else:
            ds.PatientBirthDate = ''
            
        if patient.patient_gender:
            ds.PatientSex = patient.patient_gender
        else:
            ds.PatientSex = ''
            
        matches.append(ds)
    
    return matches


def _query_studies(query_params, max_results=10000):
    """
    Query DICOMStudy model and return matching DICOM datasets.
    """
    from dicom_handler.models import DICOMStudy, DICOMSeries
    from django.db.models import Count, Sum
    
    queryset = DICOMStudy.objects.select_related('patient').all()
    
    # Patient level filters
    if query_params.get('PatientID'):
        queryset = _apply_wildcard_filter(queryset, 'patient__patient_id', query_params['PatientID'])
    
    if query_params.get('PatientName'):
        queryset = _apply_wildcard_filter(queryset, 'patient__patient_name', str(query_params['PatientName']))
    
    # Study level filters
    if query_params.get('StudyInstanceUID'):
        queryset = _apply_wildcard_filter(queryset, 'study_instance_uid', query_params['StudyInstanceUID'])
    
    if query_params.get('StudyDate'):
        queryset = _apply_date_filter(queryset, 'study_date', query_params['StudyDate'])
    
    if query_params.get('StudyDescription'):
        queryset = _apply_wildcard_filter(queryset, 'study_description', query_params['StudyDescription'])
    
    if query_params.get('AccessionNumber'):
        queryset = _apply_wildcard_filter(queryset, 'accession_number', query_params['AccessionNumber'])
    
    # Limit results
    queryset = queryset[:max_results]
    
    # Convert to DICOM datasets
    matches = []
    for study in queryset:
        ds = Dataset()
        
        # Set QueryRetrieveLevel - CRITICAL for retrieve operations
        ds.QueryRetrieveLevel = 'STUDY'
        
        # Patient info
        if study.patient.patient_id:
            ds.PatientID = study.patient.patient_id
        else:
            ds.PatientID = ''  # Include empty value if not present
            
        if study.patient.patient_name:
            ds.PatientName = study.patient.patient_name
        else:
            ds.PatientName = ''  # Include empty value if not present
            
        if study.patient.patient_date_of_birth:
            ds.PatientBirthDate = study.patient.patient_date_of_birth.strftime('%Y%m%d')
        else:
            ds.PatientBirthDate = ''  # Include empty value if not present
            
        if study.patient.patient_gender:
            ds.PatientSex = study.patient.patient_gender
        else:
            ds.PatientSex = ''  # Include empty value if not present
            
        # Study info - REQUIRED fields for retrieve operations
        if study.study_instance_uid:
            ds.StudyInstanceUID = study.study_instance_uid
        else:
            ds.StudyInstanceUID = ''  # Include empty value if not present
            
        if study.study_date:
            ds.StudyDate = study.study_date.strftime('%Y%m%d')
        else:
            ds.StudyDate = ''  # Include empty value if not present
            
        # StudyTime - include actual value or empty if not available
        if study.study_time:
            ds.StudyTime = study.study_time.strftime('%H%M%S')
        else:
            ds.StudyTime = ''
        
        if study.study_description:
            ds.StudyDescription = study.study_description
        else:
            ds.StudyDescription = ''  # Include empty value if not present
            
        # AccessionNumber - REQUIRED for many PACS systems
        if study.accession_number:
            ds.AccessionNumber = study.accession_number
        else:
            ds.AccessionNumber = ''
        
        # StudyID - REQUIRED for many PACS systems
        if study.study_id:
            ds.StudyID = study.study_id
        else:
            ds.StudyID = ''
        
        if study.study_modality:
            ds.ModalitiesInStudy = study.study_modality
        else:
            ds.ModalitiesInStudy = ''
            
        # NumberOfStudyRelatedInstances - calculate from series
        try:
            total_instances = DICOMSeries.objects.filter(
                study=study
            ).aggregate(total=Sum('instance_count'))['total']
            
            if total_instances:
                ds.NumberOfStudyRelatedInstances = str(total_instances)
            else:
                ds.NumberOfStudyRelatedInstances = '0'
        except Exception as e:
            logger.warning(f"Could not calculate instance count for study {study.study_instance_uid}: {e}")
            ds.NumberOfStudyRelatedInstances = '0'
            
        matches.append(ds)
    
    return matches


def _query_images(query_params, max_results=10000):
    """
    Query DICOMInstance model and return matching DICOM datasets at IMAGE level.
    """
    from dicom_handler.models import DICOMInstance
    
    queryset = DICOMInstance.objects.select_related('series_instance_uid__study__patient').all()
    
    # Patient level filters
    if query_params.get('PatientID'):
        queryset = _apply_wildcard_filter(queryset, 'series_instance_uid__study__patient__patient_id', query_params['PatientID'])
    
    if query_params.get('PatientName'):
        queryset = _apply_wildcard_filter(queryset, 'series_instance_uid__study__patient__patient_name', str(query_params['PatientName']))
    
    # Study level filters
    if query_params.get('StudyInstanceUID'):
        queryset = _apply_wildcard_filter(queryset, 'series_instance_uid__study__study_instance_uid', query_params['StudyInstanceUID'])
    
    if query_params.get('StudyDate'):
        queryset = _apply_date_filter(queryset, 'series_instance_uid__study__study_date', query_params['StudyDate'])
    
    if query_params.get('StudyDescription'):
        queryset = _apply_wildcard_filter(queryset, 'series_instance_uid__study__study_description', query_params['StudyDescription'])
    
    # Series level filters
    if query_params.get('SeriesInstanceUID'):
        queryset = _apply_wildcard_filter(queryset, 'series_instance_uid__series_instance_uid', query_params['SeriesInstanceUID'])
    
    if query_params.get('SeriesDescription'):
        queryset = _apply_wildcard_filter(queryset, 'series_instance_uid__series_description', query_params['SeriesDescription'])
    
    # Instance (IMAGE) level filters
    if query_params.get('SOPInstanceUID'):
        queryset = _apply_wildcard_filter(queryset, 'sop_instance_uid', query_params['SOPInstanceUID'])
    
    # Limit results
    queryset = queryset[:max_results]
    
    # Convert to DICOM datasets
    matches = []
    for instance in queryset:
        ds = Dataset()
        
        # Set QueryRetrieveLevel - CRITICAL for retrieve operations
        ds.QueryRetrieveLevel = 'IMAGE'
        
        # Patient info
        if instance.series_instance_uid.study.patient.patient_id:
            ds.PatientID = instance.series_instance_uid.study.patient.patient_id
        else:
            ds.PatientID = ''
            
        if instance.series_instance_uid.study.patient.patient_name:
            ds.PatientName = instance.series_instance_uid.study.patient.patient_name
        else:
            ds.PatientName = ''
            
        if instance.series_instance_uid.study.patient.patient_date_of_birth:
            ds.PatientBirthDate = instance.series_instance_uid.study.patient.patient_date_of_birth.strftime('%Y%m%d')
        else:
            ds.PatientBirthDate = ''
            
        if instance.series_instance_uid.study.patient.patient_gender:
            ds.PatientSex = instance.series_instance_uid.study.patient.patient_gender
        else:
            ds.PatientSex = ''
            
        # Study info - REQUIRED for retrieve operations
        if instance.series_instance_uid.study.study_instance_uid:
            ds.StudyInstanceUID = instance.series_instance_uid.study.study_instance_uid
        else:
            ds.StudyInstanceUID = ''
            
        if instance.series_instance_uid.study.study_date:
            ds.StudyDate = instance.series_instance_uid.study.study_date.strftime('%Y%m%d')
        else:
            ds.StudyDate = ''
            
        if instance.series_instance_uid.study.study_time:
            ds.StudyTime = instance.series_instance_uid.study.study_time.strftime('%H%M%S')
        else:
            ds.StudyTime = ''
        
        if instance.series_instance_uid.study.study_description:
            ds.StudyDescription = instance.series_instance_uid.study.study_description
        else:
            ds.StudyDescription = ''
            
        if instance.series_instance_uid.study.accession_number:
            ds.AccessionNumber = instance.series_instance_uid.study.accession_number
        else:
            ds.AccessionNumber = ''
            
        if instance.series_instance_uid.study.study_id:
            ds.StudyID = instance.series_instance_uid.study.study_id
        else:
            ds.StudyID = ''
        
        # Series info - REQUIRED for retrieve operations
        if instance.series_instance_uid.series_instance_uid:
            ds.SeriesInstanceUID = instance.series_instance_uid.series_instance_uid
        else:
            ds.SeriesInstanceUID = ''
            
        if instance.series_instance_uid.series_date:
            ds.SeriesDate = instance.series_instance_uid.series_date.strftime('%Y%m%d')
        else:
            ds.SeriesDate = ''
            
        ds.SeriesTime = ''
        
        if instance.series_instance_uid.series_description:
            ds.SeriesDescription = instance.series_instance_uid.series_description
        else:
            ds.SeriesDescription = ''
        
        ds.SeriesNumber = ''
        ds.Modality = ''
        
        # Instance (IMAGE) info - REQUIRED for IMAGE level
        if instance.sop_instance_uid:
            ds.SOPInstanceUID = instance.sop_instance_uid
        else:
            ds.SOPInstanceUID = ''
        
        # Read actual DICOM file to get SOPClassUID and InstanceNumber if available
        if instance.instance_path and os.path.exists(instance.instance_path):
            try:
                file_ds = dcmread(instance.instance_path, stop_before_pixels=True)
                if hasattr(file_ds, 'SOPClassUID'):
                    ds.SOPClassUID = file_ds.SOPClassUID
                if hasattr(file_ds, 'InstanceNumber'):
                    ds.InstanceNumber = str(file_ds.InstanceNumber)
            except Exception as e:
                logger.warning(f"Could not read DICOM file for instance {instance.sop_instance_uid}: {e}")
        
        matches.append(ds)
    
    return matches


def _query_series(query_params, max_results=10000):
    """
    Query DICOMSeries model and return matching DICOM datasets.
    """
    from dicom_handler.models import DICOMSeries
    
    queryset = DICOMSeries.objects.select_related('study__patient').all()
    
    # Patient level filters
    if query_params.get('PatientID'):
        queryset = _apply_wildcard_filter(queryset, 'study__patient__patient_id', query_params['PatientID'])
    
    if query_params.get('PatientName'):
        queryset = _apply_wildcard_filter(queryset, 'study__patient__patient_name', str(query_params['PatientName']))
    
    # Study level filters
    if query_params.get('StudyInstanceUID'):
        queryset = _apply_wildcard_filter(queryset, 'study__study_instance_uid', query_params['StudyInstanceUID'])
    
    if query_params.get('StudyDate'):
        queryset = _apply_date_filter(queryset, 'study__study_date', query_params['StudyDate'])
    
    if query_params.get('StudyDescription'):
        queryset = _apply_wildcard_filter(queryset, 'study__study_description', query_params['StudyDescription'])
    
    # Series level filters
    if query_params.get('SeriesInstanceUID'):
        queryset = _apply_wildcard_filter(queryset, 'series_instance_uid', query_params['SeriesInstanceUID'])
    
    if query_params.get('SeriesDescription'):
        queryset = _apply_wildcard_filter(queryset, 'series_description', query_params['SeriesDescription'])
    
    # Limit results
    queryset = queryset[:max_results]
    
    # Convert to DICOM datasets
    matches = []
    for series in queryset:
        ds = Dataset()
        
        # Set QueryRetrieveLevel - CRITICAL for retrieve operations
        ds.QueryRetrieveLevel = 'SERIES'
        
        # Patient info
        if series.study.patient.patient_id:
            ds.PatientID = series.study.patient.patient_id
        else:
            ds.PatientID = ''
            
        if series.study.patient.patient_name:
            ds.PatientName = series.study.patient.patient_name
        else:
            ds.PatientName = ''
            
        if series.study.patient.patient_date_of_birth:
            ds.PatientBirthDate = series.study.patient.patient_date_of_birth.strftime('%Y%m%d')
        else:
            ds.PatientBirthDate = ''
            
        if series.study.patient.patient_gender:
            ds.PatientSex = series.study.patient.patient_gender
        else:
            ds.PatientSex = ''
            
        # Study info - REQUIRED for retrieve operations
        if series.study.study_instance_uid:
            ds.StudyInstanceUID = series.study.study_instance_uid
        else:
            ds.StudyInstanceUID = ''
            
        if series.study.study_date:
            ds.StudyDate = series.study.study_date.strftime('%Y%m%d')
        else:
            ds.StudyDate = ''
            
        if series.study.study_time:
            ds.StudyTime = series.study.study_time.strftime('%H%M%S')
        else:
            ds.StudyTime = ''
        
        if series.study.study_description:
            ds.StudyDescription = series.study.study_description
        else:
            ds.StudyDescription = ''
            
        if series.study.accession_number:
            ds.AccessionNumber = series.study.accession_number
        else:
            ds.AccessionNumber = ''
            
        if series.study.study_id:
            ds.StudyID = series.study.study_id
        else:
            ds.StudyID = ''
        
        # Series info - REQUIRED for retrieve operations
        if series.series_instance_uid:
            ds.SeriesInstanceUID = series.series_instance_uid
        else:
            ds.SeriesInstanceUID = ''
            
        if series.series_date:
            ds.SeriesDate = series.series_date.strftime('%Y%m%d')
        else:
            ds.SeriesDate = ''
            
        ds.SeriesTime = ''
        
        if series.series_description:
            ds.SeriesDescription = series.series_description
        else:
            ds.SeriesDescription = ''
            
        ds.SeriesNumber = ''
        ds.Modality = ''
        
        if series.instance_count:
            ds.NumberOfSeriesRelatedInstances = str(series.instance_count)
        else:
            ds.NumberOfSeriesRelatedInstances = '0'
            
        matches.append(ds)
    
    return matches


def _apply_wildcard_filter(queryset, field_name, pattern):
    """
    Apply wildcard filter to Django queryset.
    Converts DICOM wildcards (* and ?) to Django ORM filters.
    """
    import re
    
    pattern = str(pattern)
    
    # If no wildcards, use exact match (case-insensitive)
    if '*' not in pattern and '?' not in pattern:
        return queryset.filter(**{f'{field_name}__iexact': pattern})
    
    # Convert DICOM wildcards to Django regex
    regex_pattern = re.escape(pattern)
    regex_pattern = regex_pattern.replace(r'\*', '.*')  # * matches any sequence
    regex_pattern = regex_pattern.replace(r'\?', '.')   # ? matches single char
    regex_pattern = f'^{regex_pattern}$'
    
    return queryset.filter(**{f'{field_name}__iregex': regex_pattern})


def _apply_date_filter(queryset, field_name, date_value):
    """
    Apply date filter to Django queryset.
    Supports single dates, wildcards, and ranges (YYYYMMDD-YYYYMMDD).
    """
    from datetime import datetime
    
    date_str = str(date_value)
    
    # Check for range query
    if '-' in date_str:
        parts = date_str.split('-')
        if len(parts) == 2:
            start_str = parts[0] if parts[0] else '00000000'
            end_str = parts[1] if parts[1] else '99999999'
            
            try:
                start_date = datetime.strptime(start_str, '%Y%m%d').date()
                end_date = datetime.strptime(end_str, '%Y%m%d').date()
                return queryset.filter(**{
                    f'{field_name}__gte': start_date,
                    f'{field_name}__lte': end_date
                })
            except ValueError:
                logger.warning(f"Invalid date range: {date_str}")
                return queryset
    
    # Single date or wildcard
    if '*' in date_str or '?' in date_str:
        return _apply_wildcard_filter(queryset, field_name, date_str)
    
    # Exact date
    try:
        date_obj = datetime.strptime(date_str, '%Y%m%d').date()
        return queryset.filter(**{field_name: date_obj})
    except ValueError:
        logger.warning(f"Invalid date format: {date_str}")
        return queryset


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
