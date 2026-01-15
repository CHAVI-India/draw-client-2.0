"""
DICOM Viewer Views with RT Structure Overlay
Provides interactive visualization of DICOM images with RT Structure contours
"""

from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from .models import DICOMSeries, RTStructureFileImport, DICOMInstance, RTStructureFileVOIData, ContourModificationTypeChoices
import os
import tempfile
import shutil
import json
import base64
from io import BytesIO
import logging
import pickle
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

# Import DICOM and visualization libraries
try:
    import pydicom
    import numpy as np
    from rt_utils import RTStructBuilder
    import matplotlib
    matplotlib.use('Agg')  # Use non-interactive backend
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_agg import FigureCanvasAgg
except ImportError as e:
    logger.error(f"Failed to import required libraries: {e}")
    raise


@login_required
def view_rt_structure_list(request, series_uid):
    """
    View to display all RT Structures available for a given series
    Step 1: User clicks "View RT Structure" button and sees list of RT Structures
    """
    series = get_object_or_404(DICOMSeries, series_instance_uid=series_uid)
    
    # Get all RT Structure imports for this series
    rt_structures = RTStructureFileImport.objects.filter(
        deidentified_series_instance_uid=series
    ).order_by('-created_at')
    
    # Prepare RT Structure data
    rt_structure_data = []
    for rt_struct in rt_structures:
        # Get VOI count
        voi_count = rt_struct.rtstructurefilevoiData_set.count() if hasattr(rt_struct, 'rtstructurefilevoiData_set') else 0
        
        rt_structure_data.append({
            'id': rt_struct.id,
            'reidentified_path': rt_struct.reidentified_rt_structure_file_path,
            'deidentified_path': rt_struct.deidentified_rt_structure_file_path,
            'created_at': rt_struct.created_at,
            'voi_count': voi_count,
            'segmentation_status': rt_struct.server_segmentation_status,
        })
    
    context = {
        'series': series,
        'patient_name': series.study.patient.patient_name,
        'patient_id': series.study.patient.patient_id,
        'study_date': series.study.study_date,
        'series_description': series.series_description,
        'rt_structures': rt_structure_data,
        'instance_count': series.instance_count,
    }
    
    return render(request, 'dicom_handler/rt_structure_list.html', context)


@login_required
def dicom_viewer(request, series_uid, rt_structure_id):
    """
    Interactive DICOM viewer with RT Structure overlay
    Step 2: User clicks on specific RT Structure to open viewer
    """
    series = get_object_or_404(DICOMSeries, series_instance_uid=series_uid)
    rt_structure = get_object_or_404(RTStructureFileImport, id=rt_structure_id)
    
    # Get all DICOM instances for this series
    instances = DICOMInstance.objects.filter(
        series_instance_uid=series
    ).order_by('sop_instance_uid')
    
    # Prepare instance data
    instance_data = []
    for idx, instance in enumerate(instances):
        instance_data.append({
            'index': idx,
            'sop_instance_uid': instance.sop_instance_uid,
            'instance_path': instance.instance_path,
        })
    
    # Get available modification types
    modification_types = ContourModificationTypeChoices.objects.all().order_by('modification_type')
    
    # Check if this RT Structure has already been rated
    has_existing_rating = rt_structure.date_contour_reviewed is not None
    
    # Get existing VOI ratings if they exist
    existing_voi_ratings = {}
    if has_existing_rating:
        voi_data_list = RTStructureFileVOIData.objects.filter(
            rt_structure_file_import=rt_structure
        ).prefetch_related('contour_modification_type')
        
        for voi_data in voi_data_list:
            # Get modification type IDs
            mod_type_ids = [str(mod_type.id) for mod_type in voi_data.contour_modification_type.all()]
            
            existing_voi_ratings[voi_data.volume_name] = {
                'modification': voi_data.contour_modification,
                'modification_types': mod_type_ids,
                'comments': voi_data.contour_modification_comments or '',
            }
    
    context = {
        'series': series,
        'rt_structure': rt_structure,
        'patient_name': series.study.patient.patient_name,
        'patient_id': series.study.patient.patient_id,
        'study_date': series.study.study_date,
        'series_description': series.series_description,
        'instance_count': len(instance_data),
        'series_uid': series_uid,
        'rt_structure_id': str(rt_structure_id),
        'modification_types': modification_types,
        'has_existing_rating': has_existing_rating,
        'existing_assessor': rt_structure.assessor_name,
        'existing_date_reviewed': rt_structure.date_contour_reviewed,
        'existing_modification_time': rt_structure.contour_modification_time_required,
        'existing_overall_rating': rt_structure.overall_rating,
        'existing_voi_ratings_json': json.dumps(existing_voi_ratings),
    }
    
    return render(request, 'dicom_handler/dicom_viewer.html', context)


