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
                
                # Check if the requestor accepts this SOP Class and Transfer Syntax
                # Get the accepted presentation contexts from the association
                sop_class_uid = ds.SOPClassUID
                current_transfer_syntax = ds.file_meta.TransferSyntaxUID if hasattr(ds, 'file_meta') else None
                
                # Find an accepted presentation context for this SOP Class
                accepted_contexts = [cx for cx in event.assoc.accepted_contexts 
                                   if cx.abstract_syntax == sop_class_uid]
                
                if not accepted_contexts:
                    logger.warning(f"No accepted context for SOP Class {sop_class_uid}, skipping file")
                    failure_count += 1
                    continue
                
                # Get the first accepted transfer syntax for this SOP Class
                accepted_transfer_syntax = accepted_contexts[0].transfer_syntax[0]
                
                # If the file's transfer syntax doesn't match, convert it
                if current_transfer_syntax and current_transfer_syntax != accepted_transfer_syntax:
                    logger.debug(f"Converting from {current_transfer_syntax} to {accepted_transfer_syntax}")
                    # Check if the dataset is compressed and needs decompression
                    try:
                        # Only decompress if the current transfer syntax is compressed
                        compressed_syntaxes = [
                            '1.2.840.10008.1.2.4.50',  # JPEG Baseline
                            '1.2.840.10008.1.2.4.51',  # JPEG Extended
                            '1.2.840.10008.1.2.4.57',  # JPEG Lossless
                            '1.2.840.10008.1.2.4.70',  # JPEG Lossless SV1
                            '1.2.840.10008.1.2.4.90',  # JPEG 2000 Lossless
                            '1.2.840.10008.1.2.4.91',  # JPEG 2000
                            '1.2.840.10008.1.2.5',     # RLE Lossless
                        ]
                        if current_transfer_syntax in compressed_syntaxes:
                            ds.decompress()
                            logger.debug(f"Decompressed dataset from {current_transfer_syntax}")
                    except Exception as e:
                        logger.debug(f"Decompression not needed or failed: {str(e)}")
                    
                    # Update the transfer syntax in file_meta
                    if hasattr(ds, 'file_meta'):
                        ds.file_meta.TransferSyntaxUID = accepted_transfer_syntax
                
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
                        logger.warning(f"C-STORE failed with status: {status.Status:#06x}")
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
    Uses DICOMInstance model for accurate file tracking with SOP Instance UIDs.
    
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
        
        # Apply filters based on query parameters
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
        
        # Limit results to prevent overwhelming the system
        queryset = queryset[:1000]
        
        # Collect file paths from instances
        for instance in queryset:
            if instance.instance_path and os.path.exists(instance.instance_path):
                matches.append(instance.instance_path)
            else:
                logger.warning(f"File not found for SOP Instance UID: {instance.sop_instance_uid}")
        
        logger.info(f"C-GET found {len(matches)} matching files from database")
        return matches
        
    except Exception as e:
        logger.error(f"Error querying database for C-GET: {str(e)}")
        return []


