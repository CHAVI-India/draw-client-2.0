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
import SimpleITK as sitk
from rt_utils import RTStructBuilder

from ..models import (
    DICOMSeries, DICOMStudy, Patient, DICOMInstance, RTStructureFileImport,
    RTStructureFileVOIData,
    ProcessingStatus, AutosegmentationStructure, StructureProperties, AdditionalStructures
)
from dicom_server.models import RemoteDicomNode
from dicom_server.cstore_push_service import send_dicom_files_to_node
from ..utils.pipeline_executor import ProductionPipelineExecutor
from ..utils.structure_generation import load_ct_series_as_sitk_image

logger = logging.getLogger(__name__)

def _mask_sensitive_data(data, field_name=""):
    """
    Mask sensitive data for logging purposes.
    """
    if not data:
        return "***EMPTY***"

    # Mask patient identifiable information
    if any(field in field_name.lower() for field in ['name', 'id', 'birth', 'patient']):
        return f"***{field_name.upper()}_MASKED***"

    # For UIDs, show only first and last 4 characters
    if 'uid' in field_name.lower() and len(str(data)) > 8:
        return f"{str(data)[:4]}...{str(data)[-4:]}"

    # For file paths, show only filename
    if 'path' in field_name.lower():
        return f"***PATH***/{os.path.basename(str(data))}"

    return str(data)


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
                    logger.info(f"Processing RTStructure file: {_mask_sensitive_data(file_info.get('rtstruct_file_path', 'Unknown'), 'file_path')}")

                    # Process individual RTStructure file
                    result = _process_rtstruct_file(file_info)

                    if result['success']:
                        processed_count += 1
                        reidentified_files.append(result['file_info'])
                        logger.info(f"Successfully reidentified RTStructure: {_mask_sensitive_data(result['file_info']['output_path'], 'file_path')}")
                    else:
                        failed_count += 1
                        logger.error(f"Failed to reidentify RTStructure: {result['error']}")
                        
                except Exception as e:
                    failed_count += 1
                    logger.error(f"Error processing RTStructure file {_mask_sensitive_data(file_info.get('rtstruct_file_path', 'Unknown'), 'file_path')}: {str(e)}")
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
        _update_successful_status(rt_import, output_path, series_data['series'], modified_ds)
        
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
        if study.study_time:
            ds.StudyTime = study.study_time.strftime('%H%M%S')
        
        # Replace AccessionNumber with original value from database
        if study.accession_number:
            ds.AccessionNumber = study.accession_number
        else:
            ds.AccessionNumber = "202514789"  # Fallback to default if not available
        
        # Replace StudyID with original value from database
        if study.study_id:
            ds.StudyID = study.study_id
        else:
            ds.StudyID = ""  # Empty if not available

        logger.debug(f"Reidentified Patient ID, Name, DOB, Gender, Study UID, Description, Study Date/Time, AccessionNumber, StudyID fields. Proceeding with other tags")

        # Set fixed values as specified
        ds.ReferringPhysicianName = "DRAW"
        
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
                    # logger.debug(f"Replaced UID at tag {data_element.tag}: "
                    #            f"***{deidentified_uid[:8]}...{deidentified_uid[-8:]}*** -> "
                    #            f"***{original_uid[:8]}...{original_uid[-8:]}***")
                else:
                    logger.debug(f"No mapping found for UID at tag {data_element.tag}: "
                               f"***{deidentified_uid[:8]}...{deidentified_uid[-8:]}***")
        # Build ROI property mapping from database
        # Get all matched templates for this series
        roi_property_map = {}
        roi_name_to_number_map = {}  # Map ROI names to ROI numbers for sequence matching
        
        logger.info("Starting ROI property mapping process...")
        
        try:
            matched_templates = series.matched_templates.all()
            logger.info(f"Found {matched_templates.count()} matched templates for series")
            
            for template in matched_templates:
                logger.debug(f"Processing template: {template.template_name}")
                # Get all structures for this template
                structures = AutosegmentationStructure.objects.filter(
                    autosegmentation_model__autosegmentation_template_name=template
                ).select_related('structureproperties')
                
                logger.debug(f"Found {structures.count()} structures for template")
                
                for structure in structures:
                    structure_name = structure.name
                    logger.debug(f"Processing structure: {structure_name}")
                    
                    # Check if this structure name already exists in our map
                    if structure_name in roi_property_map:
                        # Multiple matches - mark as ambiguous
                        roi_property_map[structure_name] = None
                        logger.warning(f"Multiple AutosegmentationStructure matches found for ROI name '{structure_name}'. "
                                     f"Skipping property updates for this ROI.")
                    else:
                        # First match - add to map
                        try:
                            properties = structure.structureproperties
                            roi_property_map[structure_name] = {
                                'roi_label': properties.roi_label if properties.roi_label else None,
                                'roi_display_color': properties.roi_display_color if properties.roi_display_color else None,
                                'rt_roi_interpreted_type': properties.rt_roi_interpreted_type if properties.rt_roi_interpreted_type else None
                            }
                            logger.debug(f"Added properties for '{structure_name}': label={properties.roi_label}, "
                                       f"color={properties.roi_display_color}, type={properties.rt_roi_interpreted_type}")
                        except StructureProperties.DoesNotExist:
                            # No properties set for this structure
                            roi_property_map[structure_name] = {
                                'roi_label': None,
                                'roi_display_color': None,
                                'rt_roi_interpreted_type': None
                            }
                            logger.debug(f"No StructureProperties found for '{structure_name}'")
            
            valid_entries = len([k for k, v in roi_property_map.items() if v is not None])
            logger.info(f"Built ROI property map with {valid_entries} valid entries out of {len(roi_property_map)} total structures")
        except Exception as e:
            logger.error(f"Error building ROI property map: {str(e)}")
            roi_property_map = {}
        
        # Update ROI properties in RT Structure Set sequences
        roi_updates_count = 0
        color_updates_count = 0
        type_updates_count = 0
        
        try:
            # 1. Update StructureSetROISequence - ROI Names and build ROI number mapping
            if hasattr(ds, 'StructureSetROISequence') and ds.StructureSetROISequence:
                logger.info(f"Processing {len(ds.StructureSetROISequence)} ROIs from RT Structure file")
                for roi_item in ds.StructureSetROISequence:
                    if hasattr(roi_item, 'ROIName'):
                        original_roi_name = roi_item.ROIName
                        roi_number = roi_item.ROINumber if hasattr(roi_item, 'ROINumber') else None
                        
                        # Build mapping for later use
                        if roi_number:
                            roi_name_to_number_map[original_roi_name] = roi_number
                        
                        logger.debug(f"ROI from file: '{original_roi_name}' (Number: {roi_number})")
                        
                        # Update ROI name if we have a custom label
                        if original_roi_name in roi_property_map:
                            if roi_property_map[original_roi_name] is not None:
                                properties = roi_property_map[original_roi_name]
                                if properties['roi_label']:
                                    roi_item.ROIName = properties['roi_label']
                                    roi_updates_count += 1
                                    logger.info(f"Updated ROI Name: '{original_roi_name}' -> '{properties['roi_label']}'")
                                    
                                    # Update mapping with new name too
                                    if roi_number:
                                        roi_name_to_number_map[properties['roi_label']] = roi_number
                                else:
                                    logger.debug(f"No custom label set for '{original_roi_name}'")
                            else:
                                logger.debug(f"Skipping '{original_roi_name}' - marked as ambiguous (multiple matches)")
                        else:
                            logger.debug(f"No match found in property map for '{original_roi_name}'")
            
            # 2. Update ROIContourSequence - ROI Display Colors
            if hasattr(ds, 'ROIContourSequence') and ds.ROIContourSequence:
                for contour_item in ds.ROIContourSequence:
                    if hasattr(contour_item, 'ReferencedROINumber'):
                        roi_number = contour_item.ReferencedROINumber
                        
                        # Find the original ROI name for this ROI number
                        original_roi_name = None
                        for name, num in roi_name_to_number_map.items():
                            if num == roi_number:
                                original_roi_name = name
                                break
                        
                        if original_roi_name and original_roi_name in roi_property_map:
                            properties = roi_property_map[original_roi_name]
                            if properties and properties['roi_display_color']:
                                # Parse DICOM color format (e.g., "255\0\0")
                                color_parts = properties['roi_display_color'].split('\\')
                                if len(color_parts) == 3:
                                    try:
                                        # Convert to list of integers
                                        color_values = [int(part.strip()) for part in color_parts]
                                        contour_item.ROIDisplayColor = color_values
                                        color_updates_count += 1
                                        logger.debug(f"Updated ROI Display Color for '{original_roi_name}': {color_values}")
                                    except ValueError as e:
                                        logger.warning(f"Invalid color format for '{original_roi_name}': {properties['roi_display_color']}")
            
            # 3. Update RTROIObservationsSequence - RT ROI Interpreted Types
            if hasattr(ds, 'RTROIObservationsSequence') and ds.RTROIObservationsSequence:
                for obs_item in ds.RTROIObservationsSequence:
                    if hasattr(obs_item, 'ReferencedROINumber'):
                        roi_number = obs_item.ReferencedROINumber
                        
                        # Find the original ROI name for this ROI number
                        original_roi_name = None
                        for name, num in roi_name_to_number_map.items():
                            if num == roi_number:
                                original_roi_name = name
                                break
                        
                        if original_roi_name and original_roi_name in roi_property_map:
                            properties = roi_property_map[original_roi_name]
                            if properties and properties['rt_roi_interpreted_type']:
                                obs_item.RTROIInterpretedType = properties['rt_roi_interpreted_type']
                                type_updates_count += 1
                                logger.debug(f"Updated RT ROI Interpreted Type for '{original_roi_name}': {properties['rt_roi_interpreted_type']}")
            
            logger.info(f"ROI property updates - Names: {roi_updates_count}, Colors: {color_updates_count}, Types: {type_updates_count}")
            
            # Log summary for debugging
            if roi_property_map:
                logger.info(f"Available structure names in property map: {list(roi_property_map.keys())}")
            if roi_name_to_number_map:
                logger.info(f"ROI names found in RT Structure file: {list(roi_name_to_number_map.keys())}")
            
        except Exception as e:
            logger.error(f"Error updating ROI properties: {str(e)}", exc_info=True)
        
        # Add AdditionalStructures as empty ROIs
        try:
            _add_additional_structures_to_rtstruct(ds, series_data, roi_name_to_number_map)
        except Exception as e:
            logger.error(f"Error adding additional structures: {str(e)}", exc_info=True)


        ds.walk(frame_of_reference_callback)
        ds.walk(uid_replacement_callback)
        
        logger.info(f"Frame of Reference UID replacements: {frame_of_reference_replacement_count}")
        logger.info(f"Total UID replacements (SOP Instance + Series Instance): {uid_replacement_count}")

        logger.info(f"Successfully reidentified DICOM tags for patient: {_mask_sensitive_data(patient.patient_id, 'patient_id')}")
        return ds
        
    except Exception as e:
        logger.error(f"Error reidentifying DICOM tags: {str(e)}")
        return None

