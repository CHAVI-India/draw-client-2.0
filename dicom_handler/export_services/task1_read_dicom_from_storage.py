"""
Task 1: Read DICOM Data from Storage (Series-Aware Implementation)

OVERVIEW:
This task reads DICOM data from the folder configured in SystemConfiguration model.
All DICOM files in folder and subfolders are processed using a series-aware approach.

IMPLEMENTATION STRATEGY (OPTIMIZED):
- Single-pass filesystem walk with series-aware grouping
- Each file read ONLY ONCE with full metadata extraction
- Files grouped by Series Instance UID during processing
- Series finalized when directory changes or processing completes
- Bulk database insert per completed series (not per file)
- Prevents race conditions with finalized_series_uids tracking

FILE FILTERING RULES:
1. Modality check: Only CT/MR/PT modalities are processed (others discarded)
2. Skip files created/modified in past 10 minutes (likely still being written)
3. Skip files created before data_pull_start_datetime (if configured)
4. Skip files already in database (check SOP Instance UID)

SERIES COMPLETION DETECTION:
- Directory change: When moving to new directory, finalize series from previous directory
- End of walk: Finalize all remaining series after filesystem traversal completes
- Prevents re-adding: finalized_series_uids set prevents double-finalization

DATABASE MODELS UPDATED:
- Patient: Patient demographics
- DICOMStudy: Study-level metadata
- DICOMSeries: Series-level metadata with instance_count and series_files_fully_read flag
- DICOMInstance: Individual file paths and SOP Instance UIDs

SERIES COMPLETION FLAGS:
- series_files_fully_read: Set to True when all files for series are loaded
- series_files_fully_read_datetime: Timestamp when series was marked complete
- instance_count: Total number of instances in the series

OUTPUT FOR NEXT TASK:
Returns list of complete series with:
- series_instance_uid: Unique identifier for the series
- series_root_path: Directory containing the series files
- first_instance_path: Path to first DICOM file for metadata reading
- instance_count: Total number of instances in the series

LOGGING:
All operations logged with sensitive data (UIDs, patient info) masked for privacy.

CRITICAL BUG FIXES IMPLEMENTED:
1. Double-finalization prevention: finalized_series_uids tracking prevents series from being
   finalized twice (once by directory change, once at end of walk)
2. Series isolation: Each series processed separately in bulk_create to prevent cross-contamination
3. Accurate instance counts: Counts set by mark_series_as_fully_loaded() after all files processed
"""

import os
import logging
import pydicom
from datetime import datetime, timedelta
from django.utils import timezone
from django.db import transaction
import json
from ..models import (
    SystemConfiguration, Patient, DICOMStudy, DICOMSeries, 
    DICOMInstance, ProcessingStatus
)

# Configure logging with masking for sensitive information
logger = logging.getLogger(__name__)

def mask_sensitive_data(data, field_name=""):
    """
    Mask sensitive DICOM data for logging purposes
    """
    if not data:
        return "***EMPTY***"
    
    # Mask patient identifiable information
    sensitive_fields = [
        'patient_name', 'patient_id', 'patient_birth_date',
        'PatientName', 'PatientID', 'PatientBirthDate',
        'institution_name', 'InstitutionName'
    ]
    
    if any(field in field_name.lower() for field in ['name', 'id', 'birth']):
        return f"***{field_name.upper()}_MASKED***"
    
    # For UIDs, show only first and last 4 characters
    if 'uid' in field_name.lower() and len(str(data)) > 8:
        return f"{str(data)[:4]}...{str(data)[-4:]}"
    
    return str(data)

