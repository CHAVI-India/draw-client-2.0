# Task 3: Deidentify the series (code to be written in task3_deidentify_series.py)
# For the series root path, read the DICOM metadata of each file one by one. 
# Deidentification will involve replacement of all the UIDs, Patient name, Patient Date of Birth, Center information, addresses as well as provider related information. For most fields these will be replaced with and #. However UIDs will be replaced with valid DICOM UIDs. 
# The following DICOM data will be replaced with # :

        # 'PatientName',  # (0010,0010)
        # 'ReferringPhysicianName',  # (0008,0090)
        # 'InstitutionName',  # (0008,0080)
        # 'PerformingPhysicianName',  # (0008,1050)
        # 'OperatorsName',  # (0008,1070)
        # 'StationName',  # (0008,1010)
        # 'InstitutionalDepartmentName',  # (0008,1040)
        # 'PhysiciansOfRecord',  # (0008,1048)
        # 'RequestingPhysician',  # (0032,1032)
        # 'ReferringPhysicianIdentificationSequence',  # (0008,0096)
        # 'ConsultingPhysicianName',  # (0008,009C)
        # 'ResponsiblePerson',  # (0010,2297)
        # 'ReviewerName'  # (300E,0008)
        # Person's Address #
        # Institution Address #
        # Phone Number #

# The dates like Study Date, Series Date, Instance Date will be replaced with a random but valid date (all of these dates should be same so generate a random date before replacement. All instances in the series should have the same date. Similiarly if two studies are done on the same date then the same date should be used to replace. To do this check the value representation of the tag and if it  DA or DT then apply this rule. 

# UID generation rules are as follows:
# The organization prefix to be used is 1.2.826.0.1.3680043.10.1561
# Patient ID : Random UUID
# Study Instance UID : <organization_prefix>>.<random_integer(length=3)>.<random_integer(length=2)>.<random_integer(length=3)> 
# Series Instance UID : <deidentified_study_instance_uid>.<count> where count is the number of series for the given study.
# Frame of Reference UID : <deidentified_series_instance_uid>.<random_integer(length=4)>
# SOP Instance UID : <deidentified_series_instance_uid>.<random_integer(length=7)>.<random_integer(length=3)>
# For all nested referenced UID these should be replaced by the corresponding UIDs from the database if available. If not then randomly the digits should be changed while maintaining the length of the UID.
# MediaStorageSOPInstanceUID should be equal to the SOP Instance UID
# Store the IDs in the database 
# - Deidentified patient ID (patient table)
# - Deidentified patient date of birth (patient table)
# - Deidentified study instance UID (study table)
# - Deidentified Study date (study table)
# - Deidentified Series instance UID (series table)
# - Deidentified frame of reference uid (series table)
# - Deidentified series date (series table)
# - Deidentified sop instance uid (instance table)
# 
# Also remove all private tags from the DICOM file using pydicom native functionality.
# Replace the uids and write the file to a local folder (deidentified_dicom). If folder does not exist create it.
# Generate the autosegmentation template file.yml and save it to the deidentified_dicom folder
# Zip the deidentified_dicom folder and save it to the deidentified_dicom folder. Remove the  folder after all files have been zipped.
# Update the processing_status field of the DICOMSeries model to DEIDENTIFIED_SUCCESSFULLY. Store the deidentified SEries instance UID, deiedentified zip file in the DICOMFileExport model
# Pass the zip file path to the next task along with corresponding DICOMSeriesUID. 
# Ensure logging of all operations while masking sensitive information.

import os
import logging
import pydicom
import random
import uuid
import shutil
import yaml
import zipfile
from datetime import datetime, date, timedelta
from django.db import transaction
from django.core.exceptions import ObjectDoesNotExist
import json

from ..models import (
    DICOMSeries, DICOMInstance, DICOMStudy, Patient, ProcessingStatus,
    DICOMFileExport, DICOMFileTransferStatus, AutosegmentationTemplate
)
from django.utils import timezone
from django.db.models import Count

# Configure logging with masking for sensitive information
logger = logging.getLogger(__name__)
# Organization prefix for UID generation
ORGANIZATION_PREFIX = "1.2.826.0.1.3680043.10.1561"

