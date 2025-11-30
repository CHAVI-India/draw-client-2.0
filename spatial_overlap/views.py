from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.db import transaction, models
from django.views.decorators.http import require_http_methods
import logging
import json
import csv
from datetime import datetime

from .models import (
    RTStructureSetFile,
    RTStructureSetVOI,
    RTStructureFileComparison,
    ComparisonResult,
    ComparisionTypeChoices
)
from .utils.compute_metrics import compute_comparison_metrics

logger = logging.getLogger(__name__)


def prepare_working_directory_for_comparison(series, rt_structure_file_path, uploaded_reference_file=None):
    """
    Creates a working directory containing:
    1. DICOM images from the series (read and saved with pydicom)
    2. Autosegmented RT Structure file (read and saved with pydicom)
    3. Reference RT Structure file if provided (read and saved with pydicom)
    
    Returns: (working_dir_path, autoseg_rt_path, reference_rt_path) or (None, None, None) on error
    """
    from dicom_handler.models import DICOMInstance
    import pydicom
    import tempfile
    import os
    
    try:
        # Create working directory
        working_dir = tempfile.mkdtemp(prefix='spatial_overlap_comparison_')
        logger.info(f"Created working directory: {working_dir}")
        
        # 1. Prepare DICOM images - read from database and save to working directory
        instances = DICOMInstance.objects.filter(
            series_instance_uid=series
        ).order_by('sop_instance_uid')
        
        if not instances.exists():
            logger.error(f"No DICOM instances found for series: {series.series_instance_uid}")
            return None, None, None
        
        # Read instance metadata for proper ordering
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
                        'image_position': image_position
                    })
                except Exception as e:
                    logger.warning(f"Could not read metadata for instance {instance.sop_instance_uid}: {e}")
        
        # Sort by instance number, then slice location, then image position
        instance_metadata.sort(key=lambda x: (x['instance_number'], x['slice_location'], x['image_position']))
        
        # Save DICOM images to working directory
        logger.info(f"Saving {len(instance_metadata)} DICOM images to working directory")
        for idx, item in enumerate(instance_metadata):
            instance = item['instance']
            try:
                # Read with force=True
                ds = pydicom.dcmread(instance.instance_path, force=True)
                
                # Save to working directory with enforce_file_format=True
                output_filename = f"image_{idx:04d}.dcm"
                output_path = os.path.join(working_dir, output_filename)
                ds.save_as(output_path, enforce_file_format=True)
                
            except Exception as e:
                logger.error(f"Failed to save DICOM image {instance.sop_instance_uid}: {e}")
                return None, None, None
        
        # 2. Save autosegmented RT Structure file
        autoseg_rt_path = None
        if rt_structure_file_path and os.path.exists(rt_structure_file_path):
            try:
                # Read RT Structure with force=True
                ds_rt = pydicom.dcmread(rt_structure_file_path, force=True)
                
                # Save to working directory
                autoseg_rt_path = os.path.join(working_dir, 'autoseg_rtstruct.dcm')
                ds_rt.save_as(autoseg_rt_path, enforce_file_format=True)
                logger.info(f"Saved autosegmented RT Structure to: {autoseg_rt_path}")
                
            except Exception as e:
                logger.error(f"Failed to save autosegmented RT Structure: {e}")
                return None, None, None
        
        # 3. Save reference RT Structure file if provided
        reference_rt_path = None
        if uploaded_reference_file:
            try:
                # Read uploaded file
                ds_ref = pydicom.dcmread(uploaded_reference_file, force=True)
                
                # Save to working directory
                reference_rt_path = os.path.join(working_dir, 'reference_rtstruct.dcm')
                ds_ref.save_as(reference_rt_path, enforce_file_format=True)
                logger.info(f"Saved reference RT Structure to: {reference_rt_path}")
                
            except Exception as e:
                logger.error(f"Failed to save reference RT Structure: {e}")
                return None, None, None
        
        return working_dir, autoseg_rt_path, reference_rt_path
        
    except Exception as e:
        logger.error(f"Error preparing working directory: {e}")
        return None, None, None