def process_single_file(file_info):
    """
    Process a single DICOM file - designed for threading
    Returns: Dictionary with file processing results
    """
    file_path, series_root_path, date_filter, current_time, ten_minutes_ago = file_info
    
    try:
        # Check file modification time conditions
        file_stat = os.stat(file_path)
        file_mtime = datetime.fromtimestamp(file_stat.st_mtime, tz=timezone.get_current_timezone())
        
        # Skip if file was modified in the past 10 minutes
        if file_mtime > ten_minutes_ago:
            return {"status": "skipped", "reason": "recently_modified", "file_path": file_path}
        
        # Skip if file was created/modified before date_pull_start_datetime
        if date_filter and date_filter <= current_time and file_mtime < date_filter:
            return {"status": "skipped", "reason": "before_date_filter", "file_path": file_path}
        
        # Try to read DICOM file
        try:
            # Read DICOM without format validation to ensure all files are processed
            dicom_data = pydicom.dcmread(file_path, force=True)
            
            # Check if file has required modality (CT/MR/PT)
            modality = getattr(dicom_data, 'Modality', None)
            if modality not in ['CT', 'MR', 'PT']:
                return {"status": "skipped", "reason": "unsupported_modality", "modality": modality, "file_path": file_path}
            
            # Check if SOP Instance UID exists
            sop_instance_uid = getattr(dicom_data, 'SOPInstanceUID', None)
            if not sop_instance_uid:
                return {"status": "error", "reason": "missing_sop_uid", "file_path": file_path}
            
            # Extract DICOM metadata
            dicom_metadata = {
                'patient_id': getattr(dicom_data, 'PatientID', ''),
                'patient_name': str(getattr(dicom_data, 'PatientName', '')),
                'patient_gender': getattr(dicom_data, 'PatientSex', ''),
                'patient_birth_date': getattr(dicom_data, 'PatientBirthDate', None),
                'study_instance_uid': getattr(dicom_data, 'StudyInstanceUID', ''),
                'study_date': getattr(dicom_data, 'StudyDate', None),
                'study_description': getattr(dicom_data, 'StudyDescription', ''),
                'study_protocol': getattr(dicom_data, 'ProtocolName', ''),
                'series_description': getattr(dicom_data, 'SeriesDescription', ''),
                'modality': modality,
                'series_instance_uid': getattr(dicom_data, 'SeriesInstanceUID', ''),
                'series_date': getattr(dicom_data, 'SeriesDate', None),
                'frame_of_reference_uid': getattr(dicom_data, 'FrameOfReferenceUID', ''),
                'sop_instance_uid': sop_instance_uid,
                'file_path': file_path,
                'series_root_path': series_root_path
            }
            return {"status": "success", "metadata": dicom_metadata}
            
        except Exception as e:
            return {"status": "error", "reason": "dicom_read_error", "error": str(e), "file_path": file_path}
            
    except Exception as e:
        return {"status": "error", "reason": "file_access_error", "error": str(e), "file_path": file_path}

