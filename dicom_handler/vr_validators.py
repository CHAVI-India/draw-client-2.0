"""
DICOM Value Representation (VR) validation utilities.

This module provides validation functions for DICOM VR types to ensure that
tag values conform to DICOM standards and are compatible with selected operators.
"""

import re
from datetime import datetime
from typing import List, Dict, Tuple, Optional
from django.core.exceptions import ValidationError


class VRValidator:
    """Main validator class for DICOM Value Representations."""
    
    # VR Categories for validation logic
    NUMERIC_VRS = {'FL', 'FD', 'SL', 'SS', 'UL', 'US', 'IS', 'DS'}
    STRING_VRS = {'AE', 'CS', 'LO', 'LT', 'PN', 'SH', 'ST', 'UT', 'UI'}
    DATETIME_VRS = {'DA', 'DT', 'TM'}
    SPECIAL_VRS = {'AS', 'AT', 'SQ', 'OB', 'OD', 'OF', 'OW', 'UN'}
    
    # Operator compatibility mapping
    NUMERIC_OPERATORS = {
        'EQUALS', 'NOT_EQUALS', 'GREATER_THAN', 'LESS_THAN',
        'GREATER_THAN_OR_EQUAL_TO', 'LESS_THAN_OR_EQUAL_TO'
    }
    
    STRING_OPERATORS = {
        'CASE_SENSITIVE_STRING_CONTAINS', 'CASE_INSENSITIVE_STRING_CONTAINS',
        'CASE_SENSITIVE_STRING_DOES_NOT_CONTAIN', 'CASE_INSENSITIVE_STRING_DOES_NOT_CONTAIN',
        'CASE_SENSITIVE_STRING_EXACT_MATCH', 'CASE_INSENSITIVE_STRING_EXACT_MATCH',
        'EQUALS', 'NOT_EQUALS'
    }
    
    @classmethod
    def validate_value_for_vr(cls, value: str, vr_code: str) -> Tuple[bool, str]:
        """
        Validate a value against its DICOM VR requirements.
        
        Args:
            value: The value to validate
            vr_code: The DICOM VR code (e.g., 'CS', 'IS', 'DA')
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not value or not vr_code:
            return True, ""
            
        validator_method = getattr(cls, f'_validate_{vr_code.lower()}', None)
        if validator_method:
            return validator_method(value)
        else:
            # For unknown VRs, just check basic constraints
            return cls._validate_unknown(value, vr_code)
    
    @classmethod
    def get_compatible_operators(cls, vr_code: str) -> List[str]:
        """Get list of operators compatible with the given VR."""
        if vr_code in cls.NUMERIC_VRS:
            return list(cls.NUMERIC_OPERATORS)
        elif vr_code in cls.STRING_VRS:
            return list(cls.STRING_OPERATORS)
        elif vr_code in cls.DATETIME_VRS:
            # Date/time VRs support both numeric (for ranges) and string operators
            return list(cls.NUMERIC_OPERATORS | cls.STRING_OPERATORS)
        else:
            # Special VRs - limited operator support
            return ['EQUALS', 'NOT_EQUALS']
    
    @classmethod
    def get_vr_guidance(cls, vr_code: str) -> Dict[str, str]:
        """Get user-friendly guidance for a VR type."""
        guidance = {
            'AE': {
                'description': 'Enter text string (letters, numbers, spaces) up to 16 characters',
                'format': 'String up to 16 characters, no backslash or control chars',
                'example': 'WORKSTATION1'
            },
            'AS': {
                'description': 'Enter age in format: number + D/W/M/Y (days/weeks/months/years)',
                'format': 'nnnD, nnnW, nnnM, or nnnY (days/weeks/months/years)',
                'example': '018M (18 months), 065Y (65 years)'
            },
            'AT': {
                'description': 'Enter DICOM tag in format (GGGG,EEEE) using hexadecimal numbers',
                'format': 'Hexadecimal tag in format (GGGG,EEEE)',
                'example': '(0018,00FF)'
            },
            'CS': {
                'description': 'Enter text string with uppercase letters, numbers, spaces, underscores only',
                'format': 'Uppercase letters, digits, space, underscore. Max 16 chars',
                'example': 'ORIGINAL, DERIVED'
            },
            'DA': {
                'description': 'Enter date in format YYYYMMDD (year, month, day as 8 digits)',
                'format': 'YYYYMMDD format',
                'example': '19930822 (August 22, 1993)'
            },
            'DS': {
                'description': 'Enter decimal number (can include decimal point and scientific notation)',
                'format': 'Fixed or floating point number. Max 16 chars',
                'example': '123.456, -0.5, 1.23E-4'
            },
            'DT': {
                'description': 'Enter date and time in format YYYYMMDDHHMMSS',
                'format': 'YYYYMMDDHHMMSS.FFFFFF&ZZXX',
                'example': '20230822143000.123456 (Aug 22, 2023 2:30 PM)'
            },
            'FL': {
                'description': 'Enter decimal number (floating point)',
                'format': 'IEEE 754 single precision floating point',
                'example': '123.456'
            },
            'FD': {
                'description': 'Enter decimal number (high precision floating point)',
                'format': 'IEEE 754 double precision floating point',
                'example': '123.456789012345'
            },
            'IS': {
                'description': 'Enter whole number (positive or negative integer)',
                'format': 'Integer in base-10, optional +/- sign. Max 12 chars',
                'example': '123, -456, +789'
            },
            'LO': {
                'description': 'Enter text string (letters, numbers, symbols) up to 64 characters',
                'format': 'Character string up to 64 characters',
                'example': 'Patient description or study notes'
            },
            'LT': {
                'description': 'Enter long text (can include multiple lines) up to 10,240 characters',
                'format': 'Text up to 10240 characters, may contain paragraphs',
                'example': 'Detailed clinical notes with multiple paragraphs'
            },
            'PN': {
                'description': 'Enter person name using ^ to separate: Family^Given^Middle^Prefix^Suffix',
                'format': 'Family^Given^Middle^Prefix^Suffix (up to 64 chars per group)',
                'example': 'Doe^John^Michael^Dr^Jr'
            },
            'SH': {
                'description': 'Enter short text string up to 16 characters',
                'format': 'Character string up to 16 characters',
                'example': 'Short description'
            },
            'SL': {
                'description': 'Enter whole number (32-bit signed integer)',
                'format': '32-bit signed integer (-2³¹ to 2³¹-1)',
                'example': '-2147483648 to 2147483647'
            },
            'SS': {
                'description': 'Enter whole number (16-bit signed integer)',
                'format': '16-bit signed integer (-32768 to 32767)',
                'example': '-32768 to 32767'
            },
            'ST': {
                'description': 'Enter text (can include multiple lines) up to 1,024 characters',
                'format': 'Text up to 1024 characters, may contain paragraphs',
                'example': 'Clinical findings or procedure notes'
            },
            'TM': {
                'description': 'Enter time in format HHMMSS (24-hour format)',
                'format': 'HHMMSS.FFFFFF (24-hour format)',
                'example': '143000.123456 (2:30 PM)'
            },
            'UI': {
                'description': 'Enter unique identifier with numbers separated by dots',
                'format': 'Numeric components separated by dots. Max 64 chars',
                'example': '1.2.840.10008.1.2.1'
            },
            'UL': {
                'description': 'Enter positive whole number (32-bit unsigned integer)',
                'format': '32-bit unsigned integer (0 to 2³²-1)',
                'example': '0 to 4294967295'
            },
            'US': {
                'description': 'Enter positive whole number (16-bit unsigned integer)',
                'format': '16-bit unsigned integer (0 to 65535)',
                'example': '0 to 65535'
            },
            'UT': {
                'description': 'Enter very long text (can include multiple paragraphs)',
                'format': 'Text up to 2³²-2 characters, may contain paragraphs',
                'example': 'Very long clinical reports or documentation'
            }
        }
        
        return guidance.get(vr_code, {
            'description': f'Enter value according to DICOM standard for {vr_code}',
            'format': 'See DICOM standard for format requirements',
            'example': 'Refer to DICOM documentation'
        })
    
    @classmethod
    def is_operator_compatible(cls, vr_code: str, operator: str) -> bool:
        """Check if an operator is compatible with a VR type."""
        compatible_operators = cls.get_compatible_operators(vr_code)
        return operator in compatible_operators
    
    # VR-specific validation methods
    
    @classmethod
    def _validate_ae(cls, value: str) -> Tuple[bool, str]:
        """Validate Application Entity (AE) value."""
        if len(value) > 16:
            return False, "Application Entity must be 16 characters or less"
        
        # Check for forbidden characters (backslash and control chars)
        if '\\' in value or any(ord(c) < 32 for c in value if c not in [' ']):
            return False, "Application Entity cannot contain backslash or control characters"
        
        return True, ""
    
    @classmethod
    def _validate_as(cls, value: str) -> Tuple[bool, str]:
        """Validate Age String (AS) value."""
        if len(value) != 4:
            return False, "Age String must be exactly 4 characters"
        
        pattern = r'^\d{3}[DWMY]$'
        if not re.match(pattern, value):
            return False, "Age String must be in format nnnD, nnnW, nnnM, or nnnY"
        
        return True, ""
    
    @classmethod
    def _validate_at(cls, value: str) -> Tuple[bool, str]:
        """Validate Attribute Tag (AT) value."""
        pattern = r'^\([0-9A-Fa-f]{4},[0-9A-Fa-f]{4}\)$'
        if not re.match(pattern, value):
            return False, "Attribute Tag must be in format (GGGG,EEEE) with hexadecimal values"
        
        return True, ""
    
    @classmethod
    def _validate_cs(cls, value: str) -> Tuple[bool, str]:
        """Validate Code String (CS) value."""
        if len(value) > 16:
            return False, "Code String must be 16 characters or less"
        
        # Check character repertoire: letters (case insensitive), digits, space, underscore
        pattern = r'^[A-Za-z0-9 _]*$'
        if not re.match(pattern, value):
            return False, "Code String can only contain letters, digits, spaces, and underscores"
        
        return True, ""
    
    @classmethod
    def _validate_da(cls, value: str) -> Tuple[bool, str]:
        """Validate Date (DA) value."""
        if len(value) != 8:
            return False, "Date must be exactly 8 characters in YYYYMMDD format"
        
        pattern = r'^\d{8}$'
        if not re.match(pattern, value):
            return False, "Date must contain only digits in YYYYMMDD format"
        
        # Validate actual date
        try:
            year = int(value[:4])
            month = int(value[4:6])
            day = int(value[6:8])
            datetime(year, month, day)
        except ValueError:
            return False, "Date must be a valid Gregorian calendar date"
        
        return True, ""
    
    @classmethod
    def _validate_ds(cls, value: str) -> Tuple[bool, str]:
        """Validate Decimal String (DS) value."""
        if len(value) > 16:
            return False, "Decimal String must be 16 characters or less"
        
        # Remove leading/trailing spaces for validation
        clean_value = value.strip()
        
        # Pattern for decimal string: optional sign, digits, optional decimal point, optional exponent
        pattern = r'^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$'
        if not re.match(pattern, clean_value):
            return False, "Decimal String must be a valid decimal number (may include scientific notation)"
        
        return True, ""
    
    @classmethod
    def _validate_dt(cls, value: str) -> Tuple[bool, str]:
        """Validate Date Time (DT) value."""
        if len(value) > 26:
            return False, "Date Time must be 26 characters or less"
        
        # Basic pattern for datetime (simplified)
        pattern = r'^\d{4}(\d{2}(\d{2}(\d{2}(\d{2}(\d{2}(\.\d{1,6})?)?)?)?)?)?([+-]\d{4})?$'
        if not re.match(pattern, value.strip()):
            return False, "Date Time must be in format YYYYMMDDHHMMSS.FFFFFF±ZZZZ"
        
        return True, ""
    
    @classmethod
    def _validate_fl(cls, value: str) -> Tuple[bool, str]:
        """Validate Floating Point Single (FL) value."""
        try:
            float_val = float(value)
            # Check if it's within single precision range (approximate)
            if abs(float_val) > 3.4e38:
                return False, "Value exceeds single precision floating point range"
        except ValueError:
            return False, "Floating Point Single must be a valid floating point number"
        
        return True, ""
    
    @classmethod
    def _validate_fd(cls, value: str) -> Tuple[bool, str]:
        """Validate Floating Point Double (FD) value."""
        try:
            float(value)
        except ValueError:
            return False, "Floating Point Double must be a valid floating point number"
        
        return True, ""
    
    @classmethod
    def _validate_is(cls, value: str) -> Tuple[bool, str]:
        """Validate Integer String (IS) value."""
        if len(value) > 12:
            return False, "Integer String must be 12 characters or less"
        
        clean_value = value.strip()
        pattern = r'^[+-]?\d+$'
        if not re.match(pattern, clean_value):
            return False, "Integer String must be a valid integer with optional sign"
        
        try:
            int_val = int(clean_value)
            if int_val < -2**31 or int_val > 2**31 - 1:
                return False, "Integer String value must be within 32-bit signed integer range"
        except ValueError:
            return False, "Integer String must be a valid integer"
        
        return True, ""
    
    @classmethod
    def _validate_lo(cls, value: str) -> Tuple[bool, str]:
        """Validate Long String (LO) value."""
        if len(value) > 64:
            return False, "Long String must be 64 characters or less"
        
        if '\\' in value:
            return False, "Long String cannot contain backslash character"
        
        return True, ""
    
    @classmethod
    def _validate_lt(cls, value: str) -> Tuple[bool, str]:
        """Validate Long Text (LT) value."""
        if len(value) > 10240:
            return False, "Long Text must be 10240 characters or less"
        
        return True, ""
    
    @classmethod
    def _validate_pn(cls, value: str) -> Tuple[bool, str]:
        """Validate Person Name (PN) value."""
        # Split by component group delimiter (=)
        component_groups = value.split('=')
        
        for group in component_groups:
            if len(group) > 64:
                return False, "Each Person Name component group must be 64 characters or less"
            
            if '\\' in group:
                return False, "Person Name cannot contain backslash character"
        
        return True, ""
    
    @classmethod
    def _validate_sh(cls, value: str) -> Tuple[bool, str]:
        """Validate Short String (SH) value."""
        if len(value) > 16:
            return False, "Short String must be 16 characters or less"
        
        if '\\' in value:
            return False, "Short String cannot contain backslash character"
        
        return True, ""
    
    @classmethod
    def _validate_sl(cls, value: str) -> Tuple[bool, str]:
        """Validate Signed Long (SL) value."""
        try:
            int_val = int(value)
            if int_val < -2**31 or int_val > 2**31 - 1:
                return False, "Signed Long must be within 32-bit signed integer range (-2³¹ to 2³¹-1)"
        except ValueError:
            return False, "Signed Long must be a valid integer"
        
        return True, ""
    
    @classmethod
    def _validate_ss(cls, value: str) -> Tuple[bool, str]:
        """Validate Signed Short (SS) value."""
        try:
            int_val = int(value)
            if int_val < -32768 or int_val > 32767:
                return False, "Signed Short must be within 16-bit signed integer range (-32768 to 32767)"
        except ValueError:
            return False, "Signed Short must be a valid integer"
        
        return True, ""
    
    @classmethod
    def _validate_st(cls, value: str) -> Tuple[bool, str]:
        """Validate Short Text (ST) value."""
        if len(value) > 1024:
            return False, "Short Text must be 1024 characters or less"
        
        return True, ""
    
    @classmethod
    def _validate_tm(cls, value: str) -> Tuple[bool, str]:
        """Validate Time (TM) value."""
        if len(value) > 16:
            return False, "Time must be 16 characters or less"
        
        # Pattern for time format (simplified)
        pattern = r'^\d{2}(\d{2}(\d{2}(\.\d{1,6})?)?)?$'
        clean_value = value.strip()
        if not re.match(pattern, clean_value):
            return False, "Time must be in format HHMMSS.FFFFFF"
        
        return True, ""
    
    @classmethod
    def _validate_ui(cls, value: str) -> Tuple[bool, str]:
        """Validate Unique Identifier (UI) value."""
        if len(value) > 64:
            return False, "Unique Identifier must be 64 characters or less"
        
        pattern = r'^[0-9]+(\.[0-9]+)*$'
        if not re.match(pattern, value.strip()):
            return False, "Unique Identifier must contain only digits separated by periods"
        
        return True, ""
    
    @classmethod
    def _validate_ul(cls, value: str) -> Tuple[bool, str]:
        """Validate Unsigned Long (UL) value."""
        try:
            int_val = int(value)
            if int_val < 0 or int_val > 2**32 - 1:
                return False, "Unsigned Long must be within 32-bit unsigned integer range (0 to 2³²-1)"
        except ValueError:
            return False, "Unsigned Long must be a valid non-negative integer"
        
        return True, ""
    
    @classmethod
    def _validate_us(cls, value: str) -> Tuple[bool, str]:
        """Validate Unsigned Short (US) value."""
        try:
            int_val = int(value)
            if int_val < 0 or int_val > 65535:
                return False, "Unsigned Short must be within 16-bit unsigned integer range (0 to 65535)"
        except ValueError:
            return False, "Unsigned Short must be a valid non-negative integer"
        
        return True, ""
    
    @classmethod
    def _validate_ut(cls, value: str) -> Tuple[bool, str]:
        """Validate Unlimited Text (UT) value."""
        if len(value) > 2**32 - 2:
            return False, "Unlimited Text exceeds maximum length"
        
        return True, ""
    
    @classmethod
    def _validate_unknown(cls, value: str, vr_code: str) -> Tuple[bool, str]:
        """Validate unknown VR types with basic checks."""
        if len(value) > 1024:  # Reasonable default limit
            return False, f"Value for VR {vr_code} exceeds reasonable length limit"
        
        return True, ""
