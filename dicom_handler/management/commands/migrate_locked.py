"""Run ``manage.py migrate`` under a Postgres advisory lock.

Why this exists
---------------
django-web, celery and celery-beat all start from the same image and the same
entrypoint, so a plain ``docker compose up`` used to kick off three concurrent
``migrate`` runs against one database. They interleave: one container creates a
table while another is halfway through the migration that populates it, and the
result is DuplicateTable/DuplicateColumn errors, deadlocks, or a lock wait that
just looks like a hang.

``migrate_locked`` serializes them. The first caller takes a session-level
advisory lock and migrates; every other caller blocks on that same lock and, by
the time it is its turn, finds nothing left to do.

Advisory locks are the right tool here because they need no extra tables or
objects in the database, they are released automatically when the session ends,
and so a container that is OOM-killed or ``docker kill``\ ed mid-migration can
never leave the schema wedged behind a lock.

This is defense in depth. The compose stack now runs migrations in a single
one-shot service with ``RUN_MIGRATIONS=false`` on the long-running containers.
If someone scales a replica, applies a compose override, or runs the image with
``docker run`` by hand, the advisory lock still keeps them out of each other's
way.
"""
import os
import time

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import connection

# Fixed key shared by every container in this project. Any integer that no other
# application on the same Postgres instance uses will do; override with
# MIGRATE_ADVISORY_LOCK_KEY if this database is shared with something else.
DEFAULT_LOCK_KEY = 72_713_001

# Seconds to wait for another container's migration before giving up. Long
# enough for a real migration run, short enough that a stuck container is
# reported rather than waiting forever.
DEFAULT_LOCK_TIMEOUT = 1800

POLL_SECONDS = 3


class Command(BaseCommand):
    help = (
        "Apply database migrations, waiting for any other container that is "
        "already migrating (Postgres advisory lock)."
    )

    # migrate does its own database work; no system checks beforehand.
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument(
            "migrate_args",
            nargs="*",
            help="Passed straight through to `manage.py migrate`, e.g. an app label.",
        )
        parser.add_argument(
            "--database", default="default", help="Database alias to migrate."
        )
        parser.add_argument(
            "--lock-timeout",
            type=int,
            default=int(os.getenv("MIGRATE_LOCK_TIMEOUT", DEFAULT_LOCK_TIMEOUT)),
            help=(
                "Seconds to wait for another container's migration before "
                "failing. Default: %(default)s."
            ),
        )
        parser.add_argument(
            "--lock-key",
            type=int,
            default=int(os.getenv("MIGRATE_ADVISORY_LOCK_KEY", DEFAULT_LOCK_KEY)),
            help="Advisory lock key; must match across containers. Default: %(default)s.",
        )
        parser.add_argument(
            "--interactive",
            action="store_true",
            help=(
                "Let migrate prompt for confirmation. Off by default: a "
                "container that stops to ask a question just hangs until it is "
                "killed, so the entrypoint must never block on input."
            ),
        )
        parser.add_argument(
            "--noinput",
            "--no-input",
            action="store_true",
            help=(
                "Accepted for familiarity with `manage.py migrate --noinput`. "
                "This command is already non-interactive, so it is a no-op."
            ),
        )
        parser.add_argument(
            "--skip-lock",
            action="store_true",
            help="Run plain migrate without taking the advisory lock.",
        )

    def handle(self, *args, **options):
        alias = options["database"]
        # `skip_checks` is deliberately not forwarded: requires_system_checks is
        # empty above, exactly like `migrate` itself, so this parser never has a
        # --skip-checks flag to read.
        migrate_kwargs = {
            "database": alias,
            "interactive": options["interactive"],
            "verbosity": options["verbosity"],
        }

        if options["skip_lock"]:
            call_command("migrate", *options["migrate_args"], **migrate_kwargs)
            return

        if connection.vendor != "postgresql":
            # No advisory locks on SQLite, and a single-file database cannot be
            # migrated from two containers at once anyway.
            self.stdout.write(
                f"Advisory locking supports Postgres only ({connection.vendor}); "
                "running migrate directly."
            )
            call_command("migrate", *options["migrate_args"], **migrate_kwargs)
            return

        key = options["lock_key"]
        timeout = options["lock_timeout"]

        # The lock is taken on the default connection and held for the whole
        # run: `migrate` uses this same connection object and does not close it,
        # and a session-level lock survives every per-migration transaction. If
        # the process dies the backend session ends and Postgres releases it.
        connection.ensure_connection()
        with connection.cursor() as cursor:
            acquired = False
            deadline = time.monotonic() + timeout
            while True:
                cursor.execute("SELECT pg_try_advisory_lock(%s)", [key])
                acquired = bool(cursor.fetchone()[0])
                if acquired:
                    break
                if time.monotonic() >= deadline:
                    raise SystemExit(
                        f"Timed out after {timeout}s waiting for another container to "
                        f"finish migrating (advisory lock key {key}). Set "
                        "MIGRATE_LOCK_TIMEOUT higher if the migration legitimately "
                        "takes longer, or check pg_stat_activity for a stuck session."
                    )
                self.stdout.write(
                    f"Another container is migrating; waiting "
                    f"({int(time.monotonic() - (deadline - timeout))}s of {timeout}s)..."
                )
                time.sleep(POLL_SECONDS)

            try:
                started = time.monotonic()
                self.stdout.write(f"Migration lock acquired (key {key}).")
                call_command("migrate", *options["migrate_args"], **migrate_kwargs)
                self.stdout.write(
                    f"Migrations finished in {time.monotonic() - started:.1f}s; "
                    "releasing lock."
                )
            finally:
                try:
                    cursor.execute("SELECT pg_advisory_unlock(%s)", [key])
                except Exception as exc:  # pragma: no cover - backend went away
                    # A dropped backend releases a session lock by itself; the
                    # only real risk would be masking the migration's own error.
                    self.stderr.write(f"Could not explicitly release the lock: {exc}")
