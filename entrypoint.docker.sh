#!/bin/bash

# Note: CA certificates update must be done at build time or with root privileges
# If you need to update CA certificates, uncomment the volume mount in docker-compose
# and rebuild the image with root user

# Create staticfiles directory if it doesn't exist
# No need to chown since we're already running as appuser
mkdir -p /app/staticfiles

# Collect static files
python manage.py collectstatic --noinput

# Apply database migrations
python manage.py migrate

# Create superuser if it doesn't exist
python manage.py createsuperuser --noinput --username $DJANGO_SUPERUSER_USERNAME --email $DJANGO_SUPERUSER_EMAIL

# Check if we're running Celery worker
if [ "$1" = "celery" ]; then
    exec celery -A draw_client worker -l INFO
# Check if we're running Celery beat
elif [ "$1" = "celery-beat" ]; then
    exec celery -A draw_client beat -l INFO
# Default to running Django with Gunicorn
else
    exec python -m gunicorn draw_client.wsgi:application \
        --bind 0.0.0.0:8000 \
        --workers 4 \
        --threads 2 \
        --worker_class gthread \
        --timeout 1800 \
        --keep-alive 2 \
        --max-requests 1000 \
        --max-requests-jitter 50 \
        --preload
fi

# Execute the main command
exec "$@"