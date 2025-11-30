"""
Celery tasks for spatial overlap metric computation.
"""
from celery import shared_task
from celery_progress.backend import ProgressRecorder
import logging

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def compute_metrics_bulk(self, comparison_ids):
    """
    Compute metrics for multiple comparisons in bulk.
    
    Args:
        comparison_ids (list): List of comparison IDs to process
        
    Returns:
        dict: Results summary with success/error counts
    """
    from .models import RTStructureFileComparison, ComparisonResult, ComparisionTypeChoices
    from .utils.compute_metrics import compute_comparison_metrics
    from django.db import transaction
    
    progress_recorder = ProgressRecorder(self)
    total = len(comparison_ids)
    success_count = 0
    error_count = 0
    results_summary = []
    
    for index, comparison_id in enumerate(comparison_ids):
        try:
            # Update progress
            progress_recorder.set_progress(index, total, description=f"Processing comparison {index + 1} of {total}")
            
            # Get comparison object
            comparison = RTStructureFileComparison.objects.select_related(
                'first_rtstructure__rtstructure_set_file',
                'second_rtstructure__rtstructure_set_file'
            ).get(id=comparison_id)
            
            logger.info(f"Computing metrics for comparison {comparison_id}: {comparison.first_rtstructure.roi_name} vs {comparison.second_rtstructure.roi_name}")
            
            # Compute metrics
            metrics = compute_comparison_metrics(comparison)
            
            if metrics:
                # Save results
                with transaction.atomic():
                    # Delete existing results for this comparison
                    ComparisonResult.objects.filter(comparison=comparison).delete()
                    
                    # Create new results
                    saved_count = 0
                    for metric_key, metric_value in metrics.items():
                        if metric_value is not None:
                            ComparisonResult.objects.create(
                                comparison=comparison,
                                comparision_type=metric_key,
                                result_value=metric_value
                            )
                            saved_count += 1
                    
                    logger.info(f"Saved {saved_count} metrics for comparison {comparison_id}")
                    success_count += 1
                    results_summary.append({
                        'id': comparison_id,
                        'status': 'success',
                        'metrics_count': saved_count,
                        'voi_pair': f"{comparison.first_rtstructure.roi_name} vs {comparison.second_rtstructure.roi_name}"
                    })
            else:
                error_count += 1
                logger.error(f"Failed to compute metrics for comparison {comparison_id}")
                results_summary.append({
                    'id': comparison_id,
                    'status': 'error',
                    'error': 'Metric computation returned None',
                    'voi_pair': f"{comparison.first_rtstructure.roi_name} vs {comparison.second_rtstructure.roi_name}"
                })
                
        except Exception as e:
            error_count += 1
            logger.error(f"Error computing metrics for comparison {comparison_id}: {str(e)}", exc_info=True)
            results_summary.append({
                'id': comparison_id,
                'status': 'error',
                'error': str(e)
            })
    
    # Final progress update
    progress_recorder.set_progress(total, total, description=f"Completed: {success_count} successful, {error_count} errors")
    
    return {
        'total': total,
        'success_count': success_count,
        'error_count': error_count,
        'results': results_summary
    }