# Fields to replace with # for deidentification
FIELDS_TO_MASK = [
    'PatientName',  # (0010,0010)
    'ReferringPhysicianName',  # (0008,0090)
    'InstitutionName',  # (0008,0080)
    'PerformingPhysicianName',  # (0008,1050)
    'OperatorsName',  # (0008,1070)
    'StationName',  # (0008,1010)
    'InstitutionalDepartmentName',  # (0008,1040)
    'PhysiciansOfRecord',  # (0008,1048)
    'RequestingPhysician',  # (0032,1032)
    'ConsultingPhysicianName',  # (0008,009C)
    'ResponsiblePerson',  # (0010,2297)
    'ReviewerName',  # (300E,0008)
    'InstitutionAddress',  # (0008,0081)
    'ReferringPhysicianAddress',  # (0008,0092)
    'InstitutionCodeSequence',  # (0008,0082)
    'PhysiciansReadingStudyIdentificationSequence',  # (0008,1062)
    'OperatorIdentificationSequence',  # (0008,1072)
    'PersonAddress',  # (0040,1102)
    'TelephoneNumbers',  # (0040,1103)
]

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

def generate_random_integer(length):
    """
    Generate a random integer with specified length
    """
    if length <= 0:
        return 0
    min_val = 10**(length-1) if length > 1 else 0
    max_val = 10**length - 1
    return random.randint(min_val, max_val)

def generate_deidentified_study_uid():
    """
    Generate a new deidentified Study Instance UID
    Returns: Study UID string
    """
    # Generate Study Instance UID: <organization_prefix>.<random_integer(3)>.<random_integer(2)>.<random_integer(3)>
    return f"{ORGANIZATION_PREFIX}.{generate_random_integer(3)}.{generate_random_integer(2)}.{generate_random_integer(3)}"

def generate_deidentified_series_uids(study_uid, series_count=1):
    """
    Generate deidentified Series and Frame of Reference UIDs based on existing Study UID
    Returns: Dictionary with generated UIDs
    """
    # Generate Series Instance UID: <deidentified_study_instance_uid>.<count>
    series_uid = f"{study_uid}.{series_count}"
    
    # Generate Frame of Reference UID: <deidentified_series_instance_uid>.<random_integer(4)>
    frame_of_ref_uid = f"{series_uid}.{generate_random_integer(4)}"
    
    return {
        'study_instance_uid': study_uid,
        'series_instance_uid': series_uid,
        'frame_of_reference_uid': frame_of_ref_uid
    }

def generate_sop_instance_uid(series_uid, instance_number):
    """
    Generate SOP Instance UID: <deidentified_series_instance_uid>.<random_integer(7)>.<random_integer(3)>
    """
    return f"{series_uid}.{generate_random_integer(7)}.{generate_random_integer(3)}"

def generate_random_date():
    """
    Generate a random but valid date for deidentification
    """
    # Generate a date between 2000 and 2020 to avoid recent dates
    start_date = date(2000, 1, 1)
    end_date = date(2020, 12, 31)
    
    time_between = end_date - start_date
    days_between = time_between.days
    random_days = random.randrange(days_between)
    
    return start_date + timedelta(days=random_days)