def bulk_create_database_records(processed_files):
    """
    Bulk create database records from processed DICOM files
    """
    patients_to_create = {}
    studies_to_create = {}
    series_to_create = {}
    instances_to_create = []
    
    # Group by patient, study, series
    for file_result in processed_files:
        if file_result['status'] != 'success':
            continue
            
        metadata = file_result['metadata']
        
        # Convert dates
        patient_birth_date = None
        if metadata['patient_birth_date']:
            try:
                patient_birth_date = datetime.strptime(str(metadata['patient_birth_date']), '%Y%m%d').date()
            except:
                pass
        
        study_date = None
        if metadata['study_date']:
            try:
                study_date = datetime.strptime(str(metadata['study_date']), '%Y%m%d').date()
            except:
                pass
        
        series_date = None
        if metadata['series_date']:
            try:
                series_date = datetime.strptime(str(metadata['series_date']), '%Y%m%d').date()
            except:
                pass
        
        # Group patients
        patient_key = metadata['patient_id']
        if patient_key not in patients_to_create:
            patients_to_create[patient_key] = {
                'patient_id': metadata['patient_id'],
                'patient_name': metadata['patient_name'],
                'patient_gender': metadata['patient_gender'],
                'patient_date_of_birth': patient_birth_date
            }
        
        # Group studies
        study_key = (patient_key, metadata['study_instance_uid'])
        if study_key not in studies_to_create:
            studies_to_create[study_key] = {
                'patient_id': patient_key,
                'study_instance_uid': metadata['study_instance_uid'],
                'study_date': study_date,
                'study_description': metadata['study_description'],
                'study_protocol': metadata['study_protocol'],
                'study_modality': metadata['modality']
            }
        
        # Group series
        series_key = (study_key, metadata['series_instance_uid'])
        if series_key not in series_to_create:
            series_to_create[series_key] = {
                'study_key': study_key,
                'series_instance_uid': metadata['series_instance_uid'],
                'series_root_path': metadata['series_root_path'],
                'frame_of_reference_uid': metadata['frame_of_reference_uid'],
                'series_description': metadata['series_description'],
                'series_date': series_date,
                'instance_count': 0
            }
        # If a description is found later, update it
        elif not series_to_create[series_key]['series_description'] and metadata['series_description']:
            series_to_create[series_key]['series_description'] = metadata['series_description']
        
        # Count instances per series
        series_to_create[series_key]['instance_count'] += 1
        
        # Collect instances
        instances_to_create.append({
            'series_key': series_key,
            'sop_instance_uid': metadata['sop_instance_uid'],
            'instance_path': metadata['file_path']
        })
    
    # Bulk create in database with transactions
    created_series_data = {}
    
    with transaction.atomic():
        # Create patients
        patient_objects = {}
        for patient_data in patients_to_create.values():
            patient, created = Patient.objects.get_or_create(
                patient_id=patient_data['patient_id'],
                defaults={
                    'patient_name': patient_data['patient_name'],
                    'patient_gender': patient_data['patient_gender'],
                    'patient_date_of_birth': patient_data['patient_date_of_birth']
                }
            )
            patient_objects[patient_data['patient_id']] = patient
        
        # Create studies
        study_objects = {}
        for study_key, study_data in studies_to_create.items():
            patient = patient_objects[study_data['patient_id']]
            study, created = DICOMStudy.objects.get_or_create(
                patient=patient,
                study_instance_uid=study_data['study_instance_uid'],
                defaults={
                    'study_date': study_data['study_date'],
                    'study_description': study_data['study_description'],
                    'study_protocol': study_data['study_protocol'],
                    'study_modality': study_data['study_modality']
                }
            )
            study_objects[study_key] = study
        
        # Create series
        series_objects = {}
        for series_key, series_data in series_to_create.items():
            study = study_objects[series_data['study_key']]
            series, created = DICOMSeries.objects.get_or_create(
                study=study,
                series_instance_uid=series_data['series_instance_uid'],
                defaults={
                    'series_root_path': series_data['series_root_path'],
                    'frame_of_reference_uid': series_data['frame_of_reference_uid'],
                    'series_date': series_data['series_date'],
                    'instance_count': series_data['instance_count'],
                    'series_description': series_data['series_description'],
                    'series_processsing_status': ProcessingStatus.UNPROCESSED
                }
            )
            if not created and series.instance_count != series_data['instance_count']:
                    series.instance_count = series_data['instance_count']
                    series.series_description = series_data['series_description']
                    series.save()
            
            series_objects[series_key] = series
            
            # Track for next task
            if series_data['series_instance_uid'] not in created_series_data:
                created_series_data[series_data['series_instance_uid']] = {
                    'first_instance_path': None,
                    'series_root_path': series_data['series_root_path'],
                    'instance_count': series_data['instance_count']
                }
        
        # Create instances
        instances_to_bulk_create = []
        for instance_data in instances_to_create:
            series = series_objects[instance_data['series_key']]
            
            # Check if instance already exists
            if not DICOMInstance.objects.filter(sop_instance_uid=instance_data['sop_instance_uid']).exists():
                instances_to_bulk_create.append(
                    DICOMInstance(
                        series_instance_uid=series,
                        sop_instance_uid=instance_data['sop_instance_uid'],
                        instance_path=instance_data['instance_path']
                    )
                )
                
                # Set first instance path for series
                series_uid = series.series_instance_uid
                if created_series_data[series_uid]['first_instance_path'] is None:
                    created_series_data[series_uid]['first_instance_path'] = instance_data['instance_path']
        
        # Bulk create instances
        if instances_to_bulk_create:
            DICOMInstance.objects.bulk_create(instances_to_bulk_create, batch_size=1000)
    
    return created_series_data