@login_required
def compare_with_reference(request):
    """
    Step 1: View to select a series that has RT Structure files.
    Shows existing comparisons for the selected series.
    """
    from dicom_handler.models import DICOMSeries, RTStructureFileImport
    
    # Get all series that have RT Structure files
    series_with_rtstructs = DICOMSeries.objects.filter(
        rtstructurefileimport__isnull=False
    ).distinct().select_related('study__patient').prefetch_related('rtstructurefileimport_set')
    
    # Get selected series ID from GET parameter or session
    selected_series_id = request.GET.get('series_id') or request.session.get('selected_series_id')
    existing_comparisons = []
    selected_series = None
    
    if selected_series_id:
        try:
            selected_series = DICOMSeries.objects.get(id=selected_series_id)
            # Get all comparisons for this series
            # Find comparisons where either RT Structure references this series
            existing_comparisons = RTStructureFileComparison.objects.filter(
                models.Q(first_rtstructure__rtstructure_set_file__referenced_series_instance_uid=selected_series.series_instance_uid) |
                models.Q(second_rtstructure__rtstructure_set_file__referenced_series_instance_uid=selected_series.series_instance_uid)
            ).select_related(
                'first_rtstructure__rtstructure_set_file',
                'second_rtstructure__rtstructure_set_file',
                'user'
            ).prefetch_related('comparisonresult_set').order_by('-created_at')
        except DICOMSeries.DoesNotExist:
            pass
    
    if request.method == 'POST':
        try:
            series_id = request.POST.get('series_id')
            
            if not series_id:
                messages.error(request, "Please select a series")
                return redirect('spatial_overlap:compare_with_reference')
            
            # Store series ID in session and redirect to RT Structure selection
            request.session['selected_series_id'] = series_id
            return redirect('spatial_overlap:select_rtstruct_for_comparison')
        except Exception as e:
            logger.error(f"Error in compare_with_reference: {str(e)}")
            messages.error(request, f"Error: {str(e)}")
            return redirect('spatial_overlap:compare_with_reference')
    
    context = {
        'series_with_rtstructs': series_with_rtstructs,
        'selected_series': selected_series,
        'existing_comparisons': existing_comparisons,
        'selected_series_id': selected_series_id
    }
    return render(request, 'spatial_overlap/compare_with_reference.html', context)