def _add_additional_structures_to_rtstruct(ds: pydicom.Dataset, series_data: Dict[str, Any], roi_name_to_number_map: Dict[str, int]) -> None:
    """
    Add AdditionalStructures to the RT Structure Set by executing their generation pipelines.
    
    This function:
    1. Retrieves AdditionalStructures linked to the matched templates
    2. Loads the CT series and creates RTStructBuilder
    3. Executes roi_generation_logic pipelines to generate contours
    4. Adds generated structures to the RT Structure Set
    
    Args:
        ds: pydicom Dataset of RT Structure Set
        series_data: Dict containing series, study, patient data
        roi_name_to_number_map: Dict mapping ROI names to ROI numbers
    """
    try:
        series = series_data['series']
        
        # Get matched templates for this series
        matched_templates = series.matched_templates.all()
        
        if not matched_templates:
            logger.info("No matched templates found for series - skipping additional structures")
            return
        
        logger.info(f"Found {len(matched_templates)} matched template(s) for series")
        
        # Collect all additional structures from matched templates
        additional_structures = []
        for template in matched_templates:
            template_structures = AdditionalStructures.objects.filter(
                autosegmentation_template=template
            ).order_by('roi_label')
            
            additional_structures.extend(template_structures)
            logger.info(f"Template '{template.template_name}': {len(template_structures)} additional structure(s)")
        
        if not additional_structures:
            logger.info("No additional structures found - skipping")
            return
        
        logger.info(f"Processing {len(additional_structures)} additional structure(s)")
        
        # Get the current maximum ROI number
        max_roi_number = 0
        if hasattr(ds, 'StructureSetROISequence') and ds.StructureSetROISequence:
            for roi_item in ds.StructureSetROISequence:
                if hasattr(roi_item, 'ROINumber'):
                    max_roi_number = max(max_roi_number, roi_item.ROINumber)
        
        # Initialize sequences if they don't exist
        if not hasattr(ds, 'StructureSetROISequence') or ds.StructureSetROISequence is None:
            ds.StructureSetROISequence = pydicom.Sequence()
        if not hasattr(ds, 'ROIContourSequence') or ds.ROIContourSequence is None:
            ds.ROIContourSequence = pydicom.Sequence()
        if not hasattr(ds, 'RTROIObservationsSequence') or ds.RTROIObservationsSequence is None:
            ds.RTROIObservationsSequence = pydicom.Sequence()
        
        # Separate structures into those with and without generation logic
        structures_with_logic = []
        structures_without_logic = []
        
        for additional_struct in additional_structures:
            if additional_struct.roi_label in roi_name_to_number_map:
                logger.warning(f"ROI '{additional_struct.roi_label}' already exists - skipping")
                continue
            
            if additional_struct.roi_generation_logic:
                structures_with_logic.append(additional_struct)
            else:
                structures_without_logic.append(additional_struct)
        
        # First, add empty ROIs for structures without generation logic
        empty_count = 0
        for additional_struct in structures_without_logic:
            roi_label = additional_struct.roi_label
            max_roi_number += 1
            roi_number = max_roi_number
            roi_name_to_number_map[roi_label] = roi_number
            
            # Parse color
            color_values = [255, 255, 0]  # Default yellow
            if additional_struct.roi_display_color:
                try:
                    color_parts = additional_struct.roi_display_color.split('\\')
                    if len(color_parts) == 3:
                        color_values = [int(part.strip()) for part in color_parts]
                except (ValueError, AttributeError):
                    logger.warning(f"Invalid color format for '{roi_label}'")
            
            # Add to StructureSetROISequence
            structure_set_roi = pydicom.Dataset()
            structure_set_roi.ROINumber = roi_number
            structure_set_roi.ReferencedFrameOfReferenceUID = ds.ReferencedFrameOfReferenceSequence[0].FrameOfReferenceUID if hasattr(ds, 'ReferencedFrameOfReferenceSequence') and ds.ReferencedFrameOfReferenceSequence else ""
            structure_set_roi.ROIName = roi_label
            structure_set_roi.ROIDescription = f"Empty ROI: {roi_label}"
            structure_set_roi.ROIGenerationAlgorithm = "MANUAL"
            ds.StructureSetROISequence.append(structure_set_roi)
            
            # Add to ROIContourSequence (empty)
            roi_contour = pydicom.Dataset()
            roi_contour.ReferencedROINumber = roi_number
            roi_contour.ROIDisplayColor = color_values
            roi_contour.ContourSequence = pydicom.Sequence()
            ds.ROIContourSequence.append(roi_contour)
            
            # Add to RTROIObservationsSequence
            roi_observation = pydicom.Dataset()
            roi_observation.ObservationNumber = roi_number
            roi_observation.ReferencedROINumber = roi_number
            roi_observation.ROIObservationLabel = roi_label
            roi_observation.RTROIInterpretedType = additional_struct.rt_roi_interpreted_type or "ORGAN"
            roi_observation.ROIInterpreter = ""
            ds.RTROIObservationsSequence.append(roi_observation)
            
            empty_count += 1
            logger.info(f"Added empty ROI #{roi_number}: '{roi_label}'")
        
        # Now process structures with generation logic
        if not structures_with_logic:
            logger.info(f"Additional structures summary - Empty ROIs: {empty_count}, Generated: 0")
            return
        
        # Load CT series and create RTStructBuilder for pipeline execution
        try:
            # Get CT instances
            instances = series_data.get('instances', [])
            if not instances:
                logger.warning("No CT instances found - cannot execute pipelines")
                logger.info(f"Additional structures summary - Empty ROIs: {empty_count}, Generated: 0")
                return
            
            # Load CT as SimpleITK image
            ct_image = load_ct_series_as_sitk_image(series_data)
            logger.info(f"Loaded CT image: {ct_image.GetSize()}")
            
            # Get series root path for RTStructBuilder
            series_root_path = series.series_root_path
            if not series_root_path or not os.path.exists(series_root_path):
                logger.warning(f"Series root path not found: {series_root_path}")
                logger.info(f"Additional structures summary - Empty ROIs: {empty_count}, Generated: 0")
                return
            
            # Save current RT Struct temporarily for RTStructBuilder
            temp_rtstruct_path = os.path.join(os.path.dirname(series_root_path), 'temp_rtstruct.dcm')
            ds.save_as(temp_rtstruct_path, write_like_original=False)
            
            # Create RTStructBuilder
            rtstruct = RTStructBuilder.create_from(
                dicom_series_path=series_root_path,
                rt_struct_path=temp_rtstruct_path
            )
            
            # Create pipeline executor
            executor = ProductionPipelineExecutor(rtstruct, ct_image)
            
            generated_count = 0
            failed_count = 0
            
            # Process each structure with generation logic
            for additional_struct in structures_with_logic:
                roi_label = additional_struct.roi_label
                
                # Parse color
                color = [255, 255, 0]  # Default yellow
                if additional_struct.roi_display_color:
                    try:
                        color_parts = additional_struct.roi_display_color.split('\\')
                        if len(color_parts) == 3:
                            color = [int(part.strip()) for part in color_parts]
                    except (ValueError, AttributeError):
                        logger.warning(f"Invalid color format for '{roi_label}'")
                
                # Execute pipeline
                logger.info(f"Executing pipeline for '{roi_label}'...")
                result = executor.execute_pipeline(additional_struct.roi_generation_logic)
                
                if result is None:
                    logger.error(f"Pipeline execution failed for '{roi_label}'")
                    failed_count += 1
                    continue
                
                # Add result to RT Struct
                if executor.add_result_to_rtstruct(roi_label, color):
                    generated_count += 1
                    roi_name_to_number_map[roi_label] = len(roi_name_to_number_map) + 1
                else:
                    logger.error(f"Failed to add '{roi_label}' to RT Struct")
                    failed_count += 1
            
            # Save the updated RT Struct back to the dataset
            rtstruct.save(temp_rtstruct_path)
            updated_ds = pydicom.dcmread(temp_rtstruct_path)
            
            # Copy the updated sequences back to original dataset
            ds.StructureSetROISequence = updated_ds.StructureSetROISequence
            ds.ROIContourSequence = updated_ds.ROIContourSequence
            ds.RTROIObservationsSequence = updated_ds.RTROIObservationsSequence
            
            # Clean up temp file
            if os.path.exists(temp_rtstruct_path):
                os.remove(temp_rtstruct_path)
            
            logger.info(f"Additional structures summary - Empty ROIs: {empty_count}, Generated: {generated_count}, Failed: {failed_count}")
            
        except Exception as e:
            logger.error(f"Error executing pipelines: {e}", exc_info=True)
            # Continue without failing the entire process
            logger.info(f"Additional structures summary - Empty ROIs: {empty_count}, Generated: 0 (pipeline execution failed)")
        
    except Exception as e:
        logger.error(f"Error adding additional structures to RT Structure Set: {str(e)}", exc_info=True)
        raise

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
            logger.info(f"Sanitized patient ID for filename: '{_mask_sensitive_data(patient_id, 'patient_id')}' -> '{safe_patient_id}'")
        filename = f"RS_{safe_patient_id}_DRAW_{timestamp}.dcm"
        output_path = os.path.join(output_dir, filename)
        
        # Save the reidentified file
        ds.save_as(output_path,enforce_file_format=True)

        logger.info(f"Exported reidentified RTStructure to: {_mask_sensitive_data(output_path, 'file_path')}")
        return output_path
        
    except Exception as e:
        logger.error(f"Error exporting reidentified file: {str(e)}")
        return None

