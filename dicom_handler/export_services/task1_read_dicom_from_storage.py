# Task 1: Read DICOM Data (code to be written in task1_read_dicom_from_storage.py)
# This task will read the DICOM data from the folder configured in SystemConfiguration model.
# It has to be enusured that all DICOM files in folder and subfolders have to be read. 
# Pydicom will be used to read DICOM metadata file by file. To ensure that all files are read we will ensure that file format check is not done at this stage.
# Before starting to read the file, the code will check if the file is having modality - CT / MR / PT - other modalities will be discarded:
# 1. Created or modified in the past 10 minutes - if so skip it. 
# 2. Created or modified before the date_pull_start_datetime field if available. If this date is not available or not specified or specified in the future then skip this conditon.
# 3. Check if the file data is already in the database (check SOP instance UID of the file)
# If all of the above conditions pass then the DICOM data will be read and saved in the database. 
# The models updated will be - Patient, DICOMStudy, DICOMSeries, DICOMInstance
# The series_root path will be the folder in which the file exists after excluding the file name. That is the folder path should be saved not the full file path. 
# The full file path should be saved in instance_path field for each file (each file will be a separate instance in the DICOMInstance table)
# The processing_status field of the DICOMSeries model will be set to UNPROCESSED
# After all files have been read, the total number of instance files for each series will be calculated and updated in the database.
# Pass the first DICOMInstance of the series to the next task including the instance_path as the metadata will be read from this along with the total number of instance files for the series
# Ensure logging of all operations while masking sensitive information.

import os
import logging
import pydicom
from datetime import datetime, timedelta
from django.utils import timezone
from django.db import transaction
from concurrent.futures import ThreadPoolExecutor, as_completed
from multiprocessing import cpu_count
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
    Returns list of series with first instance path for processing
    """
    try:
        unprocessed_series = DICOMSeries.objects.filter(
            series_processsing_status=ProcessingStatus.UNPROCESSED
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
        
        logger.info(f"Found {len(series_list)} unprocessed series for next task")
        return series_list
        
    except Exception as e:
        logger.error(f"Error getting series for next task: {str(e)}")
        return []    

def read_dicom_from_storage():
    """
    Main function to read DICOM files from configured storage folder (THREAD-PARALLEL VERSION)
    Returns: Dictionary containing processing results and series information for next task
    """
    logger.info("Starting DICOM file reading task (parallel processing)")
    
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
        
        # Collect all files first
        file_list = []
        for root, dirs, files in os.walk(folder_path):
            for file in files:
                file_path = os.path.join(root, file)
                file_list.append((file_path, root, date_filter, current_time, ten_minutes_ago))
        
        logger.info(f"Found {len(file_list)} files to process")
        
        # Check for existing SOP Instance UIDs to avoid duplicates
        existing_sop_uids = set(
            DICOMInstance.objects.values_list('sop_instance_uid', flat=True)
        )
        logger.info(f"Found {len(existing_sop_uids)} existing SOP Instance UIDs in database")
        
        # Process files in parallel using threads (Celery-compatible)
        max_workers = min(cpu_count(), 8)  # Limit to 8 threads max
        logger.info(f"Processing files with {max_workers} parallel threads")
        
        processed_files = 0
        skipped_files = 0
        error_files = 0
        all_results = []
        
        # Process in batches to manage memory
        batch_size = 500
        for i in range(0, len(file_list), batch_size):
            batch = file_list[i:i + batch_size]
            logger.info(f"Processing batch {i//batch_size + 1}/{(len(file_list)-1)//batch_size + 1} ({len(batch)} files)")
            
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # Submit all files in batch
                future_to_file = {
                    executor.submit(process_single_file, file_info): file_info[0]
                    for file_info in batch
                }
                
                # Collect results as they complete
                batch_results = []
                for future in as_completed(future_to_file):
                    try:
                        result = future.result()
                        batch_results.append(result)
                        
                        # Count results (don't modify existing_sop_uids here)
                        if result['status'] == 'success':
                            processed_files += 1
                        elif result['status'] == 'skipped':
                            skipped_files += 1
                            # logger.debug(f"Skipped file: {result['reason']} - {mask_sensitive_data(result['file_path'], 'file_path')}")
                        else:
                            error_files += 1
                            logger.warning(f"Error processing file: {result.get('reason', 'unknown')} - {mask_sensitive_data(result['file_path'], 'file_path')}")
                            
                    except Exception as e:
                        error_files += 1
                        logger.error(f"Future execution error: {str(e)}")
            
            # Filter successful results and create database records
            successful_results = [r for r in batch_results if r['status'] == 'success']
            logger.info(f"Batch completed: {len(successful_results)} successful, {len([r for r in batch_results if r['status'] == 'skipped'])} skipped, {len([r for r in batch_results if r['status'] == 'error'])} errors")
            
            # Filter out existing SOP UIDs
            new_results = []
            for result in successful_results:
                sop_uid = result['metadata']['sop_instance_uid']
                if sop_uid not in existing_sop_uids:
                    new_results.append(result)
                    existing_sop_uids.add(sop_uid)  # Add to set to avoid duplicates in same batch
            
            logger.info(f"After filtering existing UIDs: {len(new_results)} new files to create")
            
            if new_results:
                logger.info(f"Creating database records for {len(new_results)} files")
                try:
                    batch_series_data = bulk_create_database_records(new_results)
                    all_results.extend(new_results)
                    logger.info(f"Successfully created records for batch")
                except Exception as e:
                    logger.error(f"Error creating database records for batch: {str(e)}")
                    import traceback
                    traceback.print_exc()
                    error_files += len(new_results)
            else:
                logger.info(f"No new files to process in this batch (all {len(successful_results)} already exist)")
        
        logger.info(f"DICOM reading completed. Processed: {processed_files}, Skipped: {skipped_files}, Errors: {error_files}")
        
        # Get final series data for next task
        series_data = get_series_for_next_task()
        


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

