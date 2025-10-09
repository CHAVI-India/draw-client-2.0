# This will run after task1_poll_and_retrieve_rtstruct code runs and will take output from that.
# The purpose is to reidentify the RT struct file 
# For this we need to replace all UID values with the corresponding values from the database.
# The database lookup is to be done with respect to the deidentified_series_instance_uid value in the DICOMSeries table which should match with the referenced_series_intance_uid value in the RTStruct File.
# The following will need to be replaced:
# Referenced Series Instance UID : Series instance UID from the DICOMSeries table
# Patient ID: Patient ID from the Patient table
# Paitient Name: Patient Name from the Patient table
# Patient date of birth : Patient date of birth from the Patient table
# Study Instance UID: From the DicomStudy table
# Study Description: From the DicomStudy table
# Study Date : From the DicomStudy table
# Referring Physician Name : "DRAW"
# Accession Number : 202514789
# Frame of reference UIDs (0x0020,0x0052), (0x3006,0x0024) from the DICOM series Table
# Referenced SOP Instance UID  (0x0008,0x1155), (0x0020,0x000E) from the DICOM Instance table.
# After this file is written to the series_root_path available in the DICOMSeries table. This will ensure that the file is sent back to the same folder where the DICOM data was available. The filename should be starting with <PATIENT_ID>_<DRAW>_<DATETIME>_RTSTRUCT.dcm format.
# Update the series_processsing_status to RTSTRUCTURE_EXPORTED if successful else to RTSTRUCTURE_EXPORT_FAILED in the DICOMSeries model. 
# Update the path where the file was saved in the RTStructureFileImport model in the reidentified_rt_structure_file_path field and update the date time in reidentified_rt_structure_file_export_datetime field.
# Read the names of all VOI in the file and save it the RTStructureFileVOIData model.
# Following this the RTstructurefile should be deleted from the folder where it was downloaded into.
import os
import logging
import shutil
import re
from datetime import datetime
from typing import Dict, Any, List
from django.db import transaction
from django.utils import timezone
import pydicom
from pydicom.errors import InvalidDicomError

from ..models import (
    DICOMSeries, DICOMStudy, Patient, DICOMInstance, RTStructureFileImport,
    RTStructureFileVOIData,
    ProcessingStatus
)

logger = logging.getLogger(__name__)

def _sanitize_filename(filename: str) -> str:
    """
    Sanitize filename by replacing special characters with underscores.
    
    Args:
        filename: Original filename string
        
    Returns:
        Sanitized filename safe for filesystem use
    """
    # Replace any character that is not alphanumeric, dash, or underscore with underscore
    sanitized = re.sub(r'[^\w\-]', '_', filename)
    # Remove multiple consecutive underscores
    sanitized = re.sub(r'_+', '_', sanitized)
    # Remove leading/trailing underscores
    sanitized = sanitized.strip('_')
    return sanitized

