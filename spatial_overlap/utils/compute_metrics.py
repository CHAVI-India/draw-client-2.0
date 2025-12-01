"""
Utility functions for computing spatial overlap metrics between RT Structure Sets.
"""
import numpy as np
import pydicom
from rt_utils import RTStructBuilder
import logging
import os

from .metrics import (
    dice_similarity,
    jaccard_similarity,
    mean_surface_distance,
    hausdorff_distance_95,
    volume_overlap_error,
    variation_of_information,
    cosine_similarity,
    added_path_length,
    surface_dsc,
    mean_distance_to_conformity,
    undercontouring_mean_distance_to_conformity,
    overcontouring_mean_distance_to_conformity,
)

logger = logging.getLogger(__name__)


def extract_roi_mask_from_rtstruct(rtstruct_file_path, roi_name):
    """
    Extract 3D binary mask for a specific ROI from RT Structure Set file.
    
    Args:
        rtstruct_file_path (str): Path to the RT Structure Set DICOM file.
        roi_name (str): Name of the ROI to extract.
    
    Returns:
        numpy.ndarray: 3D binary mask of the ROI, or None if extraction fails.
    """
    try:
        # Load the RT Structure Set file
        ds = pydicom.dcmread(rtstruct_file_path)
        
        # Find the ROI by name
        roi_number = None
        if hasattr(ds, 'StructureSetROISequence'):
            for roi in ds.StructureSetROISequence:
                if roi.ROIName == roi_name:
                    roi_number = roi.ROINumber
                    break
        
        if roi_number is None:
            logger.error(f"ROI '{roi_name}' not found in RT Structure Set")
            return None
        
        # Extract contour data
        if not hasattr(ds, 'ROIContourSequence'):
            logger.error("No ROI Contour Sequence found in RT Structure Set")
            return None
        
        # Find the contour for this ROI
        contour_sequence = None
        for roi_contour in ds.ROIContourSequence:
            if roi_contour.ReferencedROINumber == roi_number:
                contour_sequence = roi_contour
                break
        
        if contour_sequence is None or not hasattr(contour_sequence, 'ContourSequence'):
            logger.warning(f"No contours found for ROI '{roi_name}'")
            return None
        
        # Get referenced series UID to load the image series
        referenced_series_uid = None
        if hasattr(ds, 'ReferencedFrameOfReferenceSequence'):
            for ref_frame in ds.ReferencedFrameOfReferenceSequence:
                if hasattr(ref_frame, 'RTReferencedStudySequence'):
                    for ref_study in ref_frame.RTReferencedStudySequence:
                        if hasattr(ref_study, 'RTReferencedSeriesSequence'):
                            for ref_series in ref_study.RTReferencedSeriesSequence:
                                if hasattr(ref_series, 'SeriesInstanceUID'):
                                    referenced_series_uid = ref_series.SeriesInstanceUID
                                    break
        
        # Extract contour points and create mask
        # This is a simplified version - in production you'd need the actual image series
        # to properly create the 3D mask with correct dimensions and spacing
        
        contours = []
        for contour in contour_sequence.ContourSequence:
            if hasattr(contour, 'ContourData'):
                # ContourData is a flat list of x,y,z coordinates
                points = np.array(contour.ContourData).reshape(-1, 3)
                contours.append(points)
        
        if not contours:
            logger.warning(f"No contour data found for ROI '{roi_name}'")
            return None
        
        # For now, return the contour points
        # In a full implementation, you would:
        # 1. Load the referenced image series
        # 2. Create a 3D volume with the same dimensions
        # 3. Rasterize the contours onto the volume
        # 4. Return the binary mask
        
        logger.info(f"Extracted {len(contours)} contour slices for ROI '{roi_name}'")
        return contours
        
    except Exception as e:
        logger.error(f"Error extracting ROI mask: {str(e)}")
        return None