def _update_successful_status(rt_import: RTStructureFileImport, output_path: str, series: DICOMSeries, ds: pydicom.Dataset) -> None:
    """Update database statuses after successful reidentification. Also add the SOP Instance UID, Series Instance UID, Study Instance UID, SOP Class UID from the reidentified RTStructureSet file."""
    try:
        # Extract UIDs from the reidentified RTStructure file (using the already-loaded dataset)
        sop_instance_uid = ds.SOPInstanceUID if hasattr(ds, 'SOPInstanceUID') else None
        series_instance_uid = ds.SeriesInstanceUID if hasattr(ds, 'SeriesInstanceUID') else None
        study_instance_uid = ds.StudyInstanceUID if hasattr(ds, 'StudyInstanceUID') else None
        sop_class_uid = ds.SOPClassUID if hasattr(ds, 'SOPClassUID') else None
        
        # Update RTStructureFileImport record with file path, datetime, and UIDs
        rt_import.reidentified_rt_structure_file_path = output_path
        rt_import.reidentified_rt_structure_file_export_datetime = timezone.now()
        rt_import.reidentified_rt_structure_file_sop_instance_uid = sop_instance_uid
        rt_import.reidentified_rt_structure_file_series_instance_uid = series_instance_uid
        rt_import.reidentified_rt_structure_file_study_instance_uid = study_instance_uid
        rt_import.reidentified_rt_structure_file_sop_class_uid = sop_class_uid
        
        rt_import.save(update_fields=[
            'reidentified_rt_structure_file_path',
            'reidentified_rt_structure_file_export_datetime',
            'reidentified_rt_structure_file_sop_instance_uid',
            'reidentified_rt_structure_file_series_instance_uid',
            'reidentified_rt_structure_file_study_instance_uid',
            'reidentified_rt_structure_file_sop_class_uid'
        ])
        
        logger.info(f"Stored RTStructure UIDs - SOP Instance: ***{sop_instance_uid[:8] if sop_instance_uid else 'None'}...{sop_instance_uid[-8:] if sop_instance_uid else ''}***, "
                   f"Series Instance: ***{series_instance_uid[:8] if series_instance_uid else 'None'}...{series_instance_uid[-8:] if series_instance_uid else ''}***, "
                   f"Study Instance: ***{study_instance_uid[:8] if study_instance_uid else 'None'}...{study_instance_uid[-8:] if study_instance_uid else ''}***")
        
        # Send RT Structure to export destination via C-STORE (if configured)
        logger.info("Checking for export destination configuration...")
        export_result = _send_rtstruct_to_export_destination(output_path, rt_import)
        
        if export_result['sent']:
            logger.info(f"RT Structure successfully exported to {export_result['node_name']} via C-STORE")
        elif export_result['error'] and export_result['error'] != 'No export destination configured':
            logger.warning(f"RT Structure export to remote node failed: {export_result['error']}")
            # Note: We don't fail the entire process if C-STORE export fails
            # The file is still saved locally and marked as exported
        
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