@login_required
def select_rtstruct_for_comparison(request):
    """
    Step 2: Select which RT Structure to compare and upload reference RT Structure.
    Creates a working directory with DICOM images and both RT Structure files.
    """
    from dicom_handler.models import DICOMSeries, RTStructureFileImport, DICOMInstance
    import pydicom
    import tempfile
    import os
    import shutil
    
    # Get series from session
    series_id = request.session.get('selected_series_id')
    if not series_id:
        messages.error(request, "Please select a series first")
        return redirect('spatial_overlap:compare_with_reference')
    
    try:
        series = DICOMSeries.objects.get(id=series_id)
    except DICOMSeries.DoesNotExist:
        messages.error(request, "Series not found")
        return redirect('spatial_overlap:compare_with_reference')
    
    # Get all RT Structures for this series
    rt_structures = series.rtstructurefileimport_set.all()
    
    if not rt_structures.exists():
        messages.error(request, "No RT Structures found for this series")
        return redirect('spatial_overlap:compare_with_reference')
    
    if request.method == 'POST':
        tmp_path = None
        try:
            rt_import_id = request.POST.get('rt_import_id')
            reference_file = request.FILES.get('reference_file')
            
            if not rt_import_id:
                messages.error(request, "Please select an RT Structure")
                return redirect('spatial_overlap:select_rtstruct_for_comparison')
            
            if not reference_file:
                messages.error(request, "Please upload a reference RT Structure file")
                return redirect('spatial_overlap:select_rtstruct_for_comparison')
            
            # Get selected RT Structure
            rt_import = RTStructureFileImport.objects.get(id=rt_import_id)
            
            # Get reidentified RT Structure file path
            rt_file_path = rt_import.reidentified_rt_structure_file_path
            if not rt_file_path:
                messages.error(request, "Reidentified RT Structure file not found.")
                return redirect('spatial_overlap:select_rtstruct_for_comparison')
            
            if not os.path.exists(rt_file_path):
                messages.error(request, f"RT Structure file not found at path: {rt_file_path}")
                return redirect('spatial_overlap:select_rtstruct_for_comparison')
            
            # Save uploaded reference to temporary file
            with tempfile.NamedTemporaryFile(delete=False, suffix='.dcm') as tmp_file:
                for chunk in reference_file.chunks():
                    tmp_file.write(chunk)
                tmp_path = tmp_file.name
            
            try:
                ds = pydicom.dcmread(tmp_path, force=True)
                
                # Validate modality is RTSTRUCT
                modality = str(getattr(ds, 'Modality', ''))
                if modality != 'RTSTRUCT':
                    messages.error(request, f"Invalid file: Expected RTSTRUCT modality, got '{modality}'. Please upload a valid RT Structure file.")
                    return redirect('spatial_overlap:select_rtstruct_for_comparison')
                
                # Extract referenced series UID from RT Structure
                referenced_series_uid_from_file = None
                if hasattr(ds, 'ReferencedFrameOfReferenceSequence'):
                    for ref_frame in ds.ReferencedFrameOfReferenceSequence:
                        if hasattr(ref_frame, 'RTReferencedStudySequence'):
                            for ref_study in ref_frame.RTReferencedStudySequence:
                                if hasattr(ref_study, 'RTReferencedSeriesSequence'):
                                    for ref_series in ref_study.RTReferencedSeriesSequence:
                                        if hasattr(ref_series, 'SeriesInstanceUID'):
                                            referenced_series_uid_from_file = str(ref_series.SeriesInstanceUID)
                                            break
                
                # Validate that the referenced series UID matches the image series (not the RT Structure series)
                if referenced_series_uid_from_file:
                    if referenced_series_uid_from_file != series.series_instance_uid:
                        messages.error(
                            request, 
                            f"RT Structure validation failed: The uploaded RT Structure references series '{referenced_series_uid_from_file}' "
                            f"but the selected image series is '{series.series_instance_uid}'. "
                            f"Please upload an RT Structure that was created from the same image series."
                        )
                        return redirect('spatial_overlap:select_rtstruct_for_comparison')
                    logger.info(f"Validated: RT Structure references correct image series {series.series_instance_uid}")
                else:
                    logger.warning("No referenced series UID found in RT Structure file")
                    messages.warning(
                        request,
                        "Warning: Could not find referenced series UID in the RT Structure file. "
                        "Proceeding but metrics computation may fail if the RT Structure doesn't match the image series."
                    )
                
                # Prepare working directory with DICOM images and both RT Structure files
                logger.info("Preparing working directory with DICOM images and RT Structure files")
                working_dir, autoseg_rt_path, reference_rt_path = prepare_working_directory_for_comparison(
                    series, rt_file_path, tmp_path
                )
                
                if not working_dir:
                    messages.error(request, "Failed to prepare working directory. Please check logs for details.")
                    return redirect('spatial_overlap:select_rtstruct_for_comparison')
                
                logger.info(f"Working directory created at: {working_dir}")
                logger.info(f"Autosegmented RT Structure: {autoseg_rt_path}")
                logger.info(f"Reference RT Structure: {reference_rt_path}")
                
                # Extract metadata from reference
                patient_name = str(getattr(ds, 'PatientName', 'Reference'))
                patient_id = str(getattr(ds, 'PatientID', 'Reference'))
                study_instance_uid = str(getattr(ds, 'StudyInstanceUID', ''))
                series_instance_uid = str(getattr(ds, 'SeriesInstanceUID', ''))
                sop_instance_uid = str(getattr(ds, 'SOPInstanceUID', ''))
                structure_set_label = str(getattr(ds, 'StructureSetLabel', 'Reference'))
                
                # Get structure set date
                structure_set_date = None
                if hasattr(ds, 'StructureSetDate'):
                    date_str = ds.StructureSetDate
                    from datetime import datetime
                    structure_set_date = datetime.strptime(date_str, '%Y%m%d').date()
                
                # Create RTStructureSetFile for reference
                reference_rtstruct = RTStructureSetFile.objects.create(
                    patient_name=f"{patient_name} (Reference)",
                    patient_id=f"{patient_id} (Reference)",
                    study_instance_uid=study_instance_uid,
                    series_instance_uid=series_instance_uid,
                    sop_instance_uid=sop_instance_uid,
                    structure_set_label=f"{structure_set_label} (Reference)",
                    referenced_series_instance_uid=series.series_instance_uid,
                    structure_set_date=structure_set_date,
                    rtstructure_file_path=reference_rt_path,
                    working_directory=working_dir
                )
                
                # Extract VOIs from reference
                if hasattr(ds, 'StructureSetROISequence'):
                    for roi in ds.StructureSetROISequence:
                        roi_name = str(getattr(roi, 'ROIName', 'Unknown'))
                        roi_description = str(getattr(roi, 'ROIDescription', ''))
                        roi_number = int(getattr(roi, 'ROINumber', 0))
                        
                        RTStructureSetVOI.objects.create(
                            rtstructure_set_file=reference_rtstruct,
                            roi_name=roi_name,
                            roi_description=roi_description,
                            roi_volume=None,
                            roi_number=roi_number
                        )
                
                # Create or update RTStructureSetFile for autosegmented
                autoseg_rtstruct = RTStructureSetFile.objects.filter(
                    sop_instance_uid=rt_import.deidentified_sop_instance_uid
                ).first()
                
                # Parse the autosegmented RT Structure file from working directory
                ds_auto = pydicom.dcmread(autoseg_rt_path, force=True)
                
                # Extract RT Structure's own identifiers from DICOM file
                rt_study_uid = str(getattr(ds_auto, 'StudyInstanceUID', series.study.study_instance_uid))
                rt_series_uid = str(getattr(ds_auto, 'SeriesInstanceUID', ''))
                
                if not autoseg_rtstruct:
                    # Create new record
                    autoseg_rtstruct = RTStructureSetFile.objects.create(
                        patient_name=series.study.patient.patient_name,
                        patient_id=series.study.patient.patient_id,
                        study_instance_uid=rt_study_uid,
                        series_instance_uid=rt_series_uid,  # RT Structure's own series UID
                        sop_instance_uid=rt_import.deidentified_sop_instance_uid,
                        structure_set_label=f"Autosegmented - {series.series_description or 'Unknown'}",
                        referenced_series_instance_uid=series.series_instance_uid,  # Image series UID
                        structure_set_date=series.series_date,
                        rtstructure_file_path=autoseg_rt_path,  # Path in working directory
                        working_directory=working_dir  # Same working directory
                    )
                    
                    # Extract VOIs from autosegmented (only for new records)
                    if hasattr(ds_auto, 'StructureSetROISequence'):
                        for roi in ds_auto.StructureSetROISequence:
                            roi_name = str(getattr(roi, 'ROIName', 'Unknown'))
                            roi_description = str(getattr(roi, 'ROIDescription', ''))
                            roi_number = int(getattr(roi, 'ROINumber', 0))
                            
                            RTStructureSetVOI.objects.create(
                                rtstructure_set_file=autoseg_rtstruct,
                                roi_name=roi_name,
                                roi_description=roi_description,
                                roi_volume=None,
                                roi_number=roi_number
                            )
                else:
                    # Update existing record with new working directory paths
                    autoseg_rtstruct.rtstructure_file_path = autoseg_rt_path
                    autoseg_rtstruct.working_directory = working_dir
                    autoseg_rtstruct.save()
                
                # Store in session for next step
                request.session['comparison_rtstruct1_id'] = str(autoseg_rtstruct.id) if autoseg_rtstruct else None
                request.session['comparison_rtstruct2_id'] = str(reference_rtstruct.id)
                request.session['comparison_series_id'] = str(series.id)
                
                messages.success(request, f"Reference RT Structure uploaded successfully. Found {reference_rtstruct.vois.count()} VOIs.")
                return redirect('spatial_overlap:create_comparisons')
                
            finally:
                # Clean up temporary file
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                    
        except Exception as e:
            logger.error(f"Error in select_rtstruct_for_comparison: {str(e)}")
            messages.error(request, f"Error: {str(e)}")
            return redirect('spatial_overlap:select_rtstruct_for_comparison')
    
    context = {
        'series': series,
        'rt_structures': rt_structures
    }
    return render(request, 'spatial_overlap/select_rtstruct_for_comparison.html', context)