def prepare_dicom_series_for_rtutils(series_instance_uid):
    """
    Prepare DICOM series from database for rt-utils by creating a temporary directory
    with properly formatted DICOM files.
    
    Args:
        series_instance_uid (str): Series Instance UID to retrieve from database.
    
    Returns:
        tuple: (temp_dir_path, cleanup_function) or (None, None) if preparation fails.
    """
    try:
        from dicom_handler.models import DICOMSeries, DICOMInstance
        import tempfile
        import shutil
        
        # Get the series from database
        series = DICOMSeries.objects.filter(series_instance_uid=series_instance_uid).first()
        if not series:
            logger.error(f"Series not found in database: {series_instance_uid}")
            return None, None
        
        # Get all instances for this series
        instances = DICOMInstance.objects.filter(
            series_instance_uid=series
        ).order_by('sop_instance_uid')
        
        if not instances.exists():
            logger.error(f"No instances found for series: {series_instance_uid}")
            return None, None
        
        # Create temporary directory
        temp_dir = tempfile.mkdtemp(prefix='spatial_overlap_')
        logger.info(f"Created temporary directory: {temp_dir}")
        
        # Read DICOM metadata to get proper ordering
        instance_metadata = []
        for instance in instances:
            if instance.instance_path and os.path.exists(instance.instance_path):
                try:
                    ds = pydicom.dcmread(instance.instance_path, stop_before_pixels=True, force=True)
                    instance_number = int(ds.InstanceNumber) if hasattr(ds, 'InstanceNumber') else 0
                    slice_location = float(ds.SliceLocation) if hasattr(ds, 'SliceLocation') else 0.0
                    image_position = ds.ImagePositionPatient[2] if hasattr(ds, 'ImagePositionPatient') else 0.0
                    
                    instance_metadata.append({
                        'instance': instance,
                        'instance_number': instance_number,
                        'slice_location': slice_location,
                        'image_position': image_position,
                    })
                except Exception as e:
                    logger.warning(f"Failed to read DICOM metadata for {instance.sop_instance_uid}: {e}")
                    continue
        
        if not instance_metadata:
            logger.error(f"No valid DICOM instances found for series: {series_instance_uid}")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return None, None
        
        # Sort by instance number first, then by slice location/image position
        instance_metadata.sort(key=lambda x: (x['instance_number'], x['slice_location'], x['image_position']))
        
        # Save sorted files to temp directory using pydicom save_as with enforce_file_format
        saved_count = 0
        for idx, meta in enumerate(instance_metadata):
            instance = meta['instance']
            temp_file = os.path.join(temp_dir, f'instance_{idx:04d}.dcm')
            try:
                # Read the DICOM file and save with proper format enforcement
                ds = pydicom.dcmread(instance.instance_path, force=True)
                ds.save_as(temp_file, enforce_file_format=True)
                saved_count += 1
            except Exception as e:
                logger.error(f"Failed to save DICOM file {instance.sop_instance_uid}: {e}")
                continue
        
        if saved_count == 0:
            logger.error(f"Failed to save any DICOM files for series: {series_instance_uid}")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return None, None
        
        logger.info(f"Prepared {saved_count} DICOM files in temporary directory")
        
        # Return temp directory and cleanup function
        def cleanup():
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
                logger.info(f"Cleaned up temporary directory: {temp_dir}")
            except Exception as e:
                logger.warning(f"Failed to cleanup temporary directory: {e}")
        
        return temp_dir, cleanup
        
    except Exception as e:
        logger.error(f"Error preparing DICOM series: {str(e)}")
        return None, None


