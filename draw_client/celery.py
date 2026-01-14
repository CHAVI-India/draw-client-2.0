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
    print(f'Request: {self.request!r}')