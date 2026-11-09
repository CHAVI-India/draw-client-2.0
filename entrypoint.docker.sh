#!/bin/bash

# Note: CA certificates update must be done at build time or with root privileges
# If you need to update CA certificates, uncomment the volume mount in docker-compose
# and rebuild the image with root user

# Note: Tailwind CSS is pre-built during Docker image build (see Dockerfile)
# The output.css file is already available in /app/static/css/output.css

# Create staticfiles directory if it doesn't exist
# No need to chown since we're already running as appuser
mkdir -p /app/staticfiles

# Collect static files (includes pre-built Tailwind CSS)
python manage.py collectstatic --noinput

# Apply database migrations
python manage.py migrate

# Create superuser if it doesn't exist
python manage.py createsuperuser --noinput --username $DJANGO_SUPERUSER_USERNAME --email $DJANGO_SUPERUSER_EMAIL

# Check if we're running Celery worker
if [ "$1" = "celery" ]; then
    # Bound worker concurrency explicitly. Without -c/-P, Celery defaults
    # concurrency to the host CPU count, so in Docker (which sees every host
    # core unless capped) it would spawn far more worker processes than
    # Postgres max_connections allows. Each prefork child holds one DB
    # connection, so we cap children and recycle them to release connections
    # and memory. All tunable via env, with conservative defaults.
    exec celery -A draw_client worker -l INFO \
        --pool=prefork \
        --concurrency="${CELERY_CONCURRENCY:-2}" \
        --prefetch-multiplier=1 \
        --max-tasks-per-child="${CELERY_MAX_TASKS_PER_CHILD:-20}"
# Check if we're running Celery beat
elif [ "$1" = "celery-beat" ]; then
    exec celery -A draw_client beat -l INFO
# Default to running Django with Gunicorn
else
    exec python -m gunicorn draw_client.wsgi:application \
        --bind 0.0.0.0:8000 \
        --workers 4 \
        --threads 2 \
        --worker-class gthread \
        --timeout 3600 \
        --keep-alive 2 \
        --max-requests 1000 \
        --max-requests-jitter 50 \
        --preload
fi

# Execute the main command
exec "$@"