def process_dicom_file(dicom_data, file_path, series_root_path):
    """
    Process individual DICOM file and save to database
    """
    try:
        with transaction.atomic():
            # Extract patient information
            patient_id = getattr(dicom_data, 'PatientID', '')
            patient_name = getattr(dicom_data, 'PatientName', '')
            patient_gender = getattr(dicom_data, 'PatientSex', '')
            patient_birth_date = getattr(dicom_data, 'PatientBirthDate', None)
            
            # Convert patient birth date
            if patient_birth_date:
                try:
                    patient_birth_date = datetime.strptime(str(patient_birth_date), '%Y%m%d').date()
                except:
                    patient_birth_date = None
            
            # Get or create patient
            patient, created = Patient.objects.get_or_create(
                patient_id=patient_id,
                defaults={
                    'patient_name': str(patient_name),
                    'patient_gender': patient_gender,
                    'patient_date_of_birth': patient_birth_date
                }
            )
            
            if created:
                logger.info(f"Created new patient: {mask_sensitive_data(patient_id, 'patient_id')}")
            
            # Extract study information
            study_instance_uid = getattr(dicom_data, 'StudyInstanceUID', '')
            study_date = getattr(dicom_data, 'StudyDate', None)
            study_description = getattr(dicom_data, 'StudyDescription', '')
            study_protocol = getattr(dicom_data, 'ProtocolName', '')
            series_description = getattr(dicom_data, 'SeriesDescription', '')
            modality = getattr(dicom_data, 'Modality', '')
            
            # Convert study date
            if study_date:
                try:
                    study_date = datetime.strptime(str(study_date), '%Y%m%d').date()
                except:
                    study_date = None
            
            # Get or create study
            study, created = DICOMStudy.objects.get_or_create(
                patient=patient,
                study_instance_uid=study_instance_uid,
                defaults={
                    'study_date': study_date,
                    'study_description': study_description,
                    'study_protocol': study_protocol,
                    'study_modality': modality
                }
            )
            
            if created:
                logger.info(f"Created new study: {mask_sensitive_data(study_instance_uid, 'study_instance_uid')}")
            
            # Extract series information
            series_instance_uid = getattr(dicom_data, 'SeriesInstanceUID', '')
            series_date = getattr(dicom_data, 'SeriesDate', None)
            frame_of_reference_uid = getattr(dicom_data, 'FrameOfReferenceUID', '')
            
            # Convert series date
            if series_date:
                try:
                    series_date = datetime.strptime(str(series_date), '%Y%m%d').date()
                except:
                    series_date = None
            
            # Get or create series
            series, created = DICOMSeries.objects.get_or_create(
                study=study,
                series_instance_uid=series_instance_uid,
                defaults={
                    'series_root_path': series_root_path,
                    'frame_of_reference_uid': frame_of_reference_uid,
                    'series_description': series_description,
                    'series_date': series_date,
                    'series_processsing_status': ProcessingStatus.UNPROCESSED
                }
            )
            
            if created:
                logger.info(f"Created new series: {mask_sensitive_data(series_instance_uid, 'series_uid')}")
            else:
                # If series already exists, check if description needs updating
                if series.series_description != series_description:
                    series.series_description = series_description
                    series.save()
            
            # Extract instance information
            sop_instance_uid = getattr(dicom_data, 'SOPInstanceUID', '')
            
            # Create instance
            instance = DICOMInstance.objects.create(
                series_instance_uid=series,
                sop_instance_uid=sop_instance_uid,
                instance_path=file_path
            )
            
            logger.debug(f"Created new instance: {mask_sensitive_data(sop_instance_uid, 'sop_instance_uid')}")
            
            return {
                'status': 'success',
                'series_instance_uid': series_instance_uid,
                'instance_path': file_path,
                'series_root_path': series_root_path
            }
            
    except Exception as e:
        logger.error(f"Error processing DICOM file {mask_sensitive_data(file_path, 'file_path')}: {str(e)}")
        return {'status': 'error', 'message': str(e)}

def process_single_file_and_group(file_info, series_in_progress, existing_sop_uids, finalized_series_uids):
    """
    Process a single file and group by series UID
    Returns: Statistics dict with processed/skipped/error counts
    """
    stats = {'processed': 0, 'skipped': 0, 'errors': 0}
    
    try:
        result = process_single_file(file_info)
        
        # Count by status
        if result['status'] == 'success':
            stats['processed'] += 1
        elif result['status'] == 'skipped':
            stats['skipped'] += 1
        else:
            stats['errors'] += 1
            return stats
        
        # Only process successful results
        if result['status'] != 'success':
            return stats
        
        metadata = result['metadata']
        series_uid = metadata['series_instance_uid']
        sop_uid = metadata['sop_instance_uid']
        
        # Skip if already in database
        if sop_uid in existing_sop_uids:
            stats['skipped'] += 1
            stats['processed'] -= 1
            return stats
        
        existing_sop_uids.add(sop_uid)
        
        # ⭐ Skip if series already finalized
        if series_uid in finalized_series_uids:
            logger.warning(f"Skipping file from already finalized series: {mask_sensitive_data(series_uid, 'series_uid')}")
            return stats
        
        # ⭐ Group by series (single read, immediate grouping)
        if series_uid not in series_in_progress:
            series_in_progress[series_uid] = {
                'files': [],
                'last_seen': timezone.now(),
                'series_root_path': metadata['series_root_path'],
                'first_file_metadata': metadata
            }
        
        # Add file to series group
        series_in_progress[series_uid]['files'].append(result)
        series_in_progress[series_uid]['last_seen'] = timezone.now()
        
    except Exception as e:
        stats['errors'] += 1
        logger.error(f"Error processing file: {e}")
    
    return stats