def deidentify_dicom_file(file_path, uid_mappings, date_mappings, output_path):
    """
    Deidentify a single DICOM file
    Returns: Dictionary with deidentified metadata
    """
    try:
        # Read DICOM file
        dicom_data = pydicom.dcmread(file_path, force=True)
        
        # Store original SOP Instance UID for tracking
        original_sop_uid = getattr(dicom_data, 'SOPInstanceUID', None)
        
        # Replace fields with # for deidentification
        for field_name in FIELDS_TO_MASK:
            if hasattr(dicom_data, field_name):
                setattr(dicom_data, field_name, '#')
        
        # Replace UIDs
        if 'study_instance_uid' in uid_mappings:
            dicom_data.StudyInstanceUID = uid_mappings['study_instance_uid']
        
        if 'series_instance_uid' in uid_mappings:
            dicom_data.SeriesInstanceUID = uid_mappings['series_instance_uid']
        
        if 'frame_of_reference_uid' in uid_mappings:
            if hasattr(dicom_data, 'FrameOfReferenceUID'):
                dicom_data.FrameOfReferenceUID = uid_mappings['frame_of_reference_uid']
        
        # Generate new SOP Instance UID
        new_sop_uid = generate_sop_instance_uid(uid_mappings['series_instance_uid'], 
                                               getattr(dicom_data, 'InstanceNumber', 1))
        dicom_data.SOPInstanceUID = new_sop_uid
        
        # Set MediaStorageSOPInstanceUID equal to SOPInstanceUID
        if hasattr(dicom_data, 'file_meta') and hasattr(dicom_data.file_meta, 'MediaStorageSOPInstanceUID'):
            dicom_data.file_meta.MediaStorageSOPInstanceUID = new_sop_uid
        
        # Replace Patient ID with UUID
        if hasattr(dicom_data, 'PatientID'):
            if 'patient_id' in uid_mappings:
                dicom_data.PatientID = uid_mappings['patient_id']
            else:
                dicom_data.PatientID = str(uuid.uuid4())
        
        # Replace dates with consistent random dates
        for element in dicom_data:
            if element.VR in ['DA', 'DT']:  # Date or DateTime
                tag_name = element.name if hasattr(element, 'name') else str(element.tag)
                if tag_name in date_mappings:
                    if element.VR == 'DA':
                        element.value = date_mappings[tag_name].strftime('%Y%m%d')
                    else:  # DT
                        element.value = date_mappings[tag_name].strftime('%Y%m%d%H%M%S')
        
        # Remove private tags
        dicom_data.remove_private_tags()
        
        # Save deidentified file
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        dicom_data.save_as(output_path,enforce_file_format=True)
        
        return {
            'original_sop_uid': original_sop_uid,
            'deidentified_sop_uid': new_sop_uid,
            'output_path': output_path
        }
        
    except Exception as e:
        logger.error(f"Error deidentifying DICOM file {mask_sensitive_data(file_path, 'file_path')}: {str(e)}")
        return None

def create_autosegmentation_template_yaml(template_info, output_dir):
    """
    Create autosegmentation template YAML file with proper database structure
    """
    try:
        from ..models import AutosegmentationTemplate, AutosegmentationModel, AutosegmentationStructure
        
        template_id = template_info.get('template_id')
        template_name = template_info.get('template_name')
        
        if not template_id:
            logger.warning("No template ID provided for YAML creation")
            return None
        
        # Get template from database
        try:
            template = AutosegmentationTemplate.objects.get(id=template_id)
        except AutosegmentationTemplate.DoesNotExist:
            logger.error(f"Template not found: {template_id}")
            return None
        
        # Build template data structure
        template_data = {
            'name': template.template_name,
            'protocol': 'DRAW',
            'models': {}
        }
        
        # Get all models associated with this template
        models = AutosegmentationModel.objects.filter(autosegmentation_template_name=template)
        
        for model in models:
            model_data = {
                'name': model.name,
                'config': model.config,
                'map': {},
                'trainer_name': model.trainer_name,
                'postprocess': model.postprocess
            }
            
            # Get all structures (maps) for this model
            structures = AutosegmentationStructure.objects.filter(autosegmentation_model=model)
            
            for structure in structures:
                model_data['map'][structure.map_id] = structure.name
            
            # Add model to template data using model_id as key
            template_data['models'][model.model_id] = model_data
        
        yaml_path = os.path.join(output_dir, 'autosegmentation_template.yml')
        with open(yaml_path, 'w') as yaml_file:
            yaml.dump(template_data, yaml_file, default_flow_style=False, sort_keys=False)
        
        logger.info(f"Created autosegmentation template YAML: {yaml_path}")
        return yaml_path
        
    except Exception as e:
        logger.error(f"Error creating autosegmentation template YAML: {str(e)}")
        return None

def create_zip_file(source_dir, zip_path):
    """
    Create ZIP file from directory and remove source directory
    """
    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(source_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, source_dir)
                    zipf.write(file_path, arcname)
        
        # Remove source directory after successful ZIP creation
        shutil.rmtree(source_dir)
        
        logger.info(f"Created ZIP file: {zip_path}")
        return True
        
    except Exception as e:
        logger.error(f"Error creating ZIP file {zip_path}: {str(e)}")
        return False