@login_required
def upload_rtstruct(request):
    """
    View to upload RT Structure Set files.
    """
    if request.method == 'POST':
        try:
            # Handle file upload
            uploaded_file = request.FILES.get('rtstruct_file')
            if not uploaded_file:
                messages.error(request, "No file uploaded")
                return redirect('spatial_overlap:upload_rtstruct')
            
            # Parse DICOM file
            import pydicom
            import tempfile
            import os
            
            # Save to temporary file
            with tempfile.NamedTemporaryFile(delete=False, suffix='.dcm') as tmp_file:
                for chunk in uploaded_file.chunks():
                    tmp_file.write(chunk)
                tmp_path = tmp_file.name
            
            try:
                ds = pydicom.dcmread(tmp_path)
                
                # Extract metadata
                patient_name = str(getattr(ds, 'PatientName', 'Unknown'))
                patient_id = str(getattr(ds, 'PatientID', 'Unknown'))
                study_instance_uid = str(getattr(ds, 'StudyInstanceUID', ''))
                series_instance_uid = str(getattr(ds, 'SeriesInstanceUID', ''))
                sop_instance_uid = str(getattr(ds, 'SOPInstanceUID', ''))
                structure_set_label = str(getattr(ds, 'StructureSetLabel', 'Unknown'))
                
                # Get referenced series UID
                referenced_series_uid = ''
                if hasattr(ds, 'ReferencedFrameOfReferenceSequence'):
                    for ref_frame in ds.ReferencedFrameOfReferenceSequence:
                        if hasattr(ref_frame, 'RTReferencedStudySequence'):
                            for ref_study in ref_frame.RTReferencedStudySequence:
                                if hasattr(ref_study, 'RTReferencedSeriesSequence'):
                                    for ref_series in ref_study.RTReferencedSeriesSequence:
                                        if hasattr(ref_series, 'SeriesInstanceUID'):
                                            referenced_series_uid = ref_series.SeriesInstanceUID
                                            break
                
                # Get structure set date
                structure_set_date = None
                if hasattr(ds, 'StructureSetDate'):
                    date_str = ds.StructureSetDate
                    from datetime import datetime
                    structure_set_date = datetime.strptime(date_str, '%Y%m%d').date()
                
                # Create RTStructureSetFile
                rtstruct_file = RTStructureSetFile.objects.create(
                    patient_name=patient_name,
                    patient_id=patient_id,
                    study_instance_uid=study_instance_uid,
                    series_instance_uid=series_instance_uid,
                    sop_instance_uid=sop_instance_uid,
                    structure_set_label=structure_set_label,
                    referenced_series_instance_uid=referenced_series_uid,
                    structure_set_date=structure_set_date
                )
                
                # Save the uploaded file
                rtstruct_file.rtstructure_file.save(uploaded_file.name, uploaded_file)
                
                # Extract VOIs
                if hasattr(ds, 'StructureSetROISequence'):
                    for roi in ds.StructureSetROISequence:
                        roi_name = str(getattr(roi, 'ROIName', 'Unknown'))
                        roi_description = str(getattr(roi, 'ROIDescription', ''))
                        roi_number = int(getattr(roi, 'ROINumber', 0))
                        
                        # Calculate volume if possible (placeholder for now)
                        roi_volume = None
                        
                        RTStructureSetVOI.objects.create(
                            rtstructure_set_file=rtstruct_file,
                            roi_name=roi_name,
                            roi_description=roi_description,
                            roi_volume=roi_volume,
                            roi_number=roi_number
                        )
                
                messages.success(request, f"Successfully uploaded RT Structure Set: {structure_set_label}")
                return redirect('spatial_overlap:list_rtstructs')
                
            finally:
                # Clean up temporary file
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                    
        except Exception as e:
            logger.error(f"Error uploading RT Structure Set: {str(e)}")
            messages.error(request, f"Error uploading file: {str(e)}")
            return redirect('spatial_overlap:upload_rtstruct')
    
    return render(request, 'spatial_overlap/upload_rtstruct.html')


