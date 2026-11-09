"""Add the DICOM UID uniqueness constraints that 0057 prepares the data for.

Why this migration is separate from 0057
----------------------------------------
0057 merges duplicate study/series/instance rows. When both lived in the same
migration, Django wrapped the merge DML and the ``ALTER TABLE ... ADD
CONSTRAINT`` DDL in one transaction, and Postgres refused the DDL with::

    OperationalError: cannot ALTER TABLE "dicom_handler_dicomstudy"
                      because it has pending trigger events

because the row triggers queued by the merge had not fired yet. By the time this
migration runs, 0057 has committed, so the table is free to alter.

Why the constraints are not plain ``AddConstraint`` operations
-------------------------------------------------------------
``AddConstraint`` builds the backing unique index inside a transaction while
holding an ACCESS EXCLUSIVE lock on the table. On these three tables that lock
blocks every request and every Celery task for the whole build. Because the
migration is ``atomic = False``, we can instead:

    1. CREATE UNIQUE INDEX CONCURRENTLY   (no blocking write lock)
    2. ALTER TABLE ... ADD CONSTRAINT ... UNIQUE USING INDEX   (fast metadata op)

``SeparateDatabaseAndState`` keeps the constraint in Django's model state, so
``makemigrations`` still sees the models as consistent with the database.

Re-runnability
--------------
Every step is guarded, because a migration that fails halfway must be re-runnable:

* constraint already present -> skip (environments where the old 0057 ran with
  the constraints, or a previous attempt that completed this step)
* index present and valid, constraint missing -> promote it (step 2 only)
* index present but INVALID (a failed ``CREATE UNIQUE INDEX CONCURRENTLY``
  leaves one behind) -> drop it concurrently and rebuild

Note for non-Postgres (SQLite development) databases: SQLite cannot add a
constraint to an existing table at all, so the database side is skipped with a
warning there. The state side is still applied; the constraint is simply only
enforced on Postgres, as is the case for anything else this project relies on
that SQLite does not support.
"""
from django.db import connection, migrations, models

# (model_name, [field names], constraint name)
UNIQUE_CONSTRAINTS = [
    (
        "dicomstudy",
        ["patient", "study_instance_uid"],
        "uniq_dicomstudy_patient_study_uid",
    ),
    (
        "dicomseries",
        ["study", "series_instance_uid"],
        "uniq_dicomseries_study_series_uid",
    ),
    (
        "dicominstance",
        ["series_instance_uid", "sop_instance_uid"],
        "uniq_dicominstance_series_sop_uid",
    ),
]


def _table_and_columns(apps, model_name, fields):
    """Resolve model field names to real table/column names (FKs end in _id)."""
    model = apps.get_model("dicom_handler", model_name)
    return model._meta.db_table, [model._meta.get_field(f).column for f in fields]


def _constraint_exists(table, name):
    """True when the real table constraint is already in the catalogue."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM pg_constraint WHERE conrelid = %s::regclass AND conname = %s",
            [table, name],
        )
        return cursor.fetchone() is not None


def _index_is_valid(table, name):
    """None: no such index. False: index exists but is INVALID. True: usable."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT i.indisvalid
              FROM pg_index i
              JOIN pg_class c ON c.oid = i.indexrelid
              JOIN pg_class t ON t.oid = i.indrelid
             WHERE c.relname = %s AND t.oid = %s::regclass
            """,
            [name, table],
        )
        row = cursor.fetchone()
        return None if row is None else bool(row[0])


def _build_index_concurrently(cursor, quote, table, columns, name):
    """CREATE UNIQUE INDEX CONCURRENTLY, leaving no INVALID index behind.

    A concurrent build that finds duplicate rows does not raise; it leaves an
    INVALID index. That leftover is dropped so the next attempt starts clean
    instead of tripping over it.
    """
    cursor.execute(
        "CREATE UNIQUE INDEX CONCURRENTLY {} ON {} ({})".format(
            quote(name),
            quote(table),
            ", ".join(quote(col) for col in columns),
        )
    )
    if not _index_is_valid(table, name):
        cursor.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {quote(name)}")
        raise RuntimeError(
            f"[uniq] {name}: unique index on {table} ({', '.join(columns)}) is still "
            "invalid after a concurrent build, which means duplicate rows remain. "
            "Run 'python manage.py detect_dicom_dupes' and re-apply 0057, then "
            "re-run migrate."
        )


def _add_unique_constraint(apps, model_name, fields, name):
    table, columns = _table_and_columns(apps, model_name, fields)
    quote = connection.ops.quote_name

    if connection.vendor != "postgresql":
        print(
            f"[uniq] {name}: skipped on {connection.vendor} "
            "(no online ALTER TABLE ... ADD CONSTRAINT); enforced on Postgres only."
        )
        return

    if _constraint_exists(table, name):
        print(f"[uniq] {name}: already present on {table}, skipping.")
        return

    with connection.cursor() as cursor:
        existing_index = _index_is_valid(table, name)
        if existing_index is None:
            _build_index_concurrently(cursor, quote, table, columns, name)
            print(f"[uniq] {name}: built concurrently on {table}.")
        elif existing_index is False:
            # Leftover INVALID index from a previous failed attempt: rebuild it.
            print(f"[uniq] {name}: dropping INVALID leftover index on {table}.")
            cursor.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {quote(name)}")
            _build_index_concurrently(cursor, quote, table, columns, name)
            print(f"[uniq] {name}: rebuilt concurrently on {table}.")
        else:
            # A previous attempt completed the build but not the promotion.
            print(
                f"[uniq] {name}: valid index already built on {table}, "
                "attaching constraint."
            )

        # Promotes the index into a real constraint, matching what a plain
        # AddConstraint would have created. Requires index and constraint to
        # share a name, which they do.
        cursor.execute(
            'ALTER TABLE {} ADD CONSTRAINT "{}" UNIQUE USING INDEX "{}"'.format(
                quote(table), name, name
            )
        )
        print(f"[uniq] {name}: constraint added to {table}.")


def _drop_unique_constraint(apps, model_name, fields, name):
    table, _ = _table_and_columns(apps, model_name, fields)
    if connection.vendor != "postgresql":
        return
    with connection.cursor() as cursor:
        cursor.execute(
            'ALTER TABLE {} DROP CONSTRAINT IF EXISTS "{}"'.format(
                connection.ops.quote_name(table), name
            )
        )
    print(f"[uniq] {name}: removed from {table}.")


def _forwards(model_name, fields, name):
    def run(apps, schema_editor):
        _add_unique_constraint(apps, model_name, fields, name)

    return run


def _backwards(model_name, fields, name):
    def run(apps, schema_editor):
        _drop_unique_constraint(apps, model_name, fields, name)

    return run


def _operation(model_name, fields, name):
    return migrations.SeparateDatabaseAndState(
        state_operations=[
            migrations.AddConstraint(
                model_name=model_name,
                constraint=models.UniqueConstraint(fields=fields, name=name),
            )
        ],
        database_operations=[
            migrations.RunPython(
                _forwards(model_name, fields, name),
                _backwards(model_name, fields, name),
            )
        ],
    )


class Migration(migrations.Migration):

    # Needed for CREATE/DROP INDEX CONCURRENTLY, which cannot run inside a
    # transaction block.
    atomic = False

    dependencies = [
        ("dicom_handler", "0058_excludedfilepaths"),
    ]

    operations = [_operation(*spec) for spec in UNIQUE_CONSTRAINTS]
