"""
Custom template filters for DICOM handler templates.
Provides dynamic field type detection and rendering utilities.
"""
import re
from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """
    Get an item from a dictionary by key.
    Usage: {{ my_dict|get_item:"my_key" }}
    """
    if isinstance(dictionary, dict):
        return dictionary.get(key)
    return None


@register.filter
def humanize_field(field_name):
    """
    Convert a field name to a human-readable label.
    E.g., 'delineation_guideline' -> 'Delineation Guideline'
    E.g., 'left_border_description' -> 'Left Border Description'
    """
    if not field_name:
        return ""

    # Replace underscores with spaces
    label = field_name.replace('_', ' ')

    # Handle camelCase by inserting spaces
    label = re.sub(r'(?<!^)(?=[A-Z])', ' ', label)

    # Capitalize each word
    label = label.title()

    # Common acronym handling
    acronyms = {
        'Url': 'URL',
        'Id': 'ID',
        'Api': 'API',
        'Http': 'HTTP',
        'Https': 'HTTPS',
        'Dice': 'DICE',
        'Ct': 'CT',
        'Mr': 'MR',
        'Mrn': 'MRN',
        'Rt': 'RT',
        'Roi': 'ROI',
        'Tv': 'TV',
        'Gtv': 'GTV',
        'Ctv': 'CTV',
        'Itv': 'ITV',
        'Ptv': 'PTV',
        'Dicom': 'DICOM',
        'Dvh': 'DVH',
        'Pacs': 'PACS',
        'Hl7': 'HL7',
        'Fhir': 'FHIR',
        'Tg263': 'TG263',
        'Ai': 'AI',
        'Ml': 'ML',
    }

    for old, new in acronyms.items():
        label = re.sub(r'\b' + old + r'\b', new, label)

    return label


@register.filter
def is_image_field(field_name):
    """
    Check if a field name suggests it contains image data.
    Returns True for fields like 'delineation_image', 'reference_photo', 'contour_diagram', etc.
    """
    if not field_name:
        return False

    image_keywords = [
        'image', 'photo', 'picture', 'diagram', 'illustration',
        'drawing', 'sketch', 'figure', 'scan', 'slice',
        'contour_drawing', 'delineation_image', 'reference_image',
        'atlas_image', 'example_image', 'guideline_image',
        'border_image', 'anatomy_image', 'segmentation_example',
    ]

    field_lower = field_name.lower()
    return any(keyword in field_lower for keyword in image_keywords)


@register.filter
def is_url_field(field_name):
    """
    Check if a field name suggests it contains a URL.
    Returns True for fields like 'reference_url', 'documentation_link', etc.
    """
    if not field_name:
        return False

    url_keywords = [
        'url', 'link', 'href', 'reference', 'documentation',
        'manual', 'protocol', 'website', 'webpage',
        'source', 'external', 'citation', 'paper', 'article',
    ]

    field_lower = field_name.lower()
    return any(keyword in field_lower for keyword in url_keywords)


@register.filter
def is_url(value):
    """
    Check if a value appears to be a URL.
    Returns True for strings starting with http://, https://, ftp://, etc.
    """
    if not isinstance(value, str):
        return False

    url_pattern = re.compile(
        r'^(?:http|ftp)s?://'  # http://, https://, ftp://, ftps://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|'  # domain
        r'localhost|'  # localhost
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # or IP
        r'(?::\d+)?'  # optional port
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)

    return bool(url_pattern.match(value.strip())) if value else False


@register.filter
def is_image_value(value):
    """
    Check if a value appears to be image data.
    Returns True for:
    - Base64 encoded image strings (data:image/...)
    - URLs ending in image extensions
    """
    if not isinstance(value, str):
        return False

    if not value:
        return False

    # Check for base64 image data URI
    if value.startswith('data:image/'):
        return True

    # Check for image file extensions
    image_extensions = ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.svg', '.tiff']
    value_lower = value.lower()
    return any(value_lower.endswith(ext) for ext in image_extensions)


@register.filter
def is_base64_image(value):
    """
    Check if a value is a base64 encoded image.
    Returns True for data:image/... strings.
    """
    if not isinstance(value, str):
        return False

    return value.startswith('data:image/')


@register.filter
def is_number(value):
    """
    Check if a value is a number (int or float).
    """
    if value is None:
        return False

    if isinstance(value, (int, float)):
        # Exclude booleans (which are subclass of int)
        return not isinstance(value, bool)

    # Try to convert string to number
    if isinstance(value, str):
        try:
            float(value)
            return True
        except (ValueError, TypeError):
            return False

    return False