def check_and_finalize_series_by_directory(series_in_progress, series_completed, 
                                            finalized_series_uids, previous_directory, current_time):
    """
    When leaving a directory, finalize series from that directory
    Assumption: All files for a series are typically in the same directory
    """
    series_to_finalize = []
    
    for series_uid, series_data in series_in_progress.items():
        series_root = series_data['series_root_path']
        
        # If series root matches the directory we just left, finalize it
        if series_root == previous_directory:
            series_to_finalize.append(series_uid)
    
    # Move completed series to completed list
    for series_uid in series_to_finalize:
        series_data = series_in_progress.pop(series_uid)
        file_count = len(series_data['files'])
        
        # ⭐ Mark as finalized to prevent re-adding
        finalized_series_uids.add(series_uid)
        
        logger.info(f"✅ Series complete (directory change): {mask_sensitive_data(series_uid, 'series_uid')} "
                   f"with {file_count} files")
        
        series_completed.append({
            'series_uid': series_uid,
            'files': series_data['files'],
            'file_count': file_count,
            'series_root_path': series_data['series_root_path']
        })

def finalize_all_remaining_series(series_in_progress, series_completed, finalized_series_uids, current_time):
    """
    Finalize all remaining series at end of processing
    """
    for series_uid, series_data in list(series_in_progress.items()):
        file_count = len(series_data['files'])
        
        # ⭐ Mark as finalized to prevent re-adding
        finalized_series_uids.add(series_uid)
        
        logger.info(f"✅ Series complete (end of walk): {mask_sensitive_data(series_uid, 'series_uid')} "
                   f"with {file_count} files")
        
        series_completed.append({
            'series_uid': series_uid,
            'files': series_data['files'],
            'file_count': file_count,
            'series_root_path': series_data['series_root_path']
        })
    
    # Clear in-progress dict
    series_in_progress.clear()

def flush_completed_series_to_db(series_completed):
    """
    Write completed series to database in bulk
    Marks each series as fully loaded
    ⭐ FIXED: Process each series separately to avoid cross-contamination
    """
    if not series_completed:
        return
    
    logger.info(f"Flushing {len(series_completed)} completed series to database")
    
    total_files = sum(len(s['files']) for s in series_completed)
    
    # ⭐ Process each series SEPARATELY to avoid mixing files between series
    try:
        for series_data in series_completed:
            series_uid = series_data['series_uid']
            series_files = series_data['files']
            file_count = series_data['file_count']
            
            # Create database records for THIS series only
            created_series_data = bulk_create_database_records(series_files)
            
            # Mark THIS series as fully loaded with correct count
            mark_series_as_fully_loaded(series_uid, file_count)
            
            logger.debug(f"✅ Flushed series {mask_sensitive_data(series_uid, 'series_uid')} with {file_count} files")
        
        logger.info(f"✅ Successfully flushed {len(series_completed)} series "
                   f"({total_files} files) to database")
        
    except Exception as e:
        logger.error(f"Error flushing series to database: {e}")
        import traceback
        traceback.print_exc()
        raise