@login_required
def list_rtstructs(request):
    """
    View to list all uploaded RT Structure Set files.
    """
    rtstructs = RTStructureSetFile.objects.all().prefetch_related('vois')
    context = {
        'rtstructs': rtstructs
    }
    return render(request, 'spatial_overlap/list_rtstructs.html', context)


@login_required
def rtstruct_detail(request, rtstruct_id):
    """
    View to show details of a specific RT Structure Set file.
    """
    rtstruct = get_object_or_404(RTStructureSetFile, id=rtstruct_id)
    vois = rtstruct.vois.all()
    
    context = {
        'rtstruct': rtstruct,
        'vois': vois
    }
    return render(request, 'spatial_overlap/rtstruct_detail.html', context)


@login_required
def select_comparison_pairs(request):
    """
    View to select VOI pairs for comparison from two RT Structure Sets.
    """
    if request.method == 'POST':
        try:
            rtstruct1_id = request.POST.get('rtstruct1_id')
            rtstruct2_id = request.POST.get('rtstruct2_id')
            
            if not rtstruct1_id or not rtstruct2_id:
                messages.error(request, "Please select two RT Structure Sets")
                return redirect('spatial_overlap:select_comparison_pairs')
            
            # Store in session for next step
            request.session['comparison_rtstruct1_id'] = rtstruct1_id
            request.session['comparison_rtstruct2_id'] = rtstruct2_id
            
            return redirect('spatial_overlap:create_comparisons')
            
        except Exception as e:
            logger.error(f"Error selecting RT Structure Sets: {str(e)}")
            messages.error(request, f"Error: {str(e)}")
    
    rtstructs = RTStructureSetFile.objects.all()
    context = {
        'rtstructs': rtstructs
    }
    return render(request, 'spatial_overlap/select_comparison_pairs.html', context)


