"""
Celery tasks for preparing DICOM viewer data.

Preparing the viewer (copying the series from the shared drive, sorting the
slices, parsing the RT structure and pre-building every structure mask) can
take minutes, so it runs as a Celery task instead of blocking an HTTP
request. Progress is written to the Django cache under a per-session key;
the viewer page polls ``get_dicom_load_progress`` while the task runs.
"""
import logging

from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from importlib import import_module

from .dicom_viewer_views import prepare_dicom_viewer_data

logger = logging.getLogger(__name__)

# Progress records live a bit longer than the default cache timeout so a slow
# run is never lost mid-flight.
PROGRESS_TIMEOUT = 3600


def viewer_progress_key(session_key):
    return f"viewer_progress_{session_key}"


def _write_progress(session_key, payload):
    cache.set(viewer_progress_key(session_key), payload, timeout=PROGRESS_TIMEOUT)


@shared_task(bind=True, name='dicom_handler.prepare_dicom_viewer')
def prepare_dicom_viewer_task(self, session_key, series_uid, rt_structure_id):
    """
    Prepare viewer data in the background and record progress in the cache.

    On success the temporary directory and RT structure paths are stored in
    the user's session (out-of-band, by session key) and the progress record
    carries the viewer metadata (slice count, ROI names and colors).
    """
    logger.info(f"prepare_dicom_viewer {self.request.id}: series={series_uid} rt={rt_structure_id}")

    copy_total = 0

    def progress(stage, done, total):
        nonlocal copy_total
        if stage == 'copy' and total:
            copy_total = total
        _write_progress(session_key, {
            'stage': stage,
            'copy': {'done': done if stage == 'copy' else copy_total,
                     'total': total if stage == 'copy' else copy_total},
            'structures': {'done': done if stage == 'structures' else 0,
                           'total': total if stage == 'structures' else 0},
        })

    try:
        result = prepare_dicom_viewer_data(series_uid, rt_structure_id, progress=progress)

        # Store the prep results in the user's session (out-of-band; the task
        # has no request object, so update the session by its key).
        backend = import_module(settings.SESSION_ENGINE)
        store = backend.SessionStore(session_key=session_key)
        store['dicom_temp_dir'] = result['temp_dir']
        store['rt_struct_path'] = result['temp_rt_struct']
        store.save()

        _write_progress(session_key, {
            'stage': 'done',
            'copy': {'done': copy_total, 'total': copy_total},
            'structures': {'done': len(result['roi_names']), 'total': len(result['roi_names'])},
            'instance_count': len(result['instance_files']),
            'roi_names': result['roi_names'],
            'roi_colors': result['roi_colors'],
        })
        logger.info(f"prepare_dicom_viewer {self.request.id}: done "
                    f"({len(result['instance_files'])} slices, {len(result['roi_names'])} ROIs)")
    except Exception as e:
        logger.exception(f"prepare_dicom_viewer {self.request.id} failed: {e}")
        _write_progress(session_key, {'stage': 'error', 'error': str(e)})