def mark_series_as_fully_loaded(series_uid, file_count):
    """
    Mark series as fully loaded and ready for processing
    Sets series_files_fully_read flag to prevent Task 2 from picking up incomplete series
    
    NOTE: instance_count is already correctly set by bulk_create_database_records()
    which counts ALL instances in the series. We should NOT overwrite it here.
    """
    try:
        series = DICOMSeries.objects.get(series_instance_uid=series_uid)
        
        # ⭐ Mark as complete (DO NOT overwrite instance_count - it's already correct!)
        series.series_files_fully_read = True
        series.series_files_fully_read_datetime = timezone.now()
        series.save()
        
        # Log the ACTUAL instance count from the database, not the file_count parameter
        actual_count = series.instance_count or 0
        logger.info(f"✅ Marked series as fully loaded: {mask_sensitive_data(series_uid, 'series_uid')} "
                   f"with {actual_count} instances (file_count param was {file_count})")
        
    except DICOMSeries.DoesNotExist:
        logger.error(f"Series not found for marking complete: {mask_sensitive_data(series_uid, 'series_uid')}")
    except Exception as e:
        logger.error(f"Error marking series as complete: {e}")

def update_series_instance_counts(series_data):
    """
    Update instance counts for all processed series
    """
    try:
        for series_uid, data in series_data.items():
            try:
                series = DICOMSeries.objects.get(series_instance_uid=series_uid)
                series.instance_count = data['instance_count']
                series.save()
                logger.info(f"Updated instance count for series {mask_sensitive_data(series_uid, 'series_uid')}: {data['instance_count']}")
            except DICOMSeries.DoesNotExist:
                logger.error(f"Series not found for UID: {mask_sensitive_data(series_uid, 'series_uid')}")
    except Exception as e:
        logger.error(f"Error updating series instance counts: {str(e)}")

def get_series_for_next_task():
    """
    Get series data for the next task in the chain
    Returns list of COMPLETE series with first instance path for processing
    ⭐ Only returns series where all files have been fully loaded
    """
    try:
        unprocessed_series = DICOMSeries.objects.filter(
            series_processsing_status=ProcessingStatus.UNPROCESSED,
            series_files_fully_read=True  # ⭐ NEW: Only get complete series
        ).select_related('study__patient')
        
        series_list = []
        for series in unprocessed_series:
            # Get first instance for this series
            first_instance = DICOMInstance.objects.filter(
                series_instance_uid=series
            ).first()
            
            if first_instance:
                series_list.append({
                    'series_instance_uid': series.series_instance_uid,
                    'series_root_path': series.series_root_path,
                    'first_instance_path': first_instance.instance_path,
                    'instance_count': series.instance_count or 0
                })
        
        logger.info(f"Found {len(series_list)} COMPLETE unprocessed series for next task")
        return series_list
        
    except Exception as e:
        logger.error(f"Error getting series for next task: {str(e)}")
        return []