@login_required
def create_comparisons(request):
    """
    View to create VOI pair comparisons between two selected RT Structure Sets.
    """
    rtstruct1_id = request.session.get('comparison_rtstruct1_id')
    rtstruct2_id = request.session.get('comparison_rtstruct2_id')
    
    if not rtstruct1_id or not rtstruct2_id:
        messages.error(request, "Please select RT Structure Sets first")
        return redirect('spatial_overlap:select_comparison_pairs')
    
    rtstruct1 = get_object_or_404(RTStructureSetFile, id=rtstruct1_id)
    rtstruct2 = get_object_or_404(RTStructureSetFile, id=rtstruct2_id)
    
    if request.method == 'POST':
        try:
            # Get VOI pairs from array-based form data
            voi1_ids = request.POST.getlist('voi1[]')
            voi2_ids = request.POST.getlist('voi2[]')
            
            if not voi1_ids or not voi2_ids:
                messages.error(request, "Please select at least one VOI pair")
                return redirect('spatial_overlap:create_comparisons')
            
            if len(voi1_ids) != len(voi2_ids):
                messages.error(request, "Mismatched VOI pair data")
                return redirect('spatial_overlap:create_comparisons')
            
            created_count = 0
            skipped_count = 0
            with transaction.atomic():
                for voi1_id, voi2_id in zip(voi1_ids, voi2_ids):
                    # Skip empty selections
                    if not voi1_id or not voi2_id:
                        continue
                    
                    try:
                        voi1 = RTStructureSetVOI.objects.get(id=voi1_id)
                        voi2 = RTStructureSetVOI.objects.get(id=voi2_id)
                        
                        # Check if comparison already exists
                        existing = RTStructureFileComparison.objects.filter(
                            first_rtstructure=voi1,
                            second_rtstructure=voi2
                        ).first()
                        
                        if not existing:
                            # Also check reverse order
                            existing = RTStructureFileComparison.objects.filter(
                                first_rtstructure=voi2,
                                second_rtstructure=voi1
                            ).first()
                        
                        if not existing:
                            RTStructureFileComparison.objects.create(
                                first_rtstructure=voi1,
                                second_rtstructure=voi2,
                                user=request.user
                            )
                            created_count += 1
                        else:
                            skipped_count += 1
                            logger.info(f"Skipped duplicate comparison: {voi1.roi_name} vs {voi2.roi_name}")
                    except RTStructureSetVOI.DoesNotExist:
                        logger.error(f"VOI not found: {voi1_id} or {voi2_id}")
                        continue
            
            if created_count > 0:
                messages.success(request, f"Created {created_count} comparison(s)")
            if skipped_count > 0:
                messages.info(request, f"Skipped {skipped_count} duplicate comparison(s)")
            
            return redirect('spatial_overlap:list_comparisons')
            
        except Exception as e:
            logger.error(f"Error creating comparisons: {str(e)}")
            messages.error(request, f"Error: {str(e)}")
    
    vois1 = rtstruct1.vois.all()
    vois2 = rtstruct2.vois.all()
    
    # Find matching VOI names (exact string match)
    voi1_names = {voi.roi_name: voi for voi in vois1}
    voi2_names = {voi.roi_name: voi for voi in vois2}
    
    # Get exact matches
    matching_pairs = []
    for name in voi1_names.keys():
        if name in voi2_names:
            matching_pairs.append({
                'voi1': voi1_names[name],
                'voi2': voi2_names[name],
                'name': name
            })
    
    context = {
        'rtstruct1': rtstruct1,
        'rtstruct2': rtstruct2,
        'vois1': vois1,
        'vois2': vois2,
        'matching_pairs': matching_pairs
    }
    return render(request, 'spatial_overlap/create_comparisons.html', context)


@login_required
def list_comparisons(request):
    """
    View to list all created comparisons.
    """
    comparisons = RTStructureFileComparison.objects.all().select_related(
        'first_rtstructure__rtstructure_set_file',
        'second_rtstructure__rtstructure_set_file',
        'user'
    ).prefetch_related('comparisonresult_set')
    
    context = {
        'comparisons': comparisons
    }
    return render(request, 'spatial_overlap/list_comparisons.html', context)


@login_required
def compute_metrics(request, comparison_id):
    """
    View to compute metrics for a specific comparison.
    """
    comparison = get_object_or_404(RTStructureFileComparison, id=comparison_id)
    
    if request.method == 'POST':
        try:
            # Get optional DICOM series paths
            dicom_path_1 = request.POST.get('dicom_path_1', '').strip()
            dicom_path_2 = request.POST.get('dicom_path_2', '').strip()
            
            # Compute metrics
            metrics = compute_comparison_metrics(
                comparison,
                dicom_series_path_1=dicom_path_1 if dicom_path_1 else None,
                dicom_series_path_2=dicom_path_2 if dicom_path_2 else None
            )
            
            if metrics is None:
                messages.error(request, "Failed to compute metrics. RT Structure files may be missing or DICOM series not found in database. Please ensure RT Structure files were uploaded with actual DICOM files.")
                return redirect('spatial_overlap:comparison_detail', comparison_id=comparison_id)
            
            # Save results
            with transaction.atomic():
                # Delete existing results for this comparison
                ComparisonResult.objects.filter(comparison=comparison).delete()
                
                # Create new results
                results_created = 0
                for metric_key, metric_value in metrics.items():
                    if metric_value is not None:
                        ComparisonResult.objects.create(
                            comparison=comparison,
                            comparision_type=metric_key,
                            result_value=metric_value
                        )
                        results_created += 1
                        logger.info(f"Saved metric {metric_key}: {metric_value}")
            
            logger.info(f"Total results saved: {results_created}")
            messages.success(request, f"Metrics computed successfully. {results_created} metrics saved.")
            return redirect('spatial_overlap:comparison_detail', comparison_id=comparison_id)
            
        except Exception as e:
            logger.error(f"Error computing metrics: {str(e)}")
            messages.error(request, f"Error computing metrics: {str(e)}")
    
    return redirect('spatial_overlap:comparison_detail', comparison_id=comparison_id)


