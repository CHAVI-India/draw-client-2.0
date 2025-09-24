"""
Manual Autosegmentation API Views

This module provides API endpoints for the manual autosegmentation functionality,
allowing users to manually select templates for DICOM series and trigger processing.
"""

import json
import logging
from typing import List, Dict, Any

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.views import View
from django.core.exceptions import ValidationError
from django.utils import timezone

from .utils.manual_autosegmentation import (
    get_series_for_manual_selection,
    validate_template_associations,
    trigger_manual_autosegmentation_chain,
    trigger_manual_autosegmentation_async,
    get_manual_processing_status,
    get_available_templates,
    cancel_manual_processing
)

logger = logging.getLogger(__name__)


def mask_sensitive_data(data, field_name=""):
    """
    Mask sensitive DICOM data for logging purposes
    """
    if not data:
        return "***EMPTY***"
    
    # Mask patient identifiable information
    if any(field in field_name.lower() for field in ['name', 'id', 'birth', 'patient']):
        return f"***{field_name.upper()}_MASKED***"
    
    # For UIDs, show only first and last 4 characters
    if 'uid' in field_name.lower() and len(str(data)) > 8:
        return f"{str(data)[:4]}...{str(data)[-4:]}"
    
    return str(data)


@method_decorator([login_required, csrf_exempt], name='dispatch')
class ManualAutosegmentationSeriesInfoView(View):
    """
    API endpoint to retrieve series information for manual template selection
    """
    
    def post(self, request):
        try:
            logger.info(f"ManualAutosegmentationSeriesInfoView POST called")
            logger.info(f"Request body: {request.body}")
            
            # Parse request data
            data = json.loads(request.body)
            series_uids = data.get('series_uids', [])
            
            logger.info(f"Parsed series_uids: {series_uids}")
            
            if not series_uids:
                logger.warning("No series UIDs provided")
                return JsonResponse({
                    'status': 'error',
                    'message': 'No series UIDs provided'
                }, status=400)
            
            if not isinstance(series_uids, list):
                logger.warning("series_uids is not a list")
                return JsonResponse({
                    'status': 'error',
                    'message': 'series_uids must be a list'
                }, status=400)
            
            logger.info(f"Retrieving series information for {len(series_uids)} series UIDs")
            
            # Get series information
            result = get_series_for_manual_selection(series_uids)
            
            logger.info(f"get_series_for_manual_selection returned: {result}")
            
            if result['status'] == 'success':
                logger.info(f"Successfully retrieved information for {len(result['series_data'])} series")
                return JsonResponse(result)
            else:
                logger.error(f"Failed to retrieve series information: {result.get('message', 'Unknown error')}")
                return JsonResponse(result, status=500)
                
        except json.JSONDecodeError:
            logger.error("Invalid JSON in request body")
            return JsonResponse({
                'status': 'error',
                'message': 'Invalid JSON in request body'
            }, status=400)
        except Exception as e:
            logger.error(f"Unexpected error in series info retrieval: {str(e)}")
            return JsonResponse({
                'status': 'error',
                'message': 'Internal server error'
            }, status=500)


@method_decorator([login_required, csrf_exempt], name='dispatch')
class ManualAutosegmentationValidateView(View):
    """
    API endpoint to validate template associations before processing
    """
    
    def post(self, request):
        try:
            # Parse request data
            data = json.loads(request.body)
            template_associations = data.get('template_associations', [])
            
            if not template_associations:
                return JsonResponse({
                    'status': 'error',
                    'message': 'No template associations provided'
                }, status=400)
            
            if not isinstance(template_associations, list):
                return JsonResponse({
                    'status': 'error',
                    'message': 'template_associations must be a list'
                }, status=400)
            
            logger.info(f"Validating {len(template_associations)} template associations")
            
            # Validate template associations
            result = validate_template_associations(template_associations)
            
            if result['status'] == 'success':
                logger.info(f"Successfully validated {len(result['validated_associations'])} associations")
            else:
                logger.warning(f"Validation failed with {len(result.get('errors', []))} errors")
            
            return JsonResponse(result)
                
        except json.JSONDecodeError:
            logger.error("Invalid JSON in request body")
            return JsonResponse({
                'status': 'error',
                'message': 'Invalid JSON in request body'
            }, status=400)
        except Exception as e:
            logger.error(f"Unexpected error in validation: {str(e)}")
            return JsonResponse({
                'status': 'error',
                'message': 'Internal server error'
            }, status=500)


