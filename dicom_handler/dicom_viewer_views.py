"""
DICOM Viewer Views with RT Structure Overlay
Provides interactive visualization of DICOM images with RT Structure contours
"""

from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from .models import DICOMSeries, RTStructureFileImport, DICOMInstance
import os
import tempfile
import shutil
import json
import base64
from io import BytesIO
import logging

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
    }
    
    return render(request, 'dicom_handler/dicom_viewer.html', context)


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
        
        # Copy DICOM instances to temp directory
        instances = DICOMInstance.objects.filter(
            series_instance_uid=series
        )
        
        # Read DICOM metadata to get proper ordering
        instance_metadata = []
        for instance in instances:
            if instance.instance_path and os.path.exists(instance.instance_path):
                try:
                    ds = pydicom.dcmread(instance.instance_path, stop_before_pixels=True)
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
        
        # Sort by instance number first, then by slice location/image position
        instance_metadata.sort(key=lambda x: (x['instance_number'], x['slice_location'], x['image_position']))
        
        # Copy sorted files to temp directory
        instance_files = []
        for idx, meta in enumerate(instance_metadata):
            instance = meta['instance']
            temp_file = os.path.join(temp_dir, f'instance_{idx:04d}.dcm')
            shutil.copy2(instance.instance_path, temp_file)
            instance_files.append({
                'index': idx,
                'temp_path': temp_file,
                'sop_instance_uid': instance.sop_instance_uid,
            })
        
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
        shutil.copy2(rt_struct_path, temp_rt_struct)
        
        # Load RT Structure to get ROI names
        try:
            rtstruct = RTStructBuilder.create_from(
                dicom_series_path=temp_dir,
                rt_struct_path=temp_rt_struct
            )
            roi_names = rtstruct.get_roi_names()
        except Exception as e:
            logger.error(f"Failed to load RT Structure: {e}")
            roi_names = []
        
        # Store temp directory path in session
        request.session['dicom_temp_dir'] = temp_dir
        request.session['rt_struct_path'] = temp_rt_struct
        request.session.modified = True
        
        return JsonResponse({
            'success': True,
            'temp_dir': temp_dir,
            'instance_count': len(instance_files),
            'roi_names': roi_names,
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
        ds = pydicom.dcmread(dicom_file)
        
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
        
        # Create figure
        fig, ax = plt.subplots(figsize=(10, 10))
        ax.imshow(windowed_array, cmap='gray', interpolation='nearest')
        ax.axis('off')
        
        # Track failed ROIs
        failed_rois = []
        
        # Overlay RT Structure contours if selected
        if selected_rois and rt_struct_path and os.path.exists(rt_struct_path):
            try:
                logger.info(f"Loading RT Structure from {rt_struct_path}")
                logger.info(f"Selected ROIs: {selected_rois}")
                
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
                
                # Create consistent color mapping for ALL available ROIs (not just selected ones)
                # This ensures each ROI always has the same color
                all_colors = plt.cm.rainbow(np.linspace(0, 1, len(available_rois)))
                roi_color_map = {roi_name: all_colors[i] for i, roi_name in enumerate(available_rois)}
                logger.info(f"Created color map for {len(available_rois)} ROIs")
                
                contours_drawn = 0
                for idx, roi_name in enumerate(selected_rois):
                    try:
                        logger.info(f"Processing ROI: {roi_name}")
                        
                        # Debug: Get raw RT Structure data for this ROI
                        try:
                            # Access the internal RT Structure dataset
                            rt_ds = pydicom.dcmread(rt_struct_path)
                            
                            # Find the ROI sequence entry for this ROI
                            roi_number = None
                            for roi_seq in rt_ds.StructureSetROISequence:
                                if roi_seq.ROIName == roi_name:
                                    roi_number = roi_seq.ROINumber
                                    logger.info(f"Found ROI '{roi_name}' with ROI Number: {roi_number}")
                                    break
                            
                            if roi_number:
                                # Find contour data
                                for roi_contour in rt_ds.ROIContourSequence:
                                    if roi_contour.ReferencedROINumber == roi_number:
                                        logger.info(f"ROI '{roi_name}' contour info:")
                                        logger.info(f"  - Has ContourSequence: {hasattr(roi_contour, 'ContourSequence')}")
                                        if hasattr(roi_contour, 'ContourSequence'):
                                            logger.info(f"  - Number of contours: {len(roi_contour.ContourSequence)}")
                                            
                                            # Inspect first few contours
                                            for i, contour in enumerate(roi_contour.ContourSequence[:3]):
                                                logger.info(f"  - Contour {i}:")
                                                logger.info(f"    - Contour Geometric Type: {contour.ContourGeometricType if hasattr(contour, 'ContourGeometricType') else 'N/A'}")
                                                logger.info(f"    - Number of Contour Points: {contour.NumberOfContourPoints if hasattr(contour, 'NumberOfContourPoints') else 'N/A'}")
                                                if hasattr(contour, 'ContourData'):
                                                    contour_data = contour.ContourData
                                                    logger.info(f"    - ContourData length: {len(contour_data)}")
                                                    logger.info(f"    - First 9 points: {contour_data[:9]}")
                                                    logger.info(f"    - Data type: {type(contour_data)}")
                                                    # Check for invalid values
                                                    try:
                                                        data_array = np.array(contour_data, dtype=float)
                                                        logger.info(f"    - Has NaN: {np.any(np.isnan(data_array))}")
                                                        logger.info(f"    - Has Inf: {np.any(np.isinf(data_array))}")
                                                        logger.info(f"    - Min value: {np.min(data_array)}")
                                                        logger.info(f"    - Max value: {np.max(data_array)}")
                                                    except Exception as e:
                                                        logger.error(f"    - Error converting to array: {e}")
                                        break
                        except Exception as debug_error:
                            logger.error(f"Debug inspection failed for {roi_name}: {debug_error}", exc_info=True)
                        
                        # Get 3D mask for this ROI - wrap in try-except to handle rt-utils/OpenCV errors
                        try:
                            # Additional debugging: manually check coordinate transformation
                            if roi_name == "Larynx":  # Only for problematic ROI
                                logger.info(f"=== Deep dive into Larynx coordinate transformation ===")
                                
                                # Get a sample DICOM slice to check image properties
                                sample_ds = pydicom.dcmread(dicom_files[0])
                                logger.info(f"Image properties:")
                                logger.info(f"  - Rows: {sample_ds.Rows}, Columns: {sample_ds.Columns}")
                                logger.info(f"  - PixelSpacing: {sample_ds.PixelSpacing if hasattr(sample_ds, 'PixelSpacing') else 'N/A'}")
                                logger.info(f"  - ImagePositionPatient: {sample_ds.ImagePositionPatient if hasattr(sample_ds, 'ImagePositionPatient') else 'N/A'}")
                                logger.info(f"  - ImageOrientationPatient: {sample_ds.ImageOrientationPatient if hasattr(sample_ds, 'ImageOrientationPatient') else 'N/A'}")
                                
                                # Try to manually transform first contour points
                                rt_ds = pydicom.dcmread(rt_struct_path)
                                for roi_contour in rt_ds.ROIContourSequence:
                                    if roi_contour.ReferencedROINumber == 7:  # Larynx ROI number
                                        first_contour = roi_contour.ContourSequence[0]
                                        contour_data = first_contour.ContourData
                                        
                                        # Extract x, y, z coordinates
                                        points_3d = [(float(contour_data[i]), float(contour_data[i+1]), float(contour_data[i+2])) 
                                                    for i in range(0, len(contour_data), 3)]
                                        
                                        logger.info(f"First contour has {len(points_3d)} points")
                                        logger.info(f"First 3 points in world coordinates: {points_3d[:3]}")
                                        
                                        # Try manual transformation to pixel coordinates
                                        if hasattr(sample_ds, 'ImagePositionPatient') and hasattr(sample_ds, 'ImageOrientationPatient') and hasattr(sample_ds, 'PixelSpacing'):
                                            # Get transformation parameters
                                            image_position = np.array(sample_ds.ImagePositionPatient)
                                            image_orientation = np.array(sample_ds.ImageOrientationPatient)
                                            pixel_spacing = np.array(sample_ds.PixelSpacing)
                                            
                                            # Build transformation matrix (simplified)
                                            row_cosine = image_orientation[:3]
                                            col_cosine = image_orientation[3:]
                                            
                                            logger.info(f"Transformation parameters:")
                                            logger.info(f"  - Image position: {image_position}")
                                            logger.info(f"  - Row cosine: {row_cosine}")
                                            logger.info(f"  - Col cosine: {col_cosine}")
                                            logger.info(f"  - Pixel spacing: {pixel_spacing}")
                                            
                                            # Transform first few points
                                            pixel_points = []
                                            for world_point in points_3d[:5]:
                                                world_array = np.array(world_point)
                                                
                                                # Transform to image coordinates
                                                relative_pos = world_array - image_position
                                                col = np.dot(relative_pos, row_cosine) / pixel_spacing[1]
                                                row = np.dot(relative_pos, col_cosine) / pixel_spacing[0]
                                                
                                                pixel_points.append((row, col))
                                                logger.info(f"  World {world_point} -> Pixel ({row:.2f}, {col:.2f})")
                                            
                                            # Check if points are within image bounds
                                            for i, (row, col) in enumerate(pixel_points):
                                                in_bounds = (0 <= row < sample_ds.Rows) and (0 <= col < sample_ds.Columns)
                                                logger.info(f"  Point {i}: ({row:.2f}, {col:.2f}) - In bounds: {in_bounds}")
                                                if not in_bounds:
                                                    logger.warning(f"  Point {i} is OUTSIDE image bounds!")
                                        
                                        break
                                
                            mask_3d = rtstruct.get_roi_mask_by_name(roi_name)
                        except Exception as mask_error:
                            logger.error(f"Failed to generate mask for ROI '{roi_name}': {mask_error}")
                            logger.error(f"This ROI has invalid contour data that cannot be processed by rt-utils/OpenCV")
                            logger.error(f"Skipping ROI '{roi_name}' and continuing with other structures")
                            failed_rois.append(roi_name)
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
        plt.savefig(buf, format='png', dpi=100, bbox_inches='tight')
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