@login_required
def comparison_detail(request, comparison_id):
    """
    View to show details and results of a specific comparison.
    """
    comparison = get_object_or_404(
        RTStructureFileComparison.objects.select_related(
            'first_rtstructure__rtstructure_set_file',
            'second_rtstructure__rtstructure_set_file',
            'user'
        ),
        id=comparison_id
    )
    
    results = ComparisonResult.objects.filter(comparison=comparison)
    
    # Organize results by metric type
    results_dict = {}
    for result in results:
        metric_label = dict(ComparisionTypeChoices.choices).get(result.comparision_type, result.comparision_type)
        results_dict[metric_label] = result.result_value
    
    context = {
        'comparison': comparison,
        'results': results,
        'results_dict': results_dict,
        'has_results': results.exists()
    }
    return render(request, 'spatial_overlap/comparison_detail.html', context)


@login_required
def delete_comparison(request, comparison_id):
    """
    View to delete a comparison.
    """
    comparison = get_object_or_404(RTStructureFileComparison, id=comparison_id)
    
    if request.method == 'POST':
        try:
            comparison.delete()
            messages.success(request, "Comparison deleted successfully")
            return redirect('spatial_overlap:list_comparisons')
        except Exception as e:
            logger.error(f"Error deleting comparison: {str(e)}")
            messages.error(request, f"Error: {str(e)}")
    
    return redirect('spatial_overlap:list_comparisons')


