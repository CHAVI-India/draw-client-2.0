# This set of functions will be used to collect statistics about the entire DICOM Processing Chain.
# The statistics will be stored in the Statistics model.
# The key parameters and their values will be collected from the following sources:
# - Number of unqiue patients since the last run (data from Patients table)
# - Number of unique DICOM Studies since the last run (data from DicomStudy table)
# - Number of unique DICOM Series since the last run (data from DICOMSeries table)
# - Number of unique DICOM Instances since the last run (data from DICOMInstance table)
# - Number of unique RTStruct files downloaded since the last run (data from RTStructFile table)
# - Number of series with matching rulesets since the last run (data from DICOMSeries table)
# - Number of series with failed segmentation since the last run (data from DICOMSeries table)
# - Number of series with failed deidentification since the last run (data from DICOMSeries table)
# - Number of series with failed export since the last run (data from DICOMFileExport table)
# - Number of series exported successfully since the last run (data from DICOMFileExport table)
# - Number of series completing segmentation succesfully since the last run (data from DICOMSeries table)
# - Total Time taken to complete segmentation for all cases which have completed segmentation since the last run. (obtained by subtracting the time taken from the time of receipt of RTstructureset in the RTStructFile table from the time of receipt of the RTStructFile in the RTStructFile table from the time of successful upload to the server).
# This will run as a celery beat task every 30 minute. 


from dicom_handler.models import *
from django.db.models import Count, Avg
from django.utils import timezone
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)

def get_last_run_timestamp():
    """
    Get the timestamp of the last statistics run.
    If no previous run exists, return a timestamp from 30 minutes ago.
    """
    last_run = Statistics.objects.order_by('-created_at').first()
    if last_run:
        return last_run.created_at
    return timezone.now() - timedelta(minutes=30)