def _get_export_destination_nodes():
    """
    Get the list of remote DICOM nodes configured as export destinations.
    Returns primary destination first, then fallback destinations in priority order.
    
    Returns:
        List of RemoteDicomNode instances in order of priority (primary first, then fallbacks)
    """
    try:
        nodes = []
        
        # First, get primary export destination
        primary_node = RemoteDicomNode.objects.filter(
            is_primary_export_destination=True,
            is_active=True
        ).first()
        
        if primary_node:
            nodes.append(primary_node)
            logger.info(f"Found primary export destination: {primary_node.name} ({primary_node.host}:{primary_node.port})")
        else:
            logger.warning("No primary export destination configured")
        
        # Then, get fallback export destinations ordered by priority (ascending)
        fallback_nodes = RemoteDicomNode.objects.filter(
            is_fallback_export_destination=True,
            is_active=True,
            fallback_export_destination_priority__isnull=False
        ).order_by('fallback_export_destination_priority')
        
        if fallback_nodes.exists():
            for node in fallback_nodes:
                nodes.append(node)
                logger.info(f"Found fallback export destination (priority {node.fallback_export_destination_priority}): {node.name} ({node.host}:{node.port})")
        
        if not nodes:
            logger.info("No export destination nodes configured")
        
        return nodes
    except Exception as e:
        logger.error(f"Error retrieving export destination nodes: {str(e)}")
        return []