def log_processing_summary(newly_processed_series_uids=None):
    """
    Log comprehensive summary of processed data with patient-level statistics
    Shows masked patient IDs and counts of studies, series, and instances per patient
    
    Args:
        newly_processed_series_uids: Set of series UIDs that were newly processed in this run.
                                     If None or empty, logs all data in database.
    """
    logger.info("="*80)
    logger.info("DICOM PROCESSING SUMMARY")
    logger.info("="*80)
    
    # If no new series were processed, log that and return early
    if newly_processed_series_uids is not None and len(newly_processed_series_uids) == 0:
        logger.info("No new patients/series processed in this run")
        logger.info("="*80)
        return
    
    # Get patients based on newly processed series
    if newly_processed_series_uids:
        # Get only patients with newly processed series
        patients = Patient.objects.filter(
            dicomstudy__dicomseries__series_instance_uid__in=newly_processed_series_uids
        ).distinct().order_by('patient_id')
        logger.info(f"Patients with NEW series in this run: {patients.count()}")
    else:
        # Get all patients (legacy behavior)
        patients = Patient.objects.all().order_by('patient_id')
        logger.info(f"Total Patients Processed: {patients.count()}")
    
    logger.info("")
    
    total_studies = 0
    total_series = 0
    total_instances = 0
    
    for idx, patient in enumerate(patients, 1):
        # Get studies for this patient
        if newly_processed_series_uids:
            # Only studies with newly processed series
            studies = DICOMStudy.objects.filter(
                patient=patient,
                dicomseries__series_instance_uid__in=newly_processed_series_uids
            ).distinct()
        else:
            studies = DICOMStudy.objects.filter(patient=patient)
        
        study_count = studies.count()
        
        # Get series for this patient
        if newly_processed_series_uids:
            # Only newly processed series
            series_count = DICOMSeries.objects.filter(
                study__patient=patient,
                series_instance_uid__in=newly_processed_series_uids
            ).count()
        else:
            series_count = DICOMSeries.objects.filter(study__patient=patient).count()
        
        # Get instances for this patient
        if newly_processed_series_uids:
            # Only instances from newly processed series
            instance_count = DICOMInstance.objects.filter(
                series_instance_uid__study__patient=patient,
                series_instance_uid__series_instance_uid__in=newly_processed_series_uids
            ).count()
        else:
            instance_count = DICOMInstance.objects.filter(
                series_instance_uid__study__patient=patient
            ).count()
        
        # Accumulate totals
        total_studies += study_count
        total_series += series_count
        total_instances += instance_count
        
        # Log patient details with masking
        logger.info(f"Patient {idx}:")
        logger.info(f"  Patient ID: {mask_sensitive_data(patient.patient_id, 'patient_id')}")
        logger.info(f"  Patient Name: {mask_sensitive_data(str(patient.patient_name), 'patient_name')}")
        logger.info(f"  Studies: {study_count}")
        logger.info(f"  Series: {series_count}")
        logger.info(f"  Instances: {instance_count}")
        
        # Show study details for this patient
        for study in studies:
            if newly_processed_series_uids:
                # Only count series from this run
                study_series_count = DICOMSeries.objects.filter(
                    study=study,
                    series_instance_uid__in=newly_processed_series_uids
                ).count()
                study_instance_count = DICOMInstance.objects.filter(
                    series_instance_uid__study=study,
                    series_instance_uid__series_instance_uid__in=newly_processed_series_uids
                ).count()
            else:
                study_series_count = DICOMSeries.objects.filter(study=study).count()
                study_instance_count = DICOMInstance.objects.filter(
                    series_instance_uid__study=study
                ).count()
            
            logger.info(f"    └─ Study: {mask_sensitive_data(study.study_instance_uid, 'study_uid')} "
                       f"({study.study_modality}) - {study_series_count} series, {study_instance_count} instances")
        
        logger.info("")
    
    # Overall summary
    logger.info("="*80)
    if newly_processed_series_uids:
        logger.info("TOTALS FOR THIS RUN")
    else:
        logger.info("OVERALL TOTALS")
    logger.info("="*80)
    logger.info(f"Total Patients: {patients.count()}")
    logger.info(f"Total Studies: {total_studies}")
    logger.info(f"Total Series: {total_series}")
    logger.info(f"Total Instances: {total_instances}")
    
    # Series completion status
    if newly_processed_series_uids:
        complete_series = DICOMSeries.objects.filter(
            series_instance_uid__in=newly_processed_series_uids,
            series_files_fully_read=True
        ).count()
        incomplete_series = DICOMSeries.objects.filter(
            series_instance_uid__in=newly_processed_series_uids,
            series_files_fully_read=False
        ).count()
    else:
        complete_series = DICOMSeries.objects.filter(series_files_fully_read=True).count()
        incomplete_series = DICOMSeries.objects.filter(series_files_fully_read=False).count()
    
    logger.info("")
    logger.info("SERIES COMPLETION STATUS")
    logger.info(f"  Complete series (fully_read=True): {complete_series}")
    logger.info(f"  Incomplete series (fully_read=False): {incomplete_series}")
    
    if incomplete_series > 0:
        logger.warning(f"⚠️  {incomplete_series} series are marked as incomplete!")
    else:
        logger.info("✅ All series are complete and ready for processing")
    
    logger.info("="*80)

def read_dicom_from_storage():
    """
    Main entry point - calls the optimized series-aware implementation
    """
    return read_dicom_from_storage_series_aware()