def update_database_with_deidentified_data(series_uid, uid_mappings, date_mappings, instance_mappings, zip_path=None):
    """
    Update database with deidentified UIDs and dates
    """
    try:
        with transaction.atomic():
            # Get the series
            series = DICOMSeries.objects.get(series_instance_uid=series_uid)
            study = series.study
            patient = study.patient
            
            # Update patient with deidentified data
            if 'patient_id' in uid_mappings:
                patient.deidentified_patient_id = uid_mappings['patient_id']
            
            # Update patient birth date if available in date mappings
            if 'PatientBirthDate' in date_mappings:
                patient.patient_date_of_birth = date_mappings['PatientBirthDate']
            
            patient.save()
            
            # Update study with deidentified data
            if 'study_instance_uid' in uid_mappings:
                study.deidentified_study_instance_uid = uid_mappings['study_instance_uid']
            
            if 'StudyDate' in date_mappings:
                study.deidentified_study_date = date_mappings['StudyDate']
            
            study.save()
            
            # Update series with deidentified data
            if 'series_instance_uid' in uid_mappings:
                series.deidentified_series_instance_uid = uid_mappings['series_instance_uid']
                logger.debug(f"Saving deidentified series UID: {mask_sensitive_data(uid_mappings['series_instance_uid'], 'series_uid')}")
            
            if 'frame_of_reference_uid' in uid_mappings:
                series.deidentified_frame_of_reference_uid = uid_mappings['frame_of_reference_uid']
                logger.debug(f"Saving deidentified frame of reference UID: {mask_sensitive_data(uid_mappings['frame_of_reference_uid'], 'frame_uid')}")
            
            if 'SeriesDate' in date_mappings:
                series.deidentified_series_date = date_mappings['SeriesDate']
            
            series.save()
            
            # Update instances with deidentified SOP Instance UIDs
            for original_sop_uid, deidentified_sop_uid in instance_mappings.items():
                try:
                    instance = DICOMInstance.objects.get(sop_instance_uid=original_sop_uid)
                    instance.deidentified_sop_instance_uid = deidentified_sop_uid
                    instance.save()
                except DICOMInstance.DoesNotExist:
                    logger.warning(f"Instance not found for SOP UID: {mask_sensitive_data(original_sop_uid, 'sop_uid')}")
            
            # Update series processing status in the same transaction
            series.series_processsing_status = ProcessingStatus.DEIDENTIFIED_SUCCESSFULLY
            series.save()  # Save again with the status update
            
            # Create or update DICOMFileExport record if zip_path is provided
            if zip_path:
                file_export, created = DICOMFileExport.objects.get_or_create(
                    deidentified_series_instance_uid=series,
                    defaults={
                        'deidentified_zip_file_path': zip_path,
                        'deidentified_zip_file_transfer_status': DICOMFileTransferStatus.PENDING
                    }
                )
                
                if not created:
                    file_export.deidentified_zip_file_path = zip_path
                    file_export.deidentified_zip_file_transfer_status = DICOMFileTransferStatus.PENDING
                    file_export.save()
            
            logger.info(f"Updated database with deidentified data for series: {mask_sensitive_data(series_uid, 'series_uid')}")
            return True
            
    except Exception as e:
        logger.error(f"Error updating database with deidentified data: {str(e)}")
        return False

def log_deidentification_summary(deidentified_results):
    """
    Log comprehensive summary of deidentification process
    Shows patient, study, series, and instance level statistics
    """
    if not deidentified_results:
        logger.info("No series were deidentified")
        return
    
    logger.info("="*80)
    logger.info("DEIDENTIFICATION SUMMARY")
    logger.info("="*80)
    
    # Collect unique patients, studies, series
    unique_patients = set()
    unique_studies = set()
    total_instances = 0
    
    for result in deidentified_results:
        try:
            series = DICOMSeries.objects.get(series_instance_uid=result['original_series_uid'])
            study = series.study
            patient = study.patient
            
            unique_patients.add(patient.patient_id)
            unique_studies.add(study.study_instance_uid)
            total_instances += result.get('file_count', 0)
        except Exception as e:
            logger.warning(f"Could not retrieve info for series: {e}")
    
    logger.info(f"Total Patients Deidentified: {len(unique_patients)}")
    logger.info(f"Total Studies Deidentified: {len(unique_studies)}")
    logger.info(f"Total Series Deidentified: {len(deidentified_results)}")
    logger.info(f"Total Instances Deidentified: {total_instances}")
    logger.info("")
    
    # Show per-series details
    logger.info("DEIDENTIFIED SERIES DETAILS:")
    for idx, result in enumerate(deidentified_results, 1):
        logger.info(f"  Series {idx}:")
        logger.info(f"    Original Series UID: {mask_sensitive_data(result['original_series_uid'], 'series_uid')}")
        logger.info(f"    Deidentified Series UID: {mask_sensitive_data(result['deidentified_series_uid'], 'series_uid')}")
        logger.info(f"    Template: {result.get('template_name', 'N/A')}")
        logger.info(f"    Instances: {result.get('file_count', 0)}")
        logger.info(f"    ZIP File: {mask_sensitive_data(result['zip_file_path'], 'file_path')}")
        logger.info("")
    
    logger.info("="*80)
    logger.info("✅ Deidentification process completed successfully")
    logger.info("="*80)

