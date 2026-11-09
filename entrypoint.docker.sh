#!/bin/bash

# Entrypoint for every container built from this image. It has two jobs:
#
#   1. One-time preparation (collectstatic, migrations, superuser), done by
#      exactly ONE container.
#   2. Exec the long-running process for the role the container was asked to
#      play: gunicorn, a Celery worker, or Celery beat.
#
# Why the preparation is gated behind RUN_MIGRATIONS / the `migrate` mode
# ----------------------------------------------------------------------
# django-web, celery and celery-beat all call this same script, so every
# `docker compose up` used to start three or four concurrent `manage.py migrate`
# runs against one database. They interleave and produce DuplicateTable /
# DuplicateColumn errors, deadlocks, or lock waits that look like hangs. The
# compose stack now runs a dedicated one-shot `migrate` service and sets
# RUN_MIGRATIONS=false on the three long-running services, which also stops them
# from writing collectstatic output into the shared staticfiles volume at the
# same time.
#
# RUN_MIGRATIONS defaults to true so a bare `docker run <image>` still works.
# When it is true, the work goes through `manage.py migrate_locked`, which takes
# a Postgres advisory lock: even if two containers do arrive here together, they
# queue instead of corrupting each other.
#
# Modes:
#   migrate      -> run preparation, then exit 0 (the one-shot service)
#   celery       -> prepare if asked, then exec a Celery worker
#   celery-beat  -> prepare if asked, then exec Celery beat
#   django / ""  -> prepare if asked, then exec gunicorn
#   anything else-> prepare if asked, then exec the arguments verbatim

set -uo pipefail

RUN_MIGRATIONS="${RUN_MIGRATIONS:-true}"
MODE="${1:-django}"

# Preparation: the steps that must happen once, not once per container.
run_preparation() {
    echo "[prepare] starting one-time preparation (RUN_MIGRATIONS=${RUN_MIGRATIONS})"

    # Note: CA certificates update must be done at build time or with root
    # privileges. If you need to update CA certificates, uncomment the volume
    # mount in docker-compose and rebuild the image with root user.

    # Note: Tailwind CSS is pre-built during the image build (see Dockerfile);
    # output.css is already available in /app/static/css/output.css.

    # No chown needed: we already run as appuser and /app is owned by it.
    mkdir -p /app/staticfiles

    # Collect static files (includes the pre-built Tailwind CSS).
    python manage.py collectstatic --noinput || {
        echo "[prepare] collectstatic failed" >&2
        return 1
    }

    # Apply database migrations under an advisory lock, so a second container
    # that gets here at the same moment waits instead of racing.
    python manage.py migrate_locked || {
        echo "[prepare] migrations failed" >&2
        return 1
    }

    # Create the superuser if configured. Non-fatal by design: a missing
    # DJANGO_SUPERUSER_PASSWORD or an existing user must not stop the app from
    # booting, since both are normal in an established deployment.
    if [ -n "${DJANGO_SUPERUSER_USERNAME:-}" ] && [ -n "${DJANGO_SUPERUSER_PASSWORD:-}" ]; then
        local output status
        output=$(python manage.py createsuperuser --noinput \
                    --username "$DJANGO_SUPERUSER_USERNAME" \
                    --email "$DJANGO_SUPERUSER_EMAIL" 2>&1)
        status=$?
        if [ "$status" -ne 0 ]; then
            case "$output" in
                *"already taken"* | *"already exists"*)
                    echo "[prepare] superuser '$DJANGO_SUPERUSER_USERNAME' already exists"
                    ;;
                *)
                    echo "[prepare] createsuperuser skipped: ${output}"
                    ;;
            esac
        else
            echo "[prepare] superuser '$DJANGO_SUPERUSER_USERNAME' created"
        fi
    else
        echo "[prepare] DJANGO_SUPERUSER_USERNAME or DJANGO_SUPERUSER_PASSWORD unset; skipping superuser"
    fi

    echo "[prepare] done"
    return 0
}

# The one-shot migration container: prepare, report, exit. `depends_on:
# service_completed_successfully` in docker-compose keys off this exit code.
if [ "$MODE" = "migrate" ]; then
    run_preparation
    exit $?
fi

if [ "$RUN_MIGRATIONS" = "true" ]; then
    run_preparation || {
        echo "[entrypoint] refusing to start '$MODE': preparation failed" >&2
        exit 1
    }
else
    echo "[entrypoint] RUN_MIGRATIONS=${RUN_MIGRATIONS}; skipping collectstatic/migrations (handled by the migrate service)"
fi

case "$MODE" in
celery)
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
    ;;
celery-beat)
    exec celery -A draw_client beat -l INFO
    ;;
django | gunicorn)
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
    ;;
*)
    # Any other arguments are executed verbatim, e.g.
    #   command: ["./entrypoint.docker.sh", "python", "manage.py", "detect_dicom_dupes"]
    exec "$@"
    ;;
esac
