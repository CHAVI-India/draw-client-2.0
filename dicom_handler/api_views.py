"""
API views for DICOM export functionality
"""

import logging
import os
import shutil
from datetime import datetime
from pathlib import Path

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt

from .models import DICOMSeries, DICOMInstance, RTStructureFileImport

logger = logging.getLogger(__name__)


def sanitize_filename(filename):
    """
    Sanitize a filename to prevent path traversal attacks.
    Removes any directory separators and other dangerous characters.
    """
    if not filename:
        return "unnamed"
    # Replace directory separators and other potentially dangerous characters
    sanitized = filename.replace('/', '_').replace('\\', '_').replace('..', '_')
    # Remove null bytes
    sanitized = sanitized.replace('\x00', '')
    # Strip leading/trailing whitespace and dots
    sanitized = sanitized.strip(' .')
    return sanitized[:255]  # Limit length


def validate_path_within_base(path, base_dir):
    """
    Validate that a path is within the allowed base directory.
    Returns: (is_valid: bool, normalized_path: str or None)
    """
    try:
        base_dir = os.path.abspath(base_dir)
        normalized_path = os.path.abspath(os.path.normpath(path))

        # Check for null bytes
        if '\x00' in path:
            return False, None

        # Ensure the path starts with the base directory
        if not normalized_path.startswith(base_dir + os.sep) and normalized_path != base_dir:
            return False, None

        return True, normalized_path
    except Exception:
        return False, None


@login_required
@require_http_methods(["POST"])
def series_export_details(request):
    """
    Get series details for export modal including RT Structure counts.
    """
    import json
    
    try:
        data = json.loads(request.body)
        series_uids = data.get('series_uids', [])
        
        if not series_uids:
            return JsonResponse({
                'success': False,
                'error': 'No series UIDs provided'
            }, status=400)
        
        series_list = []
        for series_uid in series_uids:
            try:
                series = DICOMSeries.objects.select_related('study__patient').get(
                    series_instance_uid=series_uid
                )
                
                # Count RT structures
                rt_count = RTStructureFileImport.objects.filter(
                    deidentified_series_instance_uid=series,
                    reidentified_rt_structure_file_path__isnull=False
                ).count()
                
                series_info = {
                    'series_instance_uid': series.series_instance_uid,
                    'patient_id': series.study.patient.patient_id or 'N/A',
                    'patient_name': series.study.patient.patient_name or 'N/A',
                    'series_description': series.series_description or 'N/A',
                    'modality': series.study.study_modality or 'N/A',
                    'instance_count': series.instance_count or 0,
                    'rt_structure_count': rt_count
                }
                series_list.append(series_info)
                
            except DICOMSeries.DoesNotExist:
                logger.warning(f"Series not found: {series_uid}")
                continue
        
        return JsonResponse({
            'success': True,
            'series': series_list
        })
        
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON data'
        }, status=400)
    except Exception as e:
        logger.error(f"Error fetching series export details: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': 'An internal server error occurred'
        }, status=500)


@login_required
@require_http_methods(["POST"])
def export_dicom_series(request):
    """
    Export selected DICOM series (images and/or RT structures) to a folder.
    """
    import json
    from django.conf import settings
    
    try:
        data = json.loads(request.body)
        selections = data.get('selections', [])
        
        if not selections:
            return JsonResponse({
                'success': False,
                'error': 'No selections provided'
            }, status=400)
        
        # Create export directory
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        export_base = getattr(settings, 'DICOM_EXPORT_DIR', '/tmp/dicom_exports')
        export_dir = os.path.join(export_base, f'export_{timestamp}')
        os.makedirs(export_dir, exist_ok=True)
        
        total_files = 0
        
        for selection in selections:
            series_uid = selection.get('series_uid')
            include_images = selection.get('include_images', False)
            include_rtstruct = selection.get('include_rtstruct', False)
            
            try:
                series = DICOMSeries.objects.get(series_instance_uid=series_uid)

                # Sanitize series_uid to prevent path traversal
                safe_series_uid = sanitize_filename(series_uid)[:16]
                series_dir = os.path.join(export_dir, f'series_{safe_series_uid}')

                # Validate series_dir is within export_dir
                is_valid, validated_path = validate_path_within_base(series_dir, export_dir)
                if not is_valid:
                    logger.error(f"Invalid series directory path detected for series: {series_uid}")
                    continue
                series_dir = validated_path
                os.makedirs(series_dir, exist_ok=True)

                # Export images if requested
                if include_images:
                    instances = DICOMInstance.objects.filter(
                        series_instance_uid=series
                    )

                    for instance in instances:
                        if instance.instance_path and os.path.exists(instance.instance_path):
                            filename = os.path.basename(instance.instance_path)
                            # Sanitize filename
                            safe_filename = sanitize_filename(filename)
                            dest_path = os.path.join(series_dir, safe_filename)
                            # Validate dest_path is within series_dir
                            is_valid_dest, validated_dest_path = validate_path_within_base(dest_path, series_dir)
                            if not is_valid_dest:
                                logger.warning(f"Invalid destination path detected for file: {filename}")
                                continue
                            shutil.copy2(instance.instance_path, validated_dest_path)
                            total_files += 1

                # Export RT structures if requested
                if include_rtstruct:
                    rt_structs = RTStructureFileImport.objects.filter(
                        deidentified_series_instance_uid=series,
                        reidentified_rt_structure_file_path__isnull=False
                    )

                    for rt_struct in rt_structs:
                        if rt_struct.reidentified_rt_structure_file_path and \
                           os.path.exists(rt_struct.reidentified_rt_structure_file_path):
                            filename = os.path.basename(rt_struct.reidentified_rt_structure_file_path)
                            # Sanitize filename
                            safe_filename = sanitize_filename(filename)
                            dest_path = os.path.join(series_dir, safe_filename)
                            # Validate dest_path is within series_dir
                            is_valid_dest, validated_dest_path = validate_path_within_base(dest_path, series_dir)
                            if not is_valid_dest:
                                logger.warning(f"Invalid destination path detected for RT struct: {filename}")
                                continue
                            shutil.copy2(rt_struct.reidentified_rt_structure_file_path, validated_dest_path)
                            total_files += 1
                
            except DICOMSeries.DoesNotExist:
                logger.warning(f"Series not found: {series_uid}")
                continue
            except Exception as e:
                logger.error(f"Error exporting series {series_uid}: {str(e)}")
                continue
        
        return JsonResponse({
            'success': True,
            'total_files': total_files,
            'export_path': export_dir
        })
        
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON data'
        }, status=400)
    except Exception as e:
        logger.error(f"Error exporting DICOM series: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': 'An internal server error occurred during export'
        }, status=500)