def _read_dicom_full(instance):
    """
    Helper function to read full DICOM file (including pixels) for sorting and copying.
    Designed to be called in parallel.
    
    Args:
        instance: DICOMInstance object
        
    Returns:
        Dictionary with DICOM dataset and metadata on success, None on failure
    """
    if not instance.instance_path or not os.path.exists(instance.instance_path):
        return None
    
    try:
        # Read full DICOM file (including pixel data)
        ds = pydicom.dcmread(instance.instance_path, force=True)
        instance_number = int(ds.InstanceNumber) if hasattr(ds, 'InstanceNumber') else 0
        slice_location = float(ds.SliceLocation) if hasattr(ds, 'SliceLocation') else 0.0
        image_position = ds.ImagePositionPatient[2] if hasattr(ds, 'ImagePositionPatient') else 0.0
        
        return {
            'instance': instance,
            'dataset': ds,  # Full DICOM dataset in memory
            'instance_number': instance_number,
            'slice_location': slice_location,
            'image_position': image_position,
        }
    except Exception as e:
        logger.warning(f"Failed to read DICOM file for {instance.sop_instance_uid}: {e}")
        return None


def _save_dicom_file(idx, dataset, sop_instance_uid, temp_dir):
    """
    Helper function to save a DICOM dataset to temp directory.
    Designed to be called in parallel.
    
    Args:
        idx: Index for the file in the sorted series (determines filename)
        dataset: pydicom Dataset object (already loaded in memory)
        sop_instance_uid: SOP Instance UID for logging
        temp_dir: Temporary directory path
        
    Returns:
        Dictionary with file info on success, None on failure
    """
    temp_file = os.path.join(temp_dir, f'instance_{idx:04d}.dcm')
    try:
        # Save the already-loaded DICOM dataset with proper format enforcement
        dataset.save_as(temp_file, enforce_file_format=True)
        return {
            'index': idx,
            'temp_path': temp_file,
            'sop_instance_uid': sop_instance_uid,
        }
    except Exception as e:
        logger.error(f"Failed to save DICOM file {sop_instance_uid}: {e}")
        return None


