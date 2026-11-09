import os

from celery import Celery
from celery.schedules import crontab

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'draw_client.settings')

app = Celery('draw_client')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Connection-safety and reliability defaults for long-running jobs.
# - prefetch multiplier 1: a worker only grabs one task at a time, so a slow
#   segmentation job does not lock up many queued messages.
# - acks_late: the message is acked after the task finishes; if a worker is
#   killed (e.g. OOM during heavy SimpleITK work) the task is redelivered
#   instead of silently lost.
app.conf.worker_prefetch_multiplier = 1
app.conf.task_acks_late = True
app.conf.task_reject_on_worker_lost = True


from celery.signals import task_postrun, worker_process_init, worker_shutting_down  # noqa: E402
from django.db import connections  # noqa: E402


@worker_process_init.connect(weak=False)
def _reset_db_connections_after_fork(*args, **kwargs):
    """Fork-safety: the prefork child inherits the parent's DB socket. Drop it
    so this child opens its own connection instead of sharing (and corrupting)
    the parent's."""
    connections.close_all()


@task_postrun.connect(weak=False)
def _close_db_connections_after_task(*args, **kwargs):
    """Celery does not fire Django's request_finished signal, so without this a
    worker holds its Postgres connection open for its entire life. Releasing it
    after every task keeps the steady-state connection count near zero and
    prevents Postgres max_connections exhaustion under load."""
    connections.close_all()


@worker_shutting_down.connect(weak=False)
def _close_db_connections_on_shutdown(*args, **kwargs):
    connections.close_all()

# Load task modules from all registered Django apps.
app.autodiscover_tasks()

# Explicitly import tasks to ensure registration
app.autodiscover_tasks(['dicom_handler', 'dicom_server'])

# Configure Celery Beat periodic tasks
app.conf.beat_schedule = {
    'check-storage-limits-every-10-minutes': {
        'task': 'dicom_server.tasks.check_storage_limits_periodic',
        'schedule': 600.0,  # 10 minutes in seconds
        'options': {'expires': 300}  # Expire if not run within 5 minutes
    },
}


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f'Request: {self.request.id}')