def extract_roi_mask_with_rtutils(rtstruct_file_path, series_instance_uid, roi_name):
    """
    Extract 3D binary mask for a specific ROI using rt-utils library.
    This method reads DICOM instances from the database and creates a temporary directory.
    
    Args:
        rtstruct_file_path (str): Path to the RT Structure Set DICOM file.
        series_instance_uid (str): Series Instance UID to retrieve DICOM images from database.
        roi_name (str): Name of the ROI to extract.
    
    Returns:
        numpy.ndarray: 3D binary mask of the ROI with shape (height, width, num_slices),
                      or None if extraction fails.
    """
    temp_dir = None
    cleanup = None
    
    try:
        from rt_utils import RTStructBuilder
        import shutil
        
        logger.info(f"Extracting mask for ROI '{roi_name}' from series {series_instance_uid}")
        
        # Prepare DICOM series from database
        temp_dir, cleanup = prepare_dicom_series_for_rtutils(series_instance_uid)
        if not temp_dir:
            logger.error("Failed to prepare DICOM series from database")
            return None
        
        # Prepare RT Structure file in temp directory
        temp_rt_struct = os.path.join(temp_dir, 'rtstruct.dcm')
        try:
            # Read and save RT Structure with proper format enforcement
            rt_ds = pydicom.dcmread(rtstruct_file_path, force=True)
            rt_ds.save_as(temp_rt_struct, enforce_file_format=True)
        except Exception as e:
            logger.error(f"Failed to save RT Structure file: {e}")
            if cleanup:
                cleanup()
            return None
        
        logger.info(f"Loading RT Structure from {temp_rt_struct}")
        logger.info(f"Using DICOM series from {temp_dir}")
        
        # Create RTStruct object from the DICOM series and RT Structure file
        rtstruct = RTStructBuilder.create_from(
            dicom_series_path=temp_dir,
            rt_struct_path=temp_rt_struct
        )
        
        # Get the 3D binary mask for the specified ROI
        mask_3d = rtstruct.get_roi_mask_by_name(roi_name)
        
        logger.info(f"Successfully extracted mask for ROI '{roi_name}' with shape {mask_3d.shape}")
        
        # Cleanup temporary directory
        if cleanup:
            cleanup()
        
        return mask_3d
        
    except Exception as e:
        logger.error(f"Error extracting ROI mask with rt-utils: {str(e)}")
        # Cleanup on error
        if cleanup:
            cleanup()
        return None


def compute_all_metrics(volume1, volume2, spacing=(1.0, 1.0, 1.0)):
    """
    Compute all available spatial overlap metrics between two binary volumes.
    
    Args:
        volume1 (numpy.ndarray): First binary volume.
        volume2 (numpy.ndarray): Second binary volume.
        spacing (tuple): Voxel spacing in (x, y, z) dimensions in mm. Default is (1.0, 1.0, 1.0).
    
    Returns:
        dict: Dictionary containing all computed metrics with their values.
              Keys correspond to ComparisionTypeChoices values.
    """
    results = {}
    
    try:
        # Dice Similarity Coefficient
        results['dsc'] = dice_similarity(volume1, volume2)
        logger.info(f"Computed DSC: {results['dsc']:.4f}")
    except Exception as e:
        logger.error(f"Error computing DSC: {str(e)}")
        results['dsc'] = None
    
    try:
        # Jaccard Similarity Coefficient
        results['jsc'] = jaccard_similarity(volume1, volume2)
        logger.info(f"Computed JSC: {results['jsc']:.4f}")
    except Exception as e:
        logger.error(f"Error computing JSC: {str(e)}")
        results['jsc'] = None
    
    try:
        # Hausdorff Distance 95th percentile
        results['hd95'] = hausdorff_distance_95(volume1, volume2)
        logger.info(f"Computed HD95: {results['hd95']:.4f}")
    except Exception as e:
        logger.error(f"Error computing HD95: {str(e)}")
        results['hd95'] = None
    
    try:
        # Mean Surface Distance
        results['msd'] = mean_surface_distance(volume1, volume2)
        logger.info(f"Computed MSD: {results['msd']:.4f}")
    except Exception as e:
        logger.error(f"Error computing MSD: {str(e)}")
        results['msd'] = None
    
    try:
        # Volume Overlap Error
        results['voe'] = volume_overlap_error(volume1, volume2)
        logger.info(f"Computed VOE: {results['voe']:.4f}")
    except Exception as e:
        logger.error(f"Error computing VOE: {str(e)}")
        results['voe'] = None
    
    try:
        # Variation of Information
        results['vi'] = variation_of_information(volume1, volume2)
        logger.info(f"Computed VI: {results['vi']:.4f}")
    except Exception as e:
        logger.error(f"Error computing VI: {str(e)}")
        results['vi'] = None
    
    try:
        # Cosine Similarity
        results['cs'] = cosine_similarity(volume1, volume2)
        logger.info(f"Computed CS: {results['cs']:.4f}")
    except Exception as e:
        logger.error(f"Error computing CS: {str(e)}")
        results['cs'] = None
    
    try:
        # Added Path Length
        results['apl'] = added_path_length(volume1, volume2, distance_threshold_mm=3, spacing=spacing)
        logger.info(f"Computed APL: {results['apl']:.4f} mm")
    except Exception as e:
        logger.error(f"Error computing APL: {str(e)}")
        results['apl'] = None
    
    try:
        # Surface Dice Similarity Coefficient
        results['surface_dsc'] = surface_dsc(volume1, volume2, tau=3.0, spacing=spacing)
        logger.info(f"Computed Surface DSC: {results['surface_dsc']:.4f}")
    except Exception as e:
        logger.error(f"Error computing Surface DSC: {str(e)}")
        results['surface_dsc'] = None
    
    # Mean Distance to Conformity metrics with slice-wise data
    try:
        # Compute MDC with detailed slice-wise data
        mdc_detailed = mean_distance_to_conformity(volume1, volume2, spacing=spacing, return_detailed=True)
        
        results['mdc'] = {
            'value': mdc_detailed['mdc'],
            'slice_data': mdc_detailed['slice_data']
        }
        logger.info(f"Computed MDC: {mdc_detailed['mdc']:.4f} mm")
        
        results['umdc'] = {
            'value': mdc_detailed['under_mdc'],
            'slice_data': mdc_detailed['slice_data']
        }
        logger.info(f"Computed Under-MDC: {mdc_detailed['under_mdc']:.4f} mm")
        
        results['omdc'] = {
            'value': mdc_detailed['over_mdc'],
            'slice_data': mdc_detailed['slice_data']
        }
        logger.info(f"Computed Over-MDC: {mdc_detailed['over_mdc']:.4f} mm")
        
    except Exception as e:
        logger.error(f"Error computing MDC metrics: {str(e)}")
        results['mdc'] = None
        results['umdc'] = None
        results['omdc'] = None
    
    return results