def reidentify_rtstruct(task_input: Dict[str, Any]) -> Dict[str, Any]:
    """
    Reidentify RTStructure files by replacing deidentified UIDs with original values.
    
    This function:
    1. Takes input from task1_poll_and_retrieve_rtstruct
    2. Loads RTStructure files and looks up original DICOM data
    3. Replaces deidentified UIDs with original patient/study/series data
    4. Exports reidentified files to original series folders
    5. Updates database statuses and cleans up temporary files
    
    Args:
        task_input: Dict containing downloaded_rtstruct_files list from task1
        
    Returns:
        Dict containing processing results for task chain
        
    Raises:
        Exception: If critical errors occur during processing
    """
    logger.info("Starting RTStructure reidentification task")
    
    downloaded_files = task_input.get('downloaded_rtstruct_files', [])
    if not downloaded_files:
        logger.info("No RTStructure files to reidentify")
        return {"reidentified_files": [], "processed_count": 0, "failed_count": 0}
    
    processed_count = 0
    failed_count = 0
    reidentified_files = []
    
    try:
        with transaction.atomic():
            for file_info in downloaded_files:
                try:
                    logger.info(f"Processing RTStructure file: {file_info.get('rtstruct_file_path', 'Unknown')}")
                    
                    # Process individual RTStructure file
                    result = _process_rtstruct_file(file_info)
                    
                    if result['success']:
                        processed_count += 1
                        reidentified_files.append(result['file_info'])
                        logger.info(f"Successfully reidentified RTStructure: {result['file_info']['output_path']}")
                    else:
                        failed_count += 1
                        logger.error(f"Failed to reidentify RTStructure: {result['error']}")
                        
                except Exception as e:
                    failed_count += 1
                    logger.error(f"Error processing RTStructure file {file_info.get('rtstruct_file_path', 'Unknown')}: {str(e)}")
                    continue
    
    except Exception as e:
        logger.error(f"Critical error in reidentify_rtstruct: {str(e)}")
        raise
    
    logger.info(f"RTStructure reidentification completed. Processed: {processed_count}, Failed: {failed_count}")
    return {
        "reidentified_files": reidentified_files,
        "processed_count": processed_count,
        "failed_count": failed_count
    }