def _send_rtstruct_to_export_destination(file_path: str, rt_import: RTStructureFileImport) -> Dict[str, Any]:
    """
    Send reidentified RT Structure file to configured export destinations via C-STORE.
    Tries primary destination first, then fallback destinations in priority order.
    
    Args:
        file_path: Path to the reidentified RT Structure file
        rt_import: RTStructureFileImport record
        
    Returns:
        Dict with success status and details
    """
    result = {
        'success': False,
        'sent': False,
        'error': None,
        'node_name': None,
        'attempted_nodes': [],
        'failed_nodes': []
    }
    
    try:
        # Get export destination nodes (primary + fallbacks in priority order)
        export_nodes = _get_export_destination_nodes()
        
        if not export_nodes:
            logger.info("No export destination configured - skipping C-STORE export")
            result['error'] = 'No export destination configured'
            return result
        
        # Validate file exists
        if not os.path.exists(file_path):
            logger.error(f"RT Structure file not found for C-STORE export: {_mask_sensitive_data(file_path, 'file_path')}")
            result['error'] = 'File not found'
            return result
        
        # Try each export destination in order (primary first, then fallbacks by priority)
        for idx, export_node in enumerate(export_nodes):
            node_type = "primary" if export_node.is_primary_export_destination else f"fallback (priority {export_node.fallback_export_destination_priority})"
            result['attempted_nodes'].append({
                'name': export_node.name,
                'type': node_type
            })
            
            try:
                # Send file via C-STORE
                logger.info(f"Attempting to send RT Structure file to {node_type} destination: {export_node.name}")
                logger.info(f"File: {os.path.basename(file_path)}")
                
                cstore_result = send_dicom_files_to_node(
                    remote_node=export_node,
                    file_paths=[file_path],
                    calling_ae_title=None  # Will use default from DicomServerConfig
                )
                
                if cstore_result['success'] and cstore_result['sent_count'] > 0:
                    result['success'] = True
                    result['sent'] = True
                    result['node_name'] = export_node.name
                    logger.info(f"Successfully sent RT Structure to {export_node.name} ({node_type}) via C-STORE")
                    
                    # Update RTStructureFileImport with export info
                    rt_import.exported_to_remote_node = True
                    rt_import.export_node_name = export_node.name
                    rt_import.export_datetime = timezone.now()
                    rt_import.save(update_fields=['exported_to_remote_node', 'export_node_name', 'export_datetime'])
                    
                    # Success! No need to try fallback nodes
                    return result
                else:
                    # Failed to send to this node, try next one
                    error_msg = cstore_result.get('error_message', 'C-STORE failed')
                    result['failed_nodes'].append({
                        'name': export_node.name,
                        'type': node_type,
                        'error': error_msg
                    })
                    logger.warning(f"Failed to send RT Structure to {export_node.name} ({node_type}): {error_msg}")
                    logger.warning(f"C-STORE details - Sent: {cstore_result['sent_count']}, Failed: {cstore_result['failed_count']}")
                    
                    # Continue to next node if available
                    if idx < len(export_nodes) - 1:
                        logger.info(f"Trying next export destination...")
                    
            except Exception as node_error:
                # Error with this specific node, try next one
                error_msg = str(node_error)
                result['failed_nodes'].append({
                    'name': export_node.name,
                    'type': node_type,
                    'error': error_msg
                })
                logger.error(f"Error sending RT Structure to {export_node.name} ({node_type}): {error_msg}", exc_info=True)
                
                # Continue to next node if available
                if idx < len(export_nodes) - 1:
                    logger.info(f"Trying next export destination...")
        
        # If we get here, all nodes failed
        result['error'] = f"Failed to send to all configured export destinations ({len(export_nodes)} nodes attempted)"
        logger.error(result['error'])
        logger.error(f"Failed nodes: {result['failed_nodes']}")
        
    except Exception as e:
        result['error'] = str(e)
        logger.error(f"Error in export destination workflow: {str(e)}", exc_info=True)
    
    return result


def _cleanup_temp_file(file_path: str) -> None:
    """Clean up temporary RTStructure file."""
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"Cleaned up temporary file: {file_path}")
    except Exception as e:
        logger.warning(f"Failed to clean up temporary file {file_path}: {str(e)}")