def gather_statistics():
    """
    Collect and store statistics about the DICOM processing chain.
    This function is designed to be run as a Celery beat task every 30 minutes.
    """
    try:
        last_run = get_last_run_timestamp()
        now = timezone.now()
        stats = []
        
        # 1. Count unique patients since last run
        unique_patients = Patient.objects.filter(created_at__gt=last_run).count()
        stats.append(Statistics(
            parameter_name='unique_patients_since_last_run',
            parameter_value=str(unique_patients)
        ))

        # 2. Count unique DICOM studies since last run
        unique_studies = DICOMStudy.objects.filter(created_at__gt=last_run).count()
        stats.append(Statistics(
            parameter_name='unique_dicom_studies_since_last_run',
            parameter_value=str(unique_studies)
        ))
        
        # 3. Count unique DICOM series since last run
        unique_series = DICOMSeries.objects.filter(created_at__gt=last_run).count()
        stats.append(Statistics(
            parameter_name='unique_dicom_series_since_last_run',
            parameter_value=str(unique_series)
        ))
        
        # 4. Count unique DICOM instances since last run
        unique_instances = DICOMInstance.objects.filter(created_at__gt=last_run).count()
        stats.append(Statistics(
            parameter_name='unique_dicom_instances_since_last_run',
            parameter_value=str(unique_instances)
        ))
        
        # 5. Count unique RTStruct files downloaded since last run
        rt_structs = RTStructureFileImport.objects.filter(created_at__gt=last_run).count()
        stats.append(Statistics(
            parameter_name='rt_struct_files_downloaded_since_last_run',
            parameter_value=str(rt_structs)
        ))
        
        # 6. Count series with matching rulesets since last run
        matched_series = DICOMSeries.objects.filter(
            created_at__gt=last_run,
            matched_rule_sets__isnull=False
        ).distinct().count()
        stats.append(Statistics(
            parameter_name='series_with_matching_rulesets_since_last_run',
            parameter_value=str(matched_series)
        ))
        
        # 7. Count series with failed segmentation since last run
        failed_segmentation = DICOMSeries.objects.filter(
            updated_at__gt=last_run,
            series_processsing_status=ProcessingStatus.FAILED_TRANSFER_TO_DRAW_SERVER
        ).count()
        stats.append(Statistics(
            parameter_name='series_with_failed_segmentation_since_last_run',
            parameter_value=str(failed_segmentation)
        ))
        
        # 8. Count series with failed deidentification since last run
        failed_deidentification = DICOMSeries.objects.filter(
            updated_at__gt=last_run,
            series_processsing_status=ProcessingStatus.DEIDENTIFICATION_FAILED
        ).count()
        stats.append(Statistics(
            parameter_name='series_with_failed_deidentification_since_last_run',
            parameter_value=str(failed_deidentification)
        ))
        
        # 9. Count series with failed export since last run
        failed_exports = DICOMFileExport.objects.filter(
            updated_at__gt=last_run,
            deidentified_zip_file_transfer_status=DICOMFileTransferStatus.FAILED
        ).count()
        stats.append(Statistics(
            parameter_name='series_with_failed_export_since_last_run',
            parameter_value=str(failed_exports)
        ))
        
        # 10. Count series exported successfully since last run
        successful_exports = DICOMFileExport.objects.filter(
            updated_at__gt=last_run,
            deidentified_zip_file_transfer_status=DICOMFileTransferStatus.COMPLETED
        ).count()
        stats.append(Statistics(
            parameter_name='series_exported_successfully_since_last_run',
            parameter_value=str(successful_exports)
        ))
        
        # 11. Count series completing segmentation successfully since last run
        completed_segmentation = DICOMSeries.objects.filter(
            updated_at__gt=last_run,
            series_processsing_status=ProcessingStatus.RTSTRUCTURE_EXPORTED
        ).count()
        stats.append(Statistics(
            parameter_name='series_completing_segmentation_since_last_run',
            parameter_value=str(completed_segmentation)
        ))
        
        # 12. Calculate average time to complete segmentation for successfully processed cases
        completed_cases = DICOMSeries.objects.filter(
            series_processsing_status=ProcessingStatus.RTSTRUCTURE_EXPORTED,
            updated_at__gt=last_run
        )
        
        # Get the average processing time in seconds
        avg_processing_time = 0
        if completed_cases.exists():
            total_seconds = 0
            for case in completed_cases:
                try:
                    # Get the export record for this series
                    export = DICOMFileExport.objects.filter(
                        deidentified_series_instance_uid=case
                    ).order_by('created_at').first()
                    
                    # Get the RT struct file import
                    rt_struct = RTStructureFileImport.objects.filter(
                        deidentified_series_instance_uid=case
                    ).order_by('-created_at').first()
                    
                    if export and rt_struct and export.deidentified_zip_file_transfer_datetime:
                        processing_time = (rt_struct.received_rt_structure_file_download_datetime - 
                                         export.deidentified_zip_file_transfer_datetime).total_seconds()
                        total_seconds += processing_time
                except Exception as e:
                    logger.error(f"Error calculating processing time for series {case.id}: {str(e)}")
                    continue
            
            if completed_cases.count() > 0:
                avg_processing_time = total_seconds / completed_cases.count()
        
        stats.append(Statistics(
            parameter_name='average_segmentation_processing_time_seconds_since_last_run',
            parameter_value=str(round(avg_processing_time, 2))
        ))
        
        # Save all statistics in a single transaction
        Statistics.objects.bulk_create(stats)
        
        logger.info(f"Successfully collected and stored {len(stats)} DICOM statistics.")
        logger.info(f"Unique Patients since last run: {unique_patients}")
        logger.info(f"Unique DICOM Studies since last run: {unique_studies}")
        logger.info(f"Unique DICOM Series since last run: {unique_series}")
        logger.info(f"Unique DICOM Instances since last run: {unique_instances}")
        logger.info(f"RT Struct Files Downloaded since last run: {rt_structs}")
        logger.info(f"Series with Matching Rulesets since last run: {matched_series}")
        logger.info(f"Series with Failed Segmentation since last run: {failed_segmentation}")
        logger.info(f"Series with Failed Deidentification since last run: {failed_deidentification}")
        logger.info(f"Series with Failed Export since last run: {failed_exports}")
        logger.info(f"Series Exported Successfully since last run: {successful_exports}")
        logger.info(f"Series Completing Segmentation Successfully since last run: {completed_segmentation}")
        logger.info(f"Average Segmentation Processing Time (seconds) since last run: {avg_processing_time}")
        logger.info(f"Series with Failed Segmentation since last run: {failed_segmentation}")
        logger.info(f"Series with Failed Deidentification since last run: {failed_deidentification}")
        logger.info(f"Series with Failed Export since last run: {failed_exports}")
        logger.info(f"Series Exported Successfully since last run: {successful_exports}")
        logger.info(f"Series Completing Segmentation Successfully since last run: {completed_segmentation}")
        logger.info(f"Average Segmentation Processing Time (seconds) since last run: {avg_processing_time}")
        return True
        
    except Exception as e:
        logger.error(f"Error gathering DICOM statistics: {str(e)}", exc_info=True)
        return False