def _process_rtstruct_file(file_info: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process a single RTStructure file for reidentification.
    
    Args:
        file_info: Dict containing file information from task1
        
    Returns:
        Dict with processing result and file information
    """
    try:
        # Extract file information
        rtstruct_path = file_info['rtstruct_file_path']
        deidentified_series_uid = file_info['deidentified_series_instance_uid']
        rt_import_id = file_info['rt_import_id']
        
        # Get RTStructureFileImport record
        rt_import = RTStructureFileImport.objects.get(id=rt_import_id)
        
        # Get DICOMSeries and related data
        series_data = _get_series_data(deidentified_series_uid)
        if not series_data:
            _update_failed_status(rt_import, "Series data not found")
            return {"success": False, "error": "Series data not found"}
        
        # Load and modify RTStructure file
        modified_ds = _reidentify_dicom_tags(rtstruct_path, series_data)
        if not modified_ds:
            _update_failed_status(rt_import, "Failed to reidentify DICOM tags")
            return {"success": False, "error": "Failed to reidentify DICOM tags"}
        
        # Export to original series folder
        output_path = _export_reidentified_file(modified_ds, series_data, rt_import)
        if not output_path:
            _update_failed_status(rt_import, "Failed to export reidentified file")
            return {"success": False, "error": "Failed to export reidentified file"}
        
        # Get VOI names from RTStructure file and save to database
        _extract_and_save_voi_data(rtstruct_path, rt_import)
        
        # Update successful status
        _update_successful_status(rt_import, output_path, series_data['series'])
        
        # Clean up temporary file
        _cleanup_temp_file(rtstruct_path)
        
        return {
            "success": True,
            "file_info": {
                "original_path": rtstruct_path,
                "output_path": output_path,
                "series_uid": series_data['series'].series_instance_uid,
                "patient_id": series_data['patient'].patient_id
            }
        }
        
    except Exception as e:
        logger.error(f"Error processing RTStructure file: {str(e)}")
        return {"success": False, "error": str(e)}

def _get_series_data(deidentified_series_uid: str) -> Dict[str, Any]:
    """
    Get all related DICOM data for a deidentified series UID.
    
    Args:
        deidentified_series_uid: Deidentified series instance UID
        
    Returns:
        Dict containing series, study, patient, and instances data
    """
    try:
        # Get DICOMSeries
        series = DICOMSeries.objects.select_related('study__patient').get(
            deidentified_series_instance_uid=deidentified_series_uid
        )
        
        # Get related study and patient
        study = series.study
        patient = study.patient
        
        # Get DICOM instances for this series
        instances = list(DICOMInstance.objects.filter(series_instance_uid=series))
        
        return {
            'series': series,
            'study': study,
            'patient': patient,
            'instances': instances
        }
        
    except DICOMSeries.DoesNotExist:
        logger.error(f"DICOMSeries not found for deidentified UID: ***{deidentified_series_uid[:4]}...{deidentified_series_uid[-4:]}***")
        return None
    except Exception as e:
        logger.error(f"Error getting series data: {str(e)}")
        return None

def _reidentify_dicom_tags(rtstruct_path: str, series_data: Dict[str, Any]) -> pydicom.Dataset:
    """
    Load RTStructure file and replace deidentified tags with original values.
    
    Args:
        rtstruct_path: Path to RTStructure file
        series_data: Dict containing original DICOM data
        
    Returns:
        Modified pydicom Dataset or None if failed
    """
    try:
        # Load RTStructure file
        ds = pydicom.dcmread(rtstruct_path, force=True)
        
        series = series_data['series']
        study = series_data['study']
        patient = series_data['patient']
        instances = series_data['instances']
        
        # Replace patient information
        if patient.patient_id:
            ds.PatientID = patient.patient_id

        if patient.patient_name:
            ds.PatientName = patient.patient_name
        if patient.patient_date_of_birth:
            ds.PatientBirthDate = patient.patient_date_of_birth.strftime('%Y%m%d')
        if patient.patient_gender:
            ds.PatientSex = patient.patient_gender
        
        # Replace study information
        if study.study_instance_uid:
            ds.StudyInstanceUID = study.study_instance_uid
        if study.study_description:
            ds.StudyDescription = study.study_description
        if study.study_date:
            ds.StudyDate = study.study_date.strftime('%Y%m%d')

        logger.debug(f"Reidentified Patient ID, Name, DOB, Gender, Study ID, Description, Study Date fields. Proceeding with other tags")

        # Set fixed values as specified
        ds.ReferringPhysicianName = "DRAW"
        ds.AccessionNumber = "202514789"
        
        logger.debug(f"Reidentified Referring Physician Name, Accession Number fields. Proceeding with other tags")
        # Replace the series description
        if series.series_description:
            ds.SeriesDescription = series.series_description

        # Note: RTStructure's own Series Instance UID (0020,000E) should remain unchanged
        # Only the Referenced Series Instance UID in sequences needs to be updated
        
        logger.debug(f"Skipping RTStructure's own Series Instance UID - keeping original. Proceeding with other tags")
        
        # Build comprehensive UID mapping dictionary including all levels (instance, series, study)
        # This approach matches the working code pattern
        uid_mapping = {}
        missing_original_uids = []
        
        # Add instance-level SOP Instance UIDs
        for instance in instances:
            if instance.deidentified_sop_instance_uid:
                if instance.sop_instance_uid:
                    uid_mapping[instance.deidentified_sop_instance_uid] = instance.sop_instance_uid
                else:
                    missing_original_uids.append(instance.deidentified_sop_instance_uid)
        
        # Add series-level Series Instance UID
        if series.deidentified_series_instance_uid and series.series_instance_uid:
            uid_mapping[series.deidentified_series_instance_uid] = series.series_instance_uid
        elif series.deidentified_series_instance_uid and not series.series_instance_uid:
            logger.error(f"CRITICAL: Original series_instance_uid is missing in database for series ID {series.id}")
            missing_original_uids.append(series.deidentified_series_instance_uid)
        
        # Add study-level Study Instance UID
        if study.deidentified_study_instance_uid and study.study_instance_uid:
            uid_mapping[study.deidentified_study_instance_uid] = study.study_instance_uid
        
        if missing_original_uids:
            logger.warning(f"Found {len(missing_original_uids)} UIDs with missing original values. "
                          f"These will not be reidentified. First few: {missing_original_uids[:5]}")
        
        logger.info(f"Created comprehensive UID mapping with {len(uid_mapping)} entries")
        logger.info(f"  - SOP Instance UIDs: {sum(1 for inst in instances if inst.sop_instance_uid)}")
        logger.info(f"  - Series Instance UID: {'Yes' if series.series_instance_uid else 'No'}")
        logger.info(f"  - Study Instance UID: {'Yes' if study.study_instance_uid else 'No'}")
        
        # Use walk() callbacks to replace UIDs throughout the entire DICOM structure
        # This ensures ALL occurrences are replaced, not just specific sequences
        
        frame_of_reference_replacement_count = 0
        uid_replacement_count = 0
        
        def frame_of_reference_callback(ds_elem, data_element):
            """Replace Frame of Reference UIDs wherever they appear"""
            nonlocal frame_of_reference_replacement_count
            if data_element.tag in [(0x0020, 0x0052), (0x3006, 0x0024)]:
                if series.frame_of_reference_uid:
                    data_element.value = series.frame_of_reference_uid
                    frame_of_reference_replacement_count += 1
                    logger.debug(f"Replaced Frame of Reference UID at tag {data_element.tag}")
        
        def uid_replacement_callback(ds_elem, data_element):
            """Replace Referenced SOP Instance UIDs and Series Instance UIDs wherever they appear"""
            nonlocal uid_replacement_count
            # Tags to replace: (0x0008, 0x1155) = Referenced SOP Instance UID
            #                  (0x0020, 0x000E) = Series Instance UID (in referenced sequences)
            if data_element.tag in [(0x0008, 0x1155), (0x0020, 0x000E)]:
                deidentified_uid = data_element.value
                if deidentified_uid in uid_mapping:
                    original_uid = uid_mapping[deidentified_uid]
                    data_element.value = original_uid
                    uid_replacement_count += 1
                    logger.debug(f"Replaced UID at tag {data_element.tag}: "
                               f"***{deidentified_uid[:8]}...{deidentified_uid[-8:]}*** -> "
                               f"***{original_uid[:8]}...{original_uid[-8:]}***")
                else:
                    logger.debug(f"No mapping found for UID at tag {data_element.tag}: "
                               f"***{deidentified_uid[:8]}...{deidentified_uid[-8:]}***")
        
        # Walk through the entire DICOM structure and apply callbacks
        ds.walk(frame_of_reference_callback)
        ds.walk(uid_replacement_callback)
        
        logger.info(f"Frame of Reference UID replacements: {frame_of_reference_replacement_count}")
        logger.info(f"Total UID replacements (SOP Instance + Series Instance): {uid_replacement_count}")
        
        logger.info(f"Successfully reidentified DICOM tags for patient: ***{patient.patient_id}***")
        return ds
        
    except Exception as e:
        logger.error(f"Error reidentifying DICOM tags: {str(e)}")
        return None

def _export_reidentified_file(ds: pydicom.Dataset, series_data: Dict[str, Any], rt_import: RTStructureFileImport) -> str:
    """
    Export reidentified RTStructure file to original series folder.
    
    Args:
        ds: Modified pydicom Dataset
        series_data: Dict containing original DICOM data
        rt_import: RTStructureFileImport record
        
    Returns:
        Output file path or None if failed
    """
    try:
        series = series_data['series']
        patient = series_data['patient']
        
        # Get output directory from series root path
        output_dir = series.series_root_path
        if not output_dir or not os.path.exists(output_dir):
            logger.error(f"Series root path not found or invalid: {output_dir}")
            return None
        
        # Generate filename: <PATIENT_ID>_DRAW_<DATETIME>_RTSTRUCT.dcm
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        patient_id = patient.patient_id or "UNKNOWN"
        # Sanitize patient ID to make it filesystem-safe
        safe_patient_id = _sanitize_filename(patient_id)
        if safe_patient_id != patient_id:
            logger.info(f"Sanitized patient ID for filename: '{patient_id}' -> '{safe_patient_id}'")
        filename = f"RS_{safe_patient_id}_DRAW_{timestamp}.dcm"
        output_path = os.path.join(output_dir, filename)
        
        # Save the reidentified file
        ds.save_as(output_path,enforce_file_format=True)
        
        logger.info(f"Exported reidentified RTStructure to: {output_path}")
        return output_path
        
    except Exception as e:
        logger.error(f"Error exporting reidentified file: {str(e)}")
        return None

def _update_successful_status(rt_import: RTStructureFileImport, output_path: str, series: DICOMSeries) -> None:
    """Update database statuses after successful reidentification."""
    try:
        # Update RTStructureFileImport record
        rt_import.reidentified_rt_structure_file_path = output_path
        rt_import.reidentified_rt_structure_file_export_datetime = timezone.now()
        rt_import.save(update_fields=[
            'reidentified_rt_structure_file_path',
            'reidentified_rt_structure_file_export_datetime'
        ])
        
        # Update DICOMSeries processing status
        series.series_processsing_status = ProcessingStatus.RTSTRUCTURE_EXPORTED
        series.save(update_fields=['series_processsing_status'])
        
        logger.info(f"Updated successful status for series: ***{series.series_instance_uid[:4]}...{series.series_instance_uid[-4:]}***")
        
    except Exception as e:
        logger.error(f"Error updating successful status: {str(e)}")

def _update_failed_status(rt_import: RTStructureFileImport, error_msg: str) -> None:
    """Update database statuses after failed reidentification."""
    try:
        # Get the related series
        series = rt_import.deidentified_series_instance_uid
        
        # Update DICOMSeries processing status
        series.series_processsing_status = ProcessingStatus.RTSTRUCTURE_EXPORT_FAILED
        series.save(update_fields=['series_processsing_status'])
        
        logger.error(f"Updated failed status for series: ***{series.series_instance_uid[:4]}...{series.series_instance_uid[-4:]}*** - {error_msg}")
        
    except Exception as e:
        logger.error(f"Error updating failed status: {str(e)}")

def _extract_and_save_voi_data(rtstruct_path: str, rt_import: RTStructureFileImport) -> None:
    """
    Extract VOI names from RT Structure Set file and save them to the database.
    Each VOI will be saved as a separate row in RTStructureFileVOIData table.
    
    Args:
        rtstruct_path: Path to the RTStructure DICOM file
        rt_import: RTStructureFileImport record to associate VOI data with
    """
    try:
        # Load the RTStructure file
        ds = pydicom.dcmread(rtstruct_path, force=True)
        
        voi_objects = []
        
        # Check if StructureSetROISequence exists (this contains the VOI names)
        if hasattr(ds, 'StructureSetROISequence') and ds.StructureSetROISequence:
            for roi in ds.StructureSetROISequence:
                # Extract ROI Name from each structure
                if hasattr(roi, 'ROIName') and roi.ROIName:
                    # Create VOI object for bulk insert
                    voi_objects.append(
                        RTStructureFileVOIData(
                            rt_structure_file_import=rt_import,
                            volume_name=roi.ROIName
                        )
                    )
                    logger.debug(f"Found VOI: {roi.ROIName}")
        
        # Bulk create all VOI entries in a single database operation
        if voi_objects:
            RTStructureFileVOIData.objects.bulk_create(voi_objects)
            logger.info(f"Successfully extracted and saved {len(voi_objects)} VOI entries to database using bulk_create")
        else:
            logger.warning(f"No VOI names found in RTStructure file: {rtstruct_path}")
        
    except Exception as e:
        logger.error(f"Error extracting and saving VOI data: {str(e)}")

def _cleanup_temp_file(file_path: str) -> None:
    """Clean up temporary RTStructure file."""
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"Cleaned up temporary file: {file_path}")
    except Exception as e:
        logger.warning(f"Failed to clean up temporary file {file_path}: {str(e)}")