def read_dicom_from_storage_series_aware():
    """
    Optimized series-aware DICOM file reading with single-pass processing
    Groups files by series and only marks series as complete when ALL files are processed
    Returns: Dictionary containing processing results and series information for next task
    """
    logger.info("Starting DICOM file reading task (series-aware single-pass processing)")
    
    try:
        # Get system configuration
        system_config = SystemConfiguration.get_singleton()
        if not system_config or not system_config.folder_configuration:
            logger.error("System configuration not found or folder path not configured")
            return {"status": "error", "message": "Folder configuration not found"}
        
        folder_path = system_config.folder_configuration
        logger.info(f"Reading DICOM files from folder: {mask_sensitive_data(folder_path, 'folder_path')}")
        
        if not os.path.exists(folder_path):
            logger.info(f"Configured folder does not exist: {mask_sensitive_data(folder_path, 'folder_path')}")
            return {"status": "error", "message": "Configured folder does not exist"}
        
        # Get date filter if configured
        date_filter = system_config.data_pull_start_datetime
        current_time = timezone.now()
        ten_minutes_ago = current_time - timedelta(minutes=10)
        
        logger.info(f"Date filter: {date_filter}, Current time: {current_time}")
        
        # ⭐ Series-aware processing: Track series being built
        series_in_progress = {}  # {series_uid: {'files': [], 'last_seen': timestamp, 'root_path': str}}
        series_completed = []     # List of completed series ready for DB insert
        finalized_series_uids = set()  # ⭐ Track which series have been finalized to prevent re-adding
        newly_processed_series_uids = set()  # ⭐ Track series UIDs processed in THIS run for summary logging
        
        # Configuration for series completion detection
        max_series_in_memory = 50  # Flush to DB when this many series accumulated
        
        # Statistics
        total_files_discovered = 0
        
        logger.info("Phase 1: Discovering and grouping files by series (single-pass, single process)...")
        
        last_directory = None
        
        # Check for existing SOP Instance UIDs to avoid duplicates
        existing_sop_uids = set(
            DICOMInstance.objects.values_list('sop_instance_uid', flat=True)
        )
        logger.info(f"Found {len(existing_sop_uids)} existing SOP Instance UIDs in database")
        logger.info(f"Processing files sequentially (single process)")
        
        processed_files = 0
        skipped_files = 0
        error_files = 0
        
        # ⭐ Single pass through filesystem with series grouping
        for root, dirs, files in os.walk(folder_path):
            # Check if we moved to a new directory - finalize series from previous directory
            if last_directory and last_directory != root:
                check_and_finalize_series_by_directory(
                    series_in_progress, 
                    series_completed,
                    finalized_series_uids,
                    last_directory,
                    current_time
                )
            
            last_directory = root
            
            # Process files from this directory one at a time
            for file in files:
                file_path = os.path.join(root, file)
                total_files_discovered += 1
                
                # Process single file
                file_info = (file_path, root, date_filter, current_time, ten_minutes_ago)
                stats = process_single_file_and_group(
                    file_info,
                    series_in_progress,
                    existing_sop_uids,
                    finalized_series_uids
                )
                processed_files += stats['processed']
                skipped_files += stats['skipped']
                error_files += stats['errors']
                
                # Log progress every 100 files
                if total_files_discovered % 100 == 0:
                    logger.info(f"Progress: {total_files_discovered} files discovered, {processed_files} processed")
                
                # Flush completed series to database periodically
                if len(series_completed) >= max_series_in_memory:
                    logger.info(f"Flushing {len(series_completed)} completed series to database...")
                    # Track newly processed series UIDs
                    for series_data in series_completed:
                        newly_processed_series_uids.add(series_data['series_uid'])
                    flush_completed_series_to_db(series_completed)
                    series_completed = []
        
        # Finalize all remaining series (end of directory walk)
        logger.info(f"Finalizing {len(series_in_progress)} remaining series...")
        finalize_all_remaining_series(series_in_progress, series_completed, finalized_series_uids, current_time)
        
        # Final flush to database
        if series_completed:
            logger.info(f"Final flush: {len(series_completed)} completed series to database")
            # Track newly processed series UIDs
            for series_data in series_completed:
                newly_processed_series_uids.add(series_data['series_uid'])
            flush_completed_series_to_db(series_completed)
        
        logger.info(f"DICOM reading completed. Files discovered: {total_files_discovered}, Processed: {processed_files}, Skipped: {skipped_files}, Errors: {error_files}")
        logger.info(f"Newly processed series in this run: {len(newly_processed_series_uids)}")
        
        # Get final series data for next task
        series_data = get_series_for_next_task()
        
        # ⭐ Log comprehensive processing summary with ONLY newly processed series
        log_processing_summary(newly_processed_series_uids)

        return {
            "status": "success",
            "processed_files": processed_files,
            "skipped_files": skipped_files,
            "error_files": error_files,
            "series_data": series_data
        }
        
    except Exception as e:
        logger.error(f"Critical error in DICOM reading task: {str(e)}")
        return {"status": "error", "message": str(e)}