@login_required
@require_http_methods(["POST"])
def load_dicom_data(request):
    """
    API endpoint to load DICOM files and RT Structure into temporary directory
    Returns paths and metadata for the viewer
    """
    try:
        data = json.loads(request.body)
        series_uid = data.get('series_uid')
        rt_structure_id = data.get('rt_structure_id')
        
        if not series_uid or not rt_structure_id:
            return JsonResponse({
                'success': False,
                'error': 'Missing required parameters'
            }, status=400)
        
        series = get_object_or_404(DICOMSeries, series_instance_uid=series_uid)
        rt_structure = get_object_or_404(RTStructureFileImport, id=rt_structure_id)
        
        # Create temporary directory for this session
        temp_dir = tempfile.mkdtemp(prefix='dicom_viewer_')
        
        # Get DICOM instances from database
        instances = DICOMInstance.objects.filter(
            series_instance_uid=series
        )
        
        # STEP 1: Read all DICOM files in parallel (including pixel data)
        max_workers = min(8, (os.cpu_count() or 1) * 2)
        logger.info(f"Reading {instances.count()} DICOM files in parallel using {max_workers} workers")
        
        dicom_data = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all read tasks
            future_to_instance = {
                executor.submit(_read_dicom_full, instance): instance 
                for instance in instances
            }
            
            # Collect results as they complete
            for future in as_completed(future_to_instance):
                result = future.result()
                if result is not None:
                    dicom_data.append(result)
        
        logger.info(f"Successfully read {len(dicom_data)} out of {instances.count()} DICOM files")
        
        # STEP 2: Aggregate and sort by instance number, slice location, image position
        dicom_data.sort(key=lambda x: (x['instance_number'], x['slice_location'], x['image_position']))
        logger.info(f"Sorted {len(dicom_data)} DICOM files by instance number and slice location")
        
        # STEP 3: Save sorted DICOM files in parallel to temp directory
        logger.info(f"Saving {len(dicom_data)} sorted DICOM files in parallel using {max_workers} workers")
        
        instance_files = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all save tasks with sorted index
            future_to_idx = {
                executor.submit(
                    _save_dicom_file, 
                    idx, 
                    data['dataset'], 
                    data['instance'].sop_instance_uid, 
                    temp_dir
                ): idx 
                for idx, data in enumerate(dicom_data)
            }
            
            # Collect results as they complete
            for future in as_completed(future_to_idx):
                result = future.result()
                if result is not None:
                    instance_files.append(result)
        
        # Sort instance_files by index to maintain proper order
        instance_files.sort(key=lambda x: x['index'])
        logger.info(f"Successfully saved {len(instance_files)} out of {len(dicom_data)} DICOM files")
        
        # Copy RT Structure file to temp directory
        rt_struct_path = rt_structure.reidentified_rt_structure_file_path
        if not rt_struct_path or not os.path.exists(rt_struct_path):
            # Fallback to deidentified path
            rt_struct_path = rt_structure.deidentified_rt_structure_file_path
        
        if not rt_struct_path or not os.path.exists(rt_struct_path):
            shutil.rmtree(temp_dir, ignore_errors=True)
            return JsonResponse({
                'success': False,
                'error': 'RT Structure file not found'
            }, status=404)
        
        temp_rt_struct = os.path.join(temp_dir, 'rtstruct.dcm')
        try:
            # Read and save RT Structure with proper format enforcement
            rt_ds = pydicom.dcmread(rt_struct_path, force=True)
            rt_ds.save_as(temp_rt_struct, enforce_file_format=True)
        except Exception as e:
            logger.error(f"Failed to save RT Structure file: {e}")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return JsonResponse({
                'success': False,
                'error': f'Failed to process RT Structure file: {str(e)}'
            }, status=500)
        
        # Load RT Structure to get ROI names and colors
        try:
            rtstruct = RTStructBuilder.create_from(
                dicom_series_path=temp_dir,
                rt_struct_path=temp_rt_struct
            )
            roi_names = rtstruct.get_roi_names()
            
            # Extract ROI colors from RT Structure file
            roi_colors = {}
            if hasattr(rt_ds, 'StructureSetROISequence') and hasattr(rt_ds, 'ROIContourSequence'):
                # Create mapping from ROI Number to ROI Name
                roi_number_to_name = {}
                for roi_item in rt_ds.StructureSetROISequence:
                    roi_number = int(roi_item.ROINumber)
                    roi_name = str(roi_item.ROIName)
                    roi_number_to_name[roi_number] = roi_name
                
                # Extract colors from ROI Contour Sequence
                for contour_item in rt_ds.ROIContourSequence:
                    roi_number = int(contour_item.ReferencedROINumber)
                    roi_name = roi_number_to_name.get(roi_number)
                    
                    if roi_name and hasattr(contour_item, 'ROIDisplayColor'):
                        # ROIDisplayColor is stored as [R, G, B] with values 0-255
                        color_values = contour_item.ROIDisplayColor
                        roi_colors[roi_name] = {
                            'r': int(color_values[0]),
                            'g': int(color_values[1]),
                            'b': int(color_values[2])
                        }
                        logger.info(f"Extracted color for '{roi_name}': RGB({color_values[0]}, {color_values[1]}, {color_values[2]})")
            
        except Exception as e:
            logger.error(f"Failed to load RT Structure: {e}")
            roi_names = []
            roi_colors = {}
        
        # Store temp directory path in session
        request.session['dicom_temp_dir'] = temp_dir
        request.session['rt_struct_path'] = temp_rt_struct
        request.session.modified = True
        
        return JsonResponse({
            'success': True,
            'temp_dir': temp_dir,
            'instance_count': len(instance_files),
            'roi_names': roi_names,
            'roi_colors': roi_colors,
        })
        
    except Exception as e:
        logger.error(f"Error loading DICOM data: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@require_http_methods(["POST"])
def get_dicom_slice(request):
    """
    API endpoint to get a specific DICOM slice with RT Structure overlay
    Returns base64-encoded image
    """
    try:
        data = json.loads(request.body)
        slice_index = int(data.get('slice_index', 0))
        window_center = float(data.get('window_center', 40))
        window_width = float(data.get('window_width', 400))
        selected_rois = data.get('selected_rois', [])
        
        # Get temp directory from session
        temp_dir = request.session.get('dicom_temp_dir')
        rt_struct_path = request.session.get('rt_struct_path')
        
        if not temp_dir or not os.path.exists(temp_dir):
            return JsonResponse({
                'success': False,
                'error': 'Session expired. Please reload the page.'
            }, status=400)
        
        # Get list of DICOM files
        dicom_files = sorted([
            os.path.join(temp_dir, f) for f in os.listdir(temp_dir)
            if f.startswith('instance_') and f.endswith('.dcm')
        ])
        
        if slice_index < 0 or slice_index >= len(dicom_files):
            return JsonResponse({
                'success': False,
                'error': 'Invalid slice index'
            }, status=400)
        
        # Load DICOM file
        dicom_file = dicom_files[slice_index]
        ds = pydicom.dcmread(dicom_file, force = True)
        
        # Log current slice information
        instance_number = int(ds.InstanceNumber) if hasattr(ds, 'InstanceNumber') else None
        slice_location = float(ds.SliceLocation) if hasattr(ds, 'SliceLocation') else None
        image_position = ds.ImagePositionPatient[2] if hasattr(ds, 'ImagePositionPatient') else None
        logger.info(f"Current DICOM slice {slice_index}: InstanceNumber={instance_number}, SliceLocation={slice_location}, ImagePosition Z={image_position}")
        
        # Get pixel array
        pixel_array = ds.pixel_array.astype(float)
        
        # Apply rescale slope and intercept if available
        if hasattr(ds, 'RescaleSlope') and hasattr(ds, 'RescaleIntercept'):
            pixel_array = pixel_array * ds.RescaleSlope + ds.RescaleIntercept
        
        # Apply windowing
        windowed_array = apply_windowing(pixel_array, window_center, window_width)
        
        # Create figure with aspect ratio matching the DICOM image
        height, width = windowed_array.shape
        aspect_ratio = width / height
        
        # Set figure size based on aspect ratio (base height of 10 inches)
        fig_height = 10
        fig_width = fig_height * aspect_ratio
        
        fig, ax = plt.subplots(figsize=(fig_width, fig_height))
        ax.imshow(windowed_array, cmap='gray', interpolation='nearest')
        ax.axis('off')
        
        # Track failed ROIs
        failed_rois = []
        
        # Overlay RT Structure contours if selected
        if selected_rois and rt_struct_path and os.path.exists(rt_struct_path):
            try:
                logger.info(f"Loading RT Structure from {rt_struct_path}")
                logger.info(f"Selected ROIs: {selected_rois}")
                
                # Use file-based cache instead of session (masks are too large for session)
                cache_dir = os.path.join(temp_dir, 'mask_cache')
                os.makedirs(cache_dir, exist_ok=True)
                
                rtstruct = RTStructBuilder.create_from(
                    dicom_series_path=temp_dir,
                    rt_struct_path=rt_struct_path
                )
                
                available_rois = rtstruct.get_roi_names()
                logger.info(f"Available ROIs in RT Structure: {available_rois}")
                
                # Get the series_data from rt-utils to understand slice mapping
                # rt-utils creates mask based on sorted DICOM files it finds
                series_data = rtstruct.series_data
                logger.info(f"RT Structure series has {len(series_data)} slices")
                
                # Find which rt-utils slice index corresponds to our current DICOM file
                current_sop_uid = ds.SOPInstanceUID
                rt_slice_index = None
                for rt_idx, rt_slice in enumerate(series_data):
                    if rt_slice.SOPInstanceUID == current_sop_uid:
                        rt_slice_index = rt_idx
                        logger.info(f"Found matching slice: viewer index {slice_index} -> RT Structure index {rt_slice_index}")
                        break
                
                if rt_slice_index is None:
                    logger.warning(f"Could not find matching slice for SOP UID {current_sop_uid}")
                    # Fallback: use the slice index as-is
                    rt_slice_index = slice_index
                
                # Extract colors from RT Structure file
                # Read the RT Structure DICOM file to get ROI colors
                rt_ds = pydicom.dcmread(rt_struct_path, force=True)
                roi_color_map = {}
                
                # Build mapping from ROI name to color from DICOM tags
                if hasattr(rt_ds, 'StructureSetROISequence') and hasattr(rt_ds, 'ROIContourSequence'):
                    # Create mapping from ROI Number to ROI Name
                    roi_number_to_name = {}
                    for roi_item in rt_ds.StructureSetROISequence:
                        roi_number = int(roi_item.ROINumber)
                        roi_name = str(roi_item.ROIName)
                        roi_number_to_name[roi_number] = roi_name
                    
                    # Extract colors from ROI Contour Sequence
                    for contour_item in rt_ds.ROIContourSequence:
                        roi_number = int(contour_item.ReferencedROINumber)
                        roi_name = roi_number_to_name.get(roi_number)
                        
                        if roi_name and hasattr(contour_item, 'ROIDisplayColor'):
                            # ROIDisplayColor is stored as [R, G, B] with values 0-255
                            color_values = contour_item.ROIDisplayColor
                            # Convert to matplotlib format (0-1 range)
                            color = (color_values[0] / 255.0, 
                                   color_values[1] / 255.0, 
                                   color_values[2] / 255.0)
                            roi_color_map[roi_name] = color
                            logger.info(f"Extracted color for '{roi_name}': RGB({color_values[0]}, {color_values[1]}, {color_values[2]})")
                
                # For ROIs without colors in the file, assign rainbow colors
                rainbow_colors = plt.cm.rainbow(np.linspace(0, 1, len(available_rois)))
                for i, roi_name in enumerate(available_rois):
                    if roi_name not in roi_color_map:
                        roi_color_map[roi_name] = rainbow_colors[i]
                        logger.info(f"Assigned rainbow color to '{roi_name}' (no color in RT Structure)")
                
                logger.info(f"Created color map for {len(available_rois)} ROIs ({len([k for k in roi_color_map if k in available_rois])} from file, {len([k for k in available_rois if k not in roi_color_map])} generated)")
                
                contours_drawn = 0
                for idx, roi_name in enumerate(selected_rois):
                    try:
                        logger.info(f"Processing ROI: {roi_name}")
                        
                        # Check if mask is already cached in file
                        cache_file = os.path.join(cache_dir, f"{roi_name}.pkl")
                        failed_cache_file = os.path.join(cache_dir, f"{roi_name}.failed")
                        
                        # Check if this ROI failed previously
                        if os.path.exists(failed_cache_file):
                            logger.info(f"Skipping {roi_name} (previously failed)")
                            failed_rois.append(roi_name)
                            continue
                        
                        # Try to load from cache
                        if os.path.exists(cache_file):
                            logger.info(f"Using cached mask for {roi_name}")
                            with open(cache_file, 'rb') as f:
                                mask_3d = pickle.load(f)
                        else:
                            # Get 3D mask for this ROI - wrap in try-except to handle rt-utils/OpenCV errors
                            try:
                                logger.info(f"Generating mask for {roi_name} (first time)")
                                mask_3d = rtstruct.get_roi_mask_by_name(roi_name)
                                
                                # Cache the mask to file for future use
                                with open(cache_file, 'wb') as f:
                                    pickle.dump(mask_3d, f)
                                logger.info(f"Cached mask for {roi_name}")
                                
                            except Exception as mask_error:
                                logger.error(f"Failed to generate mask for ROI '{roi_name}': {mask_error}")
                                logger.error(f"This ROI has invalid contour data that cannot be processed by rt-utils/OpenCV")
                                logger.error(f"Skipping ROI '{roi_name}' and continuing with other structures")
                                failed_rois.append(roi_name)
                                
                                # Mark as failed so we don't retry
                                with open(failed_cache_file, 'w') as f:
                                    f.write(str(mask_error))
                                continue  # Skip this ROI and move to the next one
                            
                        logger.info(f"Mask 3D shape for {roi_name}: {mask_3d.shape}")
                        logger.info(f"Viewer slice index: {slice_index}, RT Structure slice index: {rt_slice_index}, Total slices in mask: {mask_3d.shape[2]}")
                        
                        # Get the slice for current index using the mapped rt_slice_index
                        if rt_slice_index < mask_3d.shape[2]:
                            mask_slice = mask_3d[:, :, rt_slice_index]
                            logger.info(f"Mask slice shape: {mask_slice.shape}, Non-zero pixels: {np.count_nonzero(mask_slice)}")
                            
                            # Create contour overlay
                            if np.any(mask_slice):
                                # Find contours
                                contours = find_contours(mask_slice)
                                logger.info(f"Found {len(contours)} contours for {roi_name}")
                                
                                for contour_idx, contour in enumerate(contours):
                                    if len(contour) > 2:  # Need at least 3 points to draw
                                        ax.plot(contour[:, 1], contour[:, 0], 
                                               color=roi_color_map[roi_name], linewidth=2, 
                                               label=roi_name if contour_idx == 0 else "")
                                        contours_drawn += 1
                            else:
                                logger.info(f"No mask data on RT slice {rt_slice_index} for {roi_name}")
                        else:
                            logger.warning(f"RT slice index {rt_slice_index} out of range for {roi_name} (max: {mask_3d.shape[2]-1})")
                            
                    except Exception as e:
                        logger.error(f"Failed to overlay ROI {roi_name}: {e}", exc_info=True)
                        continue
                
                logger.info(f"Total contours drawn: {contours_drawn}")
                
                # Add legend if ROIs were overlaid
                if contours_drawn > 0:
                    ax.legend(loc='upper right', fontsize=8, framealpha=0.7)
                    
            except Exception as e:
                logger.error(f"Failed to overlay RT Structure: {e}", exc_info=True)
        
        # Convert plot to base64 image
        buf = BytesIO()
        plt.tight_layout()
        plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        plt.close(fig)
        buf.seek(0)
        
        image_base64 = base64.b64encode(buf.read()).decode('utf-8')
        
        # Get slice metadata
        metadata = {
            'slice_location': float(ds.SliceLocation) if hasattr(ds, 'SliceLocation') else None,
            'instance_number': int(ds.InstanceNumber) if hasattr(ds, 'InstanceNumber') else slice_index + 1,
            'slice_thickness': float(ds.SliceThickness) if hasattr(ds, 'SliceThickness') else None,
        }
        
        return JsonResponse({
            'success': True,
            'image': image_base64,
            'metadata': metadata,
            'slice_index': slice_index,
            'total_slices': len(dicom_files),
            'failed_rois': failed_rois,
        })
        
    except Exception as e:
        logger.error(f"Error getting DICOM slice: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@require_http_methods(["POST"])
def render_all_slices(request):
    """
    API endpoint to pre-render all DICOM slices for browser caching.
    Returns array of base64-encoded images for all slices.
    """
    try:
        data = json.loads(request.body)
        window_center = float(data.get('window_center', 40))
        window_width = float(data.get('window_width', 400))
        selected_rois = data.get('selected_rois', [])
        
        # Get temp directory from session
        temp_dir = request.session.get('dicom_temp_dir')
        rt_struct_path = request.session.get('rt_struct_path')
        
        if not temp_dir or not os.path.exists(temp_dir):
            return JsonResponse({
                'success': False,
                'error': 'Session expired. Please reload the page.'
            }, status=400)
        
        # Get list of DICOM files
        dicom_files = sorted([
            os.path.join(temp_dir, f) for f in os.listdir(temp_dir)
            if f.startswith('instance_') and f.endswith('.dcm')
        ])
        
        logger.info(f"Pre-rendering {len(dicom_files)} slices with window C/W: {window_center}/{window_width}")
        
        # Prepare RT Structure data if needed
        rtstruct = None
        roi_color_map = {}
        series_data = None
        
        if selected_rois and rt_struct_path and os.path.exists(rt_struct_path):
            try:
                # Load RT Structure once
                rtstruct = RTStructBuilder.create_from(
                    dicom_series_path=temp_dir,
                    rt_struct_path=rt_struct_path
                )
                series_data = rtstruct.series_data
                
                # Extract colors once
                rt_ds = pydicom.dcmread(rt_struct_path, force=True)
                if hasattr(rt_ds, 'StructureSetROISequence') and hasattr(rt_ds, 'ROIContourSequence'):
                    roi_number_to_name = {}
                    for roi_item in rt_ds.StructureSetROISequence:
                        roi_number = int(roi_item.ROINumber)
                        roi_name = str(roi_item.ROIName)
                        roi_number_to_name[roi_number] = roi_name
                    
                    for contour_item in rt_ds.ROIContourSequence:
                        roi_number = int(contour_item.ReferencedROINumber)
                        roi_name = roi_number_to_name.get(roi_number)
                        
                        if roi_name and hasattr(contour_item, 'ROIDisplayColor'):
                            color_values = contour_item.ROIDisplayColor
                            color = (color_values[0] / 255.0, 
                                   color_values[1] / 255.0, 
                                   color_values[2] / 255.0)
                            roi_color_map[roi_name] = color
                
                # For ROIs without colors, assign rainbow colors
                available_rois = rtstruct.get_roi_names()
                rainbow_colors = plt.cm.rainbow(np.linspace(0, 1, len(available_rois)))
                for i, roi_name in enumerate(available_rois):
                    if roi_name not in roi_color_map:
                        roi_color_map[roi_name] = rainbow_colors[i]
                
                # Pre-load masks
                cache_dir = os.path.join(temp_dir, 'mask_cache')
                os.makedirs(cache_dir, exist_ok=True)
                
                for roi_name in selected_rois:
                    cache_file = os.path.join(cache_dir, f"{roi_name}.pkl")
                    if not os.path.exists(cache_file):
                        try:
                            mask_3d = rtstruct.get_roi_mask_by_name(roi_name)
                            with open(cache_file, 'wb') as f:
                                pickle.dump(mask_3d, f)
                        except Exception as e:
                            logger.error(f"Failed to cache mask for {roi_name}: {e}")
                
            except Exception as e:
                logger.error(f"Failed to prepare RT Structure: {e}")
                rtstruct = None
        
        # Render all slices in parallel
        def render_single_slice(slice_idx):
            try:
                dicom_file = dicom_files[slice_idx]
                ds = pydicom.dcmread(dicom_file, force=True)
                
                # Get pixel array
                pixel_array = ds.pixel_array.astype(float)
                
                # Apply rescale
                if hasattr(ds, 'RescaleSlope') and hasattr(ds, 'RescaleIntercept'):
                    pixel_array = pixel_array * ds.RescaleSlope + ds.RescaleIntercept
                
                # Apply windowing
                windowed_array = apply_windowing(pixel_array, window_center, window_width)
                
                # Create figure
                height, width = windowed_array.shape
                aspect_ratio = width / height
                fig_height = 10
                fig_width = fig_height * aspect_ratio
                
                fig, ax = plt.subplots(figsize=(fig_width, fig_height))
                ax.imshow(windowed_array, cmap='gray', interpolation='nearest')
                ax.axis('off')
                
                # Overlay contours if RT Structure loaded
                if rtstruct and selected_rois:
                    current_sop_uid = ds.SOPInstanceUID
                    rt_slice_index = None
                    for rt_idx, rt_slice in enumerate(series_data):
                        if rt_slice.SOPInstanceUID == current_sop_uid:
                            rt_slice_index = rt_idx
                            break
                    
                    if rt_slice_index is None:
                        rt_slice_index = slice_idx
                    
                    cache_dir = os.path.join(temp_dir, 'mask_cache')
                    contours_drawn = 0
                    
                    for roi_name in selected_rois:
                        cache_file = os.path.join(cache_dir, f"{roi_name}.pkl")
                        if os.path.exists(cache_file):
                            try:
                                with open(cache_file, 'rb') as f:
                                    mask_3d = pickle.load(f)
                                
                                if rt_slice_index < mask_3d.shape[2]:
                                    mask_slice = mask_3d[:, :, rt_slice_index]
                                    
                                    if np.any(mask_slice):
                                        contours = find_contours(mask_slice)
                                        for contour_idx, contour in enumerate(contours):
                                            if len(contour) > 2:
                                                ax.plot(contour[:, 1], contour[:, 0], 
                                                       color=roi_color_map[roi_name], linewidth=2,
                                                       label=roi_name if contour_idx == 0 else "")
                                                contours_drawn += 1
                            except Exception as e:
                                logger.error(f"Failed to overlay {roi_name} on slice {slice_idx}: {e}")
                    
                    if contours_drawn > 0:
                        ax.legend(loc='upper right', fontsize=8, framealpha=0.7)
                
                # Convert to base64
                buf = BytesIO()
                plt.tight_layout()
                plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
                plt.close(fig)
                buf.seek(0)
                
                image_base64 = base64.b64encode(buf.read()).decode('utf-8')
                
                # Get metadata
                metadata = {
                    'slice_location': float(ds.SliceLocation) if hasattr(ds, 'SliceLocation') else None,
                    'instance_number': int(ds.InstanceNumber) if hasattr(ds, 'InstanceNumber') else slice_idx + 1,
                }
                
                return {
                    'index': slice_idx,
                    'image': image_base64,
                    'metadata': metadata,
                }
            except Exception as e:
                logger.error(f"Failed to render slice {slice_idx}: {e}")
                return None
        
        # Render all slices in parallel
        max_workers = min(8, (os.cpu_count() or 1) * 2)
        rendered_slices = []
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(render_single_slice, idx): idx for idx in range(len(dicom_files))}
            
            for future in as_completed(futures):
                result = future.result()
                if result is not None:
                    rendered_slices.append(result)
        
        # Sort by index
        rendered_slices.sort(key=lambda x: x['index'])
        
        logger.info(f"Successfully rendered {len(rendered_slices)} out of {len(dicom_files)} slices")
        
        return JsonResponse({
            'success': True,
            'slices': rendered_slices,
            'total_slices': len(dicom_files),
        })
        
    except Exception as e:
        logger.error(f"Error rendering all slices: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@require_http_methods(["POST"])
def cleanup_temp_files(request):
    """
    API endpoint to cleanup temporary files when viewer is closed
    """
    try:
        temp_dir = request.session.get('dicom_temp_dir')
        
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
        
        # Clear session variables
        request.session.pop('dicom_temp_dir', None)
        request.session.pop('rt_struct_path', None)
        request.session.modified = True
        
        return JsonResponse({
            'success': True,
            'message': 'Temporary files cleaned up'
        })
        
    except Exception as e:
        logger.error(f"Error cleaning up temp files: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


def apply_windowing(pixel_array, window_center, window_width):
    """
    Apply window/level to pixel array
    """
    img_min = window_center - window_width / 2
    img_max = window_center + window_width / 2
    
    windowed = np.clip(pixel_array, img_min, img_max)
    windowed = (windowed - img_min) / (img_max - img_min)
    
    return windowed


def find_contours(mask_slice, level=0.5):
    """
    Find contours in a binary mask slice
    """
    try:
        from skimage import measure
        contours = measure.find_contours(mask_slice, level)
        return contours
    except ImportError:
        # Fallback: use matplotlib's contour finding
        import matplotlib._contour as _contour
        # Simple edge detection
        edges = np.zeros_like(mask_slice)
        edges[:-1, :] |= (mask_slice[:-1, :] != mask_slice[1:, :])
        edges[:, :-1] |= (mask_slice[:, :-1] != mask_slice[:, 1:])
        
        # Find coordinates of edges
        y, x = np.where(edges)
        if len(x) > 0:
            points = np.column_stack([y, x])
            return [points]
        return []


@login_required
@require_http_methods(["POST"])
def save_contour_ratings(request):
    """
    Save contour quality ratings from the DICOM viewer
    """
    try:
        data = json.loads(request.body)
        series_uid = data.get('series_uid')
        overall_rating = data.get('overall_rating')
        modification_time = data.get('modification_time')
        structure_ratings = data.get('structure_ratings', {})
        
        logger.info(f"Saving ratings for series {series_uid}")
        
        # Get the series
        series = get_object_or_404(DICOMSeries, series_instance_uid=series_uid)
        
        # Get the RT Structure import for this series
        rt_import = RTStructureFileImport.objects.filter(
            deidentified_series_instance_uid=series
        ).first()
        
        if not rt_import:
            return JsonResponse({
                'success': False,
                'error': 'No RT Structure found for this series'
            }, status=404)
        
        # Update RT Structure level data
        rt_import.overall_rating = overall_rating
        rt_import.assessor_name = request.user.get_full_name() or request.user.username
        rt_import.date_contour_reviewed = timezone.now().date()
        if modification_time is not None:
            rt_import.contour_modification_time_required = modification_time
        rt_import.save()
        
        logger.info(f"Updated RT Structure {rt_import.id} with overall rating {overall_rating}")
        
        # Save individual structure ratings
        saved_count = 0
        for roi_name, rating_data in structure_ratings.items():
            # Get or create VOI data
            voi_data, created = RTStructureFileVOIData.objects.get_or_create(
                rt_structure_file_import=rt_import,
                volume_name=roi_name,
                defaults={
                    'contour_modification': rating_data.get('modification', 'NO_MODIFICATION'),
                    'contour_modification_comments': rating_data.get('comments', '')
                }
            )
            
            if not created:
                # Update existing
                voi_data.contour_modification = rating_data.get('modification', 'NO_MODIFICATION')
                voi_data.contour_modification_comments = rating_data.get('comments', '')
                voi_data.save()
            
            # Handle modification types (M2M relationship)
            modification_type_ids = rating_data.get('modification_types', [])
            if modification_type_ids:
                # Clear existing and set new
                voi_data.contour_modification_type.clear()
                for type_id in modification_type_ids:
                    try:
                        mod_type = ContourModificationTypeChoices.objects.get(id=type_id)
                        voi_data.contour_modification_type.add(mod_type)
                    except ContourModificationTypeChoices.DoesNotExist:
                        logger.warning(f"Modification type {type_id} not found")
            else:
                # Clear all if none selected
                voi_data.contour_modification_type.clear()
            
            saved_count += 1
            logger.info(f"Saved rating for {roi_name}: {rating_data.get('modification')} with {len(modification_type_ids)} modification types")
        
        return JsonResponse({
            'success': True,
            'message': f'Saved ratings for {saved_count} structures',
            'rt_import_id': str(rt_import.id)
        })
        
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {e}")
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON data'
        }, status=400)
    except Exception as e:
        logger.error(f"Error saving ratings: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)