@login_required
@require_http_methods(["POST"])
def batch_compute_metrics(request):
    """
    AJAX view to compute metrics for multiple comparisons.
    """
    try:
        data = json.loads(request.body)
        comparison_ids = data.get('comparison_ids', [])
        
        if not comparison_ids:
            return JsonResponse({'error': 'No comparisons selected'}, status=400)
        
        success_count = 0
        error_count = 0
        
        for comp_id in comparison_ids:
            try:
                comparison = RTStructureFileComparison.objects.get(id=comp_id)
                metrics = compute_comparison_metrics(comparison)
                
                if metrics:
                    with transaction.atomic():
                        ComparisonResult.objects.filter(comparison=comparison).delete()
                        for metric_key, metric_value in metrics.items():
                            if metric_value is not None:
                                ComparisonResult.objects.create(
                                    comparison=comparison,
                                    comparision_type=metric_key,
                                    result_value=metric_value
                                )
                    success_count += 1
                else:
                    error_count += 1
            except Exception as e:
                logger.error(f"Error computing metrics for comparison {comp_id}: {str(e)}")
                error_count += 1
        
        return JsonResponse({
            'success': True,
            'success_count': success_count,
            'error_count': error_count
        })
        
    except Exception as e:
        logger.error(f"Error in batch compute: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def bulk_compute_metrics_async(request):
    """
    Start bulk computation of metrics for selected comparisons using Celery.
    """
    if request.method == 'POST':
        try:
            comparison_ids = request.POST.getlist('comparison_ids[]')
            
            if not comparison_ids:
                return JsonResponse({'error': 'No comparisons selected'}, status=400)
            
            # Convert to integers
            comparison_ids = [int(cid) for cid in comparison_ids]
            
            # Start Celery task
            from .tasks import compute_metrics_bulk
            task = compute_metrics_bulk.delay(comparison_ids)
            
            logger.info(f"Started bulk compute task {task.id} for {len(comparison_ids)} comparisons")
            
            return JsonResponse({
                'success': True,
                'task_id': task.id,
                'total_comparisons': len(comparison_ids)
            })
            
        except Exception as e:
            logger.error(f"Error starting bulk compute: {str(e)}")
            return JsonResponse({'error': str(e)}, status=500)
    
    return JsonResponse({'error': 'Method not allowed'}, status=405)


@login_required
def bulk_compute_status(request, task_id):
    """
    Check the status of a bulk compute task.
    """
    from celery.result import AsyncResult
    
    task = AsyncResult(task_id)
    
    if task.state == 'PENDING':
        response = {
            'state': task.state,
            'current': 0,
            'total': 1,
            'status': 'Pending...'
        }
    elif task.state != 'FAILURE':
        response = {
            'state': task.state,
            'current': task.info.get('current', 0),
            'total': task.info.get('total', 1),
            'status': task.info.get('description', ''),
        }
        if task.state == 'SUCCESS':
            response['result'] = task.info
    else:
        response = {
            'state': task.state,
            'current': 1,
            'total': 1,
            'status': str(task.info),
        }
    
    return JsonResponse(response)


@login_required
def series_comparisons(request, series_instance_uid):
    """
    View to show all comparisons for a specific series.
    """
    from dicom_handler.models import DICOMSeries
    
    try:
        series = DICOMSeries.objects.select_related('study__patient').get(
            series_instance_uid=series_instance_uid
        )
    except DICOMSeries.DoesNotExist:
        messages.error(request, "Series not found")
        return redirect('spatial_overlap:list_rtstructs')
    
    # Get all comparisons for this series
    comparisons = RTStructureFileComparison.objects.filter(
        models.Q(first_rtstructure__rtstructure_set_file__referenced_series_instance_uid=series_instance_uid) |
        models.Q(second_rtstructure__rtstructure_set_file__referenced_series_instance_uid=series_instance_uid)
    ).select_related(
        'first_rtstructure__rtstructure_set_file',
        'second_rtstructure__rtstructure_set_file',
        'user'
    ).prefetch_related('comparisonresult_set').order_by('-created_at')
    
    context = {
        'series': series,
        'comparisons': comparisons
    }
    return render(request, 'spatial_overlap/series_comparisons.html', context)


@login_required
def all_metrics_view(request):
    """
    View to display all spatial overlap metrics with filtering options.
    """
    # Get all comparison results with related data
    results = ComparisonResult.objects.select_related(
        'comparison__first_rtstructure__rtstructure_set_file',
        'comparison__second_rtstructure__rtstructure_set_file',
        'comparison__first_rtstructure',
        'comparison__second_rtstructure',
        'comparison__user'
    ).order_by('-created_at')
    
    # Get filter parameters
    metric_type = request.GET.get('metric_type', '')
    if metric_type:
        results = results.filter(comparision_type=metric_type)
    
    # Pagination info
    total_count = results.count()
    
    context = {
        'results': results[:1000],  # Limit to first 1000 for display
        'total_count': total_count,
        'metric_types': ComparisionTypeChoices.choices,
        'selected_metric_type': metric_type,
    }
    return render(request, 'spatial_overlap/all_metrics.html', context)


@login_required
def download_metrics_csv(request):
    """
    Download all spatial overlap metrics as a CSV file.
    """
    # Get all comparison results with related data
    results = ComparisonResult.objects.select_related(
        'comparison__first_rtstructure__rtstructure_set_file',
        'comparison__second_rtstructure__rtstructure_set_file',
        'comparison__first_rtstructure',
        'comparison__second_rtstructure',
        'comparison__user'
    ).order_by('-created_at')
    
    # Apply filters if provided
    metric_type = request.GET.get('metric_type', '')
    if metric_type:
        results = results.filter(comparision_type=metric_type)
    
    # Create the HttpResponse object with CSV header
    response = HttpResponse(content_type='text/csv')
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    response['Content-Disposition'] = f'attachment; filename="spatial_overlap_metrics_{timestamp}.csv"'
    
    writer = csv.writer(response)
    
    # Write header row
    writer.writerow([
        'Metric ID',
        'Comparison ID',
        'Metric Type',
        'Metric Value',
        'Patient ID',
        'Patient Name',
        'Study Instance UID',
        'Series Instance UID (First)',
        'Series Instance UID (Second)',
        'First RT Structure Set Label',
        'First RT Structure Set Name',
        'First ROI Name',
        'First ROI Number',
        'Second RT Structure Set Label',
        'Second RT Structure Set Name',
        'Second ROI Name',
        'Second ROI Number',
        'Comparison Created At',
        'Metric Created At',
        'Computed By User'
    ])
    
    # Write data rows
    for result in results:
        comparison = result.comparison
        first_rtstruct = comparison.first_rtstructure
        second_rtstruct = comparison.second_rtstructure
        first_rtset = first_rtstruct.rtstructure_set_file
        second_rtset = second_rtstruct.rtstructure_set_file
        
        # Patient and study info is stored directly in RTStructureSetFile
        patient_id = first_rtset.patient_id or 'N/A'
        patient_name = first_rtset.patient_name or 'N/A'
        study_instance_uid = first_rtset.study_instance_uid or 'N/A'
        
        writer.writerow([
            result.id,
            comparison.id,
            result.get_comparision_type_display(),
            result.result_value,
            patient_id,
            patient_name,
            study_instance_uid,
            first_rtset.referenced_series_instance_uid or 'N/A',
            second_rtset.referenced_series_instance_uid or 'N/A',
            first_rtset.structure_set_label or 'N/A',
            getattr(first_rtset, 'structure_set_name', 'N/A') or 'N/A',
            first_rtstruct.roi_name or 'N/A',
            first_rtstruct.roi_number or 'N/A',
            second_rtset.structure_set_label or 'N/A',
            getattr(second_rtset, 'structure_set_name', 'N/A') or 'N/A',
            second_rtstruct.roi_name or 'N/A',
            second_rtstruct.roi_number or 'N/A',
            comparison.created_at.strftime('%Y-%m-%d %H:%M:%S') if comparison.created_at else 'N/A',
            result.created_at.strftime('%Y-%m-%d %H:%M:%S') if result.created_at else 'N/A',
            comparison.user.username if comparison.user else 'N/A'
        ])
    
    logger.info(f"Downloaded {results.count()} metrics as CSV")
    return response
