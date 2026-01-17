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
            'error': str(e)
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
                
                # Create series subdirectory
                series_dir = os.path.join(export_dir, f'series_{series_uid[:16]}')
                os.makedirs(series_dir, exist_ok=True)
                
                # Export images if requested
                if include_images:
                    instances = DICOMInstance.objects.filter(
                        series_instance_uid=series
                    )
                    
                    for instance in instances:
                        if instance.instance_path and os.path.exists(instance.instance_path):
                            filename = os.path.basename(instance.instance_path)
                            dest_path = os.path.join(series_dir, filename)
                            shutil.copy2(instance.instance_path, dest_path)
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
                            dest_path = os.path.join(series_dir, filename)
                            shutil.copy2(rt_struct.reidentified_rt_structure_file_path, dest_path)
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
            'error': str(e)
        }, status=500)
