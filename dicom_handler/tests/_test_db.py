"""Shared helper so every DB-touching test runs against a *dedicated test
database* instead of the configured dev/prod database (``draw_client``).

The standalone ``__main__`` scripts in this package connect to the database
directly via ``django.setup()`` + ORM writes.  Without isolation that would
read from — and, for the DICOM-ingest scripts, wipe — the live developer
database.  Everything here mirrors the pattern already used by the inline
``create_test_db(...)`` calls in the other tests, so the whole suite consistently
lands on ``test_<NAME>`` (an in-memory database when running on SQLite) and the
real database is left untouched.

Usage::

    from dicom_handler.tests._test_db import run_on_test_db, use_test_database

    @run_on_test_db
    def main():
        ...

    # or, when the work is not a single function:
    with use_test_database():
        ...
"""
from __future__ import annotations

import contextlib
import functools

from django.db import connections
from django.test.utils import setup_test_environment, teardown_test_environment


@contextlib.contextmanager
def use_test_database(verbosity: int = 1):
    """Create a separate test database, yield, then always destroy it.

    Safe against the dev/prod database: ``create_test_db`` targets the
    ``TEST['NAME']`` (defaults to ``test_<NAME>``) and ``autoclobber=True``
    lets it replace a leftover test database without prompting.
    """
    setup_test_environment()
    connection = connections["default"]
    test_db_name = connection.creation.create_test_db(
        verbosity=verbosity,
        autoclobber=True,
        keepdb=False,
    )
    try:
        yield test_db_name
    finally:
        connection.creation.destroy_test_db(test_db_name, verbosity=verbosity)
        teardown_test_environment()


def run_on_test_db(func=None, *, verbosity: int = 1):
    """Decorator that runs the wrapped callable entirely inside
    :func:`use_test_database`.  Handy for the ``main()``/``run_all_tests()``
    entry points of the standalone test scripts."""
    def decorate(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            with use_test_database(verbosity=verbosity):
                return fn(*args, **kwargs)
        return wrapper

    if func is not None:
        return decorate(func)
    return decorate
