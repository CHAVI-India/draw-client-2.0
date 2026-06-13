#!/usr/bin/env python
"""
Quick test for Varian color parsing
"""

import os
import sys
import django

# Setup Django environment
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'draw_client.settings')
django.setup()

from dicom_handler.parsers.varian_parser import VarianEclipseParser

def test_color_formats():
    """Test various Varian color formats"""
    parser = VarianEclipseParser()
    
    test_cases = [
        # Basic named colors
        ("Yellow", "255\\255\\0"),
        ("Cyan", "0\\255\\255"),
        ("Red", "255\\0\\0"),
        ("red", "255\\0\\0"),  # case insensitive
        
        # Segment prefixed colors
        ("Segment - Cyan", "0\\255\\255"),
        ("Segment-Magenta", "255\\0\\255"),
        ("Segment - Yellow", "255\\255\\0"),
        ("SEGMENT-RED", "255\\0\\0"),  # case insensitive
        
        # Translucent prefixed colors
        ("Translucent Red", "255\\0\\0"),
        ("Translucent - Blue", "0\\0\\255"),
        ("Translucent-Green", "0\\255\\0"),
        
        # Contour prefixed colors
        ("Contour Yellow", "255\\255\\0"),
        ("Contour - Magenta", "255\\0\\255"),
        ("Contour-Cyan", "0\\255\\255"),
        
        # Transparent/Opaque prefixed colors
        ("Transparent Orange", "255\\165\\0"),
        ("Opaque - Purple", "128\\0\\128"),
        
        # Special rendering colors
        ("Skin Rendering", "255\\224\\189"),
        ("Bone Rendering", "255\\245\\238"),
        ("skin", "255\\224\\189"),  # case insensitive
        
        # RGB format
        ("RGB 255 0 0", "255\\0\\0"),
        ("RGB 0 255 255", "0\\255\\255"),
        ("rgb 128 128 128", "128\\128\\128"),
        
        # Hex format
        ("#FF0000", "255\\0\\0"),
        ("FF0000", "255\\0\\0"),
        ("#00FFFF", "0\\255\\255"),
        
        # Invalid/None cases
        ("", None),
        ("InvalidColor", None),
        (None, None),
    ]
    
    print("Testing Varian Color Parsing")
    print("=" * 80)
    
    passed = 0
    failed = 0
    
    for color_input, expected in test_cases:
        result = parser._parse_color(color_input)
        status = "✓" if result == expected else "✗"
        
        if result == expected:
            passed += 1
        else:
            failed += 1
        
        input_display = f"'{color_input}'" if color_input else "None"
        result_display = f"'{result}'" if result else "None"
        expected_display = f"'{expected}'" if expected else "None"
        
        print(f"{status} {input_display:25} -> {result_display:20} (expected: {expected_display})")
    
    print("=" * 80)
    print(f"Results: {passed} passed, {failed} failed")
    
    return failed == 0

if __name__ == '__main__':
    success = test_color_formats()
    sys.exit(0 if success else 1)