@method_decorator([login_required, csrf_exempt], name='dispatch')
class ManualAutosegmentationStartProcessingView(View):
    """
    API endpoint to start manual autosegmentation processing
    """
    
    def post(self, request):
        try:
            # Parse request data
            data = json.loads(request.body)
            template_associations = data.get('template_associations', [])
            async_processing = data.get('async_processing', True)
            
            if not template_associations:
                return JsonResponse({
                    'status': 'error',
                    'message': 'No template associations provided'
                }, status=400)
            
            if not isinstance(template_associations, list):
                return JsonResponse({
                    'status': 'error',
                    'message': 'template_associations must be a list'
                }, status=400)
            
            logger.info(f"Starting manual autosegmentation processing for {len(template_associations)} associations (async: {async_processing})")
            
            # Start processing
            if async_processing:
                result = trigger_manual_autosegmentation_async(template_associations)
            else:
                result = trigger_manual_autosegmentation_chain(template_associations)
            
            if result['status'] in ['success', 'initiated']:
                logger.info(f"Successfully started processing for {len(template_associations)} series")
                return JsonResponse(result)
            else:
                logger.error(f"Failed to start processing: {result.get('message', 'Unknown error')}")
                return JsonResponse(result, status=500)
                
        except json.JSONDecodeError:
            logger.error("Invalid JSON in request body")
            return JsonResponse({
                'status': 'error',
                'message': 'Invalid JSON in request body'
            }, status=400)
        except Exception as e:
            logger.error(f"Unexpected error starting processing: {str(e)}")
            return JsonResponse({
                'status': 'error',
                'message': 'Internal server error'
            }, status=500)


@method_decorator([login_required, csrf_exempt], name='dispatch')
class ManualAutosegmentationStatusView(View):
    """
    API endpoint to get processing status for manually processed series
    """
    
    def post(self, request):
        try:
            # Parse request data
            data = json.loads(request.body)
            series_uids = data.get('series_uids', [])
            
            if not series_uids:
                return JsonResponse({
                    'status': 'error',
                    'message': 'No series UIDs provided'
                }, status=400)
            
            if not isinstance(series_uids, list):
                return JsonResponse({
                    'status': 'error',
                    'message': 'series_uids must be a list'
                }, status=400)
            
            logger.info(f"Getting processing status for {len(series_uids)} series")
            
            # Get processing status
            result = get_manual_processing_status(series_uids)
            
            if result['status'] == 'success':
                logger.info(f"Successfully retrieved status for {len(result.get('series_status', []))} series")
            else:
                logger.warning(f"Status retrieval had issues: {result.get('message', 'Unknown error')}")
            
            return JsonResponse(result)
                
        except json.JSONDecodeError:
            logger.error("Invalid JSON in request body")
            return JsonResponse({
                'status': 'error',
                'message': 'Invalid JSON in request body'
            }, status=400)
        except Exception as e:
            logger.error(f"Unexpected error getting status: {str(e)}")
            return JsonResponse({
                'status': 'error',
                'message': 'Internal server error'
            }, status=500)


