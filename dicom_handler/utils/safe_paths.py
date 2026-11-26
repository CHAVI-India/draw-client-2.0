"""
Validation helpers for file paths that were persisted in the database.

Stored paths (e.g. ``DICOMInstance.instance_path``,
``RTStructureSetFile.rtstructure_file_path``) are attacker-influenceable in
the "indirect path injection" sense: a malicious value written at ingestion
time (for example a crafted filename received over DICOM C-STORE) would be
re-used later in file operations.

``validate_stored_path`` is a cheap, deployment-agnostic guard to apply at
every use site: it rejects values that could enable directory traversal
(null bytes, explicit ``..`` path segments) while accepting any normal
absolute or relative path that the application itself produced.
"""
import os


def validate_stored_path(stored_path):
    """
    Return a normalized copy of a database-stored path, or ``None`` if the
    value is not a safe path to use in a file operation.

    Rejects:
      * empty / non-string values
      * values containing null bytes
      * values with an explicit ``..`` path segment (traversal attempts)

    Returns:
        The path normalized with ``os.path.normpath`` (collapses redundant
        separators and ``.`` segments) — never a path that can escape via
        ``..``.
    """
    if not stored_path or not isinstance(stored_path, str):
        return None
    if '\x00' in stored_path:
        return None
    if '..' in stored_path.split(os.sep):
        return None
    return os.path.normpath(stored_path)
