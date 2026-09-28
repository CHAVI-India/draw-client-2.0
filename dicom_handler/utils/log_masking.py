import os
import re


def mask_sensitive_data(data, field_name=""):
    """
    Mask sensitive data for logging purposes.
    """
    if not data:
        return "***EMPTY***"

    # Mask patient identifiable information
    if any(field in field_name.lower() for field in ['name', 'id', 'birth', 'patient', 'token', 'bearer', 'secret', 'password']):
        return f"***{field_name.upper()}_MASKED***"

    # For UIDs, show only first and last 4 characters
    if 'uid' in field_name.lower() and len(str(data)) > 8:
        return f"{str(data)[:4]}...{str(data)[-4:]}"

    # For file paths, show only filename (with patient-identifying segments masked)
    if 'path' in field_name.lower() or 'dir' in field_name.lower():
        basename = os.path.basename(str(data))
        basename = re.sub(r'^(RS_)[^_]+(_DRAW_)', r'\1***\2', basename)
        return f"***PATH***/{basename}"

    return str(data)