@method_decorator([login_required, csrf_exempt], name='dispatch')
class ManualAutosegmentationRetryView(View):
    """
    API endpoint to retry failed manual processing
    """
    
    def post(self, request):
        try:
            # Parse request data
            data = json.loads(request.body)
            series_uid = data.get('series_uid')
            
            if not series_uid:
                return JsonResponse({
                    'status': 'error',
                    'message': 'No series UID provided'
                }, status=400)
            
            logger.info(f"Retrying manual processing for series: {mask_sensitive_data(series_uid, 'series_uid')}")
            
            # For retry, we need to get the existing template association and restart processing
            # This is a simplified implementation - in practice you might want to store
            # the original template associations for retry purposes
            
            from .models import DICOMSeries
            try:
                series = DICOMSeries.objects.get(series_instance_uid=series_uid)
                matched_templates = series.matched_templates.all()
                
                if not matched_templates:
                    return JsonResponse({
                        'status': 'error',
                        'message': 'No template association found for retry'
                    }, status=400)
                
                # Create template association for retry
                template_associations = [{
                    'series_uid': series_uid,
                    'template_id': matched_templates.first().id
                }]
                
                # Retry with async processing
                result = trigger_manual_autosegmentation_async(template_associations)
                
                if result['status'] in ['success', 'initiated']:
                    logger.info(f"Successfully retried processing for series: {mask_sensitive_data(series_uid, 'series_uid')}")
                    return JsonResponse({
                        'status': 'success',
                        'message': 'Retry initiated successfully'
                    })
                else:
                    logger.error(f"Failed to retry processing: {result.get('message', 'Unknown error')}")
                    return JsonResponse(result, status=500)
                    
            except DICOMSeries.DoesNotExist:
                return JsonResponse({
                    'status': 'error',
                    'message': 'Series not found'
                }, status=404)
                
        except json.JSONDecodeError:
            logger.error("Invalid JSON in request body")
            return JsonResponse({
                'status': 'error',
                'message': 'Invalid JSON in request body'
            }, status=400)
        except Exception as e:
            logger.error(f"Unexpected error in retry: {str(e)}")
            return JsonResponse({
                'status': 'error',
                'message': 'Internal server error'
            }, status=500)


@method_decorator([login_required, csrf_exempt], name='dispatch')
class ManualAutosegmentationCancelView(View):
    """
    API endpoint to cancel manual processing
    """
    
    def post(self, request):
        try:
            # Parse request data
            data = json.loads(request.body)
            series_uids = data.get('series_uids', [])
            
            if not series_uids:
                return JsonResponse({
                    'status': 'error',
                    'message': 'No series UIDs provided'
                }, status=400)
            
            if not isinstance(series_uids, list):
                return JsonResponse({
                    'status': 'error',
                    'message': 'series_uids must be a list'
                }, status=400)
            
            logger.info(f"Cancelling manual processing for {len(series_uids)} series")
            
            # Cancel processing
            result = cancel_manual_processing(series_uids)
            
            if result['status'] == 'success':
                logger.info(f"Successfully cancelled processing for {result['cancelled_count']} series")
            else:
                logger.error(f"Failed to cancel processing: {result.get('message', 'Unknown error')}")
            
            return JsonResponse(result)
                
        except json.JSONDecodeError:
            logger.error("Invalid JSON in request body")
            return JsonResponse({
                'status': 'error',
                'message': 'Invalid JSON in request body'
            }, status=400)
        except Exception as e:
            logger.error(f"Unexpected error in cancellation: {str(e)}")
            return JsonResponse({
                'status': 'error',
                'message': 'Internal server error'
            }, status=500)


@login_required
@require_http_methods(["GET"])
def get_available_templates_view(request):
    """
    API endpoint to get available autosegmentation templates
    """
    try:
        logger.info("Retrieving available autosegmentation templates")
        
        # Get available templates
        result = get_available_templates()
        
        if result['status'] == 'success':
            logger.info(f"Successfully retrieved {len(result['templates'])} templates")
        else:
            logger.warning(f"Template retrieval had issues: {result.get('message', 'Unknown error')}")
        
        return JsonResponse(result)
        
    except Exception as e:
        logger.error(f"Unexpected error getting templates: {str(e)}")
        return JsonResponse({
            'status': 'error',
            'message': 'Internal server error'
        }, status=500)


@login_required
@require_http_methods(["GET"])
def test_api_endpoint(request):
    """
    Simple test endpoint to verify API is working
    """
    try:
        logger.info("Test API endpoint called")
        return JsonResponse({
            'status': 'success',
            'message': 'API is working correctly',
            'timestamp': timezone.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Test endpoint error: {str(e)}")
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)