def deidentify_series(task2_output):
    """
    Main function to deidentify DICOM series
    Input: Output from task2 (matched series data)
    Returns: Dictionary containing deidentified series information for next task
    """
    logger.info("Starting DICOM series deidentification task")
    
    try:
        # Validate input
        if not task2_output or task2_output.get('status') != 'success':
            logger.error("Invalid input from task2 or task2 failed")
            return {"status": "error", "message": "Invalid input from previous task"}
        
        matched_series = task2_output.get('matched_series', [])
        if not matched_series:
            logger.info("No matched series to deidentify")
            return {"status": "success", "processed_series": 0, "deidentified_series": []}
        
        logger.info(f"Processing {len(matched_series)} matched series for deidentification")
        
        deidentified_results = []
        processed_count = 0
        
        # Create base deidentified_dicom directory
        base_output_dir = "deidentified_dicom"
        os.makedirs(base_output_dir, exist_ok=True)
        
        # Keep track of study UIDs and their deidentified counterparts for consistency
        study_uid_mappings = {}
        study_date_mappings = {}
        series_counters = {}  # Track series count per study
        
        for series_info in matched_series:
            try:
                series_uid = series_info['series_instance_uid']
                series_root_path = series_info['series_root_path']
                template_id = series_info.get('associated_template_id')
                template_name = series_info.get('associated_template_name')
                
                logger.info(f"Deidentifying series: {mask_sensitive_data(series_uid, 'series_uid')}")
                
                # Get series from database
                series = DICOMSeries.objects.get(series_instance_uid=series_uid)
                study = series.study
                original_study_uid = study.study_instance_uid
                
                # Generate or reuse study UID mappings for consistency
                if original_study_uid not in study_uid_mappings:
                    # Generate new study UID only once per study
                    deidentified_study_uid = generate_deidentified_study_uid()
                    study_uid_mappings[original_study_uid] = {
                        'study_instance_uid': deidentified_study_uid
                    }
                    series_counters[original_study_uid] = 0
                    
                    # Generate consistent date mappings for this study
                    random_date = generate_random_date()
                    study_date_mappings[original_study_uid] = {
                        'StudyDate': random_date,
                        'SeriesDate': random_date,
                        'ContentDate': random_date,
                        'AcquisitionDate': random_date,
                        'PatientBirthDate': random_date
                    }
                
                # Increment series counter for this study
                series_counters[original_study_uid] += 1
                current_series_count = series_counters[original_study_uid]
                
                # Generate UIDs for this series using the existing study UID
                existing_study_uid = study_uid_mappings[original_study_uid]['study_instance_uid']
                uid_mappings = generate_deidentified_series_uids(existing_study_uid, current_series_count)
                uid_mappings['patient_id'] = str(uuid.uuid4())
                
                logger.debug(f"Generated UIDs for series {current_series_count}: Study={mask_sensitive_data(uid_mappings['study_instance_uid'], 'study_uid')}, Series={mask_sensitive_data(uid_mappings['series_instance_uid'], 'series_uid')}, Frame={mask_sensitive_data(uid_mappings['frame_of_reference_uid'], 'frame_uid')}")
                
                # Use consistent date mappings for this study
                date_mappings = study_date_mappings[original_study_uid]
                
                # Create output directory for this series with random number to avoid conflicts
                random_suffix = generate_random_integer(6)
                series_output_dir = os.path.join(base_output_dir, f"series_{current_series_count}_{series_uid}_{random_suffix}")
                os.makedirs(series_output_dir, exist_ok=True)
                
                # Get all DICOM instances for this series
                instances = DICOMInstance.objects.filter(series_instance_uid=series)
                
                if not instances.exists():
                    logger.warning(f"No instances found for series: {mask_sensitive_data(series_uid, 'series_uid')}")
                    continue
                
                # Deidentify each DICOM file
                instance_mappings = {}
                deidentified_files = []
                
                for instance in instances:
                    if not os.path.exists(instance.instance_path):
                        logger.warning(f"Instance file not found: {mask_sensitive_data(instance.instance_path, 'file_path')}")
                        continue
                    
                    # Generate output path
                    filename = os.path.basename(instance.instance_path)
                    output_path = os.path.join(series_output_dir, filename)
                    
                    # Deidentify the file
                    result = deidentify_dicom_file(instance.instance_path, uid_mappings, date_mappings, output_path)
                    
                    if result:
                        instance_mappings[result['original_sop_uid']] = result['deidentified_sop_uid']
                        deidentified_files.append(result['output_path'])
                        logger.debug(f"Deidentified instance: {mask_sensitive_data(result['original_sop_uid'], 'sop_uid')}")
                
                if not deidentified_files:
                    logger.error(f"No files were successfully deidentified for series: {mask_sensitive_data(series_uid, 'series_uid')}")
                    continue
                
                # Create autosegmentation template YAML
                template_info = {
                    'template_id': template_id,
                    'template_name': template_name,
                    'series_uid': uid_mappings['series_instance_uid'],
                    'study_uid': uid_mappings['study_instance_uid']
                }
                
                yaml_path = create_autosegmentation_template_yaml(template_info, series_output_dir)
                
                # Create ZIP file
                zip_filename = f"deidentified_series_{uid_mappings['series_instance_uid']}.zip"
                zip_path = os.path.join(base_output_dir, zip_filename)
                
                if create_zip_file(series_output_dir, zip_path):
                    # Update database with deidentified data, status, and export record in single transaction
                    if update_database_with_deidentified_data(series_uid, uid_mappings, date_mappings, instance_mappings, zip_path):
                        
                        # Add to results for next task
                        deidentified_results.append({
                            'original_series_uid': series_uid,
                            'deidentified_series_uid': uid_mappings['series_instance_uid'],
                            'zip_file_path': zip_path,
                            'template_id': template_id,
                            'template_name': template_name,
                            'file_count': len(deidentified_files)
                        })
                        
                        logger.info(f"Successfully deidentified series: {mask_sensitive_data(series_uid, 'series_uid')} -> {mask_sensitive_data(uid_mappings['series_instance_uid'], 'series_uid')}")
                        processed_count += 1
                        
                    else:
                        logger.error(f"Failed to update database for series: {mask_sensitive_data(series_uid, 'series_uid')}")
                        # Update status to failed
                        series.series_processsing_status = ProcessingStatus.DEIDENTIFICATION_FAILED
                        series.save()
                else:
                    logger.error(f"Failed to create ZIP file for series: {mask_sensitive_data(series_uid, 'series_uid')}")
                    series.series_processsing_status = ProcessingStatus.DEIDENTIFICATION_FAILED
                    series.save()
                    
            except DICOMSeries.DoesNotExist:
                logger.error(f"Series not found in database: {mask_sensitive_data(series_info.get('series_instance_uid', 'unknown'), 'series_uid')}")
                continue
            except Exception as e:
                logger.error(f"Error processing series {mask_sensitive_data(series_info.get('series_instance_uid', 'unknown'), 'series_uid')}: {str(e)}")
                continue
        
        logger.info(f"Deidentification completed. Processed: {processed_count}, Successful: {len(deidentified_results)}")
        
        # Log comprehensive summary
        log_deidentification_summary(deidentified_results)
        
        return {
            "status": "success",
            "processed_series": processed_count,
            "successful_deidentifications": len(deidentified_results),
            "deidentified_series": deidentified_results
        }
        
    except Exception as e:
        logger.error(f"Critical error in deidentification task: {str(e)}")
        return {"status": "error", "message": str(e)}