def get_series_instance_uid_from_rtstruct(rtstruct_file_obj):
    """
    Get the series instance UID from the RT Structure file's referenced series.
    
    Args:
        rtstruct_file_obj: RTStructureSetFile model instance.
    
    Returns:
        str: Series Instance UID, or None if not found.
    """
    try:
        from dicom_handler.models import DICOMSeries
        
        ref_uid = rtstruct_file_obj.referenced_series_instance_uid
        if not ref_uid:
            logger.warning(f"No referenced series UID found for RT Structure {rtstruct_file_obj.id}")
            return None
        
        # Verify the series exists in the database
        series = DICOMSeries.objects.filter(series_instance_uid=ref_uid).first()
        if series:
            logger.info(f"Found DICOM series in database: {ref_uid}")
            return ref_uid
        
        logger.warning(f"No DICOM series found in database for referenced UID: {ref_uid}")
        return None
        
    except Exception as e:
        logger.error(f"Error finding series instance UID: {str(e)}")
        return None


def compute_comparison_metrics(comparison_obj, dicom_series_path_1=None, dicom_series_path_2=None):
    """
    Compute all metrics for a given RTStructureFileComparison object.
    
    Args:
        comparison_obj: RTStructureFileComparison model instance.
        dicom_series_path_1 (str, optional): Path to DICOM series for first RT Structure.
        dicom_series_path_2 (str, optional): Path to DICOM series for second RT Structure.
    
    Returns:
        dict: Dictionary of computed metrics, or None if computation fails.
    """
    try:
        # Get the two VOIs being compared
        voi1 = comparison_obj.first_rtstructure
        voi2 = comparison_obj.second_rtstructure
        
        logger.info(f"Computing metrics for comparison: {voi1.roi_name} vs {voi2.roi_name}")
        
        # Check if RT Structure file paths exist
        if not voi1.rtstructure_set_file.rtstructure_file_path:
            logger.error(f"No RT Structure file path associated with {voi1.rtstructure_set_file.structure_set_label}")
            return None
        
        if not voi2.rtstructure_set_file.rtstructure_file_path:
            logger.error(f"No RT Structure file path associated with {voi2.rtstructure_set_file.structure_set_label}")
            return None
        
        # Get the RT Structure Set file paths from working directory
        rtstruct_file_1 = voi1.rtstructure_set_file.rtstructure_file_path
        rtstruct_file_2 = voi2.rtstructure_set_file.rtstructure_file_path
        
        logger.info(f"RT Structure file 1: {rtstruct_file_1}")
        logger.info(f"RT Structure file 2: {rtstruct_file_2}")
        
        # Use working directory which contains DICOM images and RT Structure files
        working_dir_1 = voi1.rtstructure_set_file.working_directory
        working_dir_2 = voi2.rtstructure_set_file.working_directory
        
        # Both RT Structures should share the same working directory
        if working_dir_1 != working_dir_2:
            logger.warning(f"RT Structures have different working directories: {working_dir_1} vs {working_dir_2}")
        
        if not working_dir_1 or not os.path.exists(working_dir_1):
            logger.error(f"Working directory not found: {working_dir_1}")
            return None
        
        logger.info(f"Using working directory: {working_dir_1}")
        
        # Extract masks using rt-utils with DICOM images from working directory
        logger.info("Using rt-utils for mask extraction with DICOM images from working directory")
        
        # Use rt-utils to load RT Structure and extract masks
        # The working directory contains all DICOM images and RT Structure files
        try:
            from rt_utils import RTStructBuilder
            
            # Load RT Structure 1 with DICOM images from working directory
            logger.info(f"Loading RT Structure 1 from: {rtstruct_file_1}")
            rtstruct1 = RTStructBuilder.create_from(
                dicom_series_path=working_dir_1,
                rt_struct_path=rtstruct_file_1
            )
            mask1 = rtstruct1.get_roi_mask_by_name(voi1.roi_name)
            logger.info(f"Extracted mask 1 with shape: {mask1.shape}")
            
            # Load RT Structure 2 with DICOM images from working directory
            logger.info(f"Loading RT Structure 2 from: {rtstruct_file_2}")
            rtstruct2 = RTStructBuilder.create_from(
                dicom_series_path=working_dir_2 if working_dir_2 != working_dir_1 else working_dir_1,
                rt_struct_path=rtstruct_file_2
            )
            mask2 = rtstruct2.get_roi_mask_by_name(voi2.roi_name)
            logger.info(f"Extracted mask 2 with shape: {mask2.shape}")
            
            # Extract voxel spacing from DICOM images for APL calculation
            # Get the first DICOM file from the working directory
            dicom_files = [f for f in os.listdir(working_dir_1) if f.endswith('.dcm') and not f.startswith('autoseg') and not f.startswith('reference')]
            if dicom_files:
                first_dicom = pydicom.dcmread(os.path.join(working_dir_1, dicom_files[0]), force=True)
                # Get pixel spacing (x, y) and slice thickness (z)
                pixel_spacing = getattr(first_dicom, 'PixelSpacing', [1.0, 1.0])
                slice_thickness = getattr(first_dicom, 'SliceThickness', 1.0)
                spacing = (float(pixel_spacing[0]), float(pixel_spacing[1]), float(slice_thickness))
                logger.info(f"Extracted voxel spacing: {spacing} mm")
            else:
                spacing = (1.0, 1.0, 1.0)
                logger.warning("Could not extract voxel spacing from DICOM, using default (1.0, 1.0, 1.0)")
            
        except Exception as e:
            logger.error(f"Failed to extract masks using rt-utils: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
        
        if mask1 is None or mask2 is None:
            logger.error("Failed to extract masks for comparison")
            return None
        
        # Ensure masks have the same shape
        if isinstance(mask1, np.ndarray) and isinstance(mask2, np.ndarray):
            if mask1.shape != mask2.shape:
                logger.error(f"Mask shapes do not match: {mask1.shape} vs {mask2.shape}")
                return None
            
            # Compute all metrics with spacing information
            metrics = compute_all_metrics(mask1, mask2, spacing=spacing)
            return metrics
        else:
            logger.error("Masks are not numpy arrays - cannot compute metrics")
            return None
        
    except Exception as e:
        logger.error(f"Error computing comparison metrics: {str(e)}")
        return None
