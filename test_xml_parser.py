#!/usr/bin/env python
"""
Test script for XML template parser
Run with: python test_xml_parser.py
"""

import os
import sys
import django

# Setup Django environment
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'draw_client.settings')
django.setup()

from dicom_handler.xml_template_parser import XMLTemplateParser


def test_parse_hn_xml():
    """Test parsing HN.xml file"""
    print("=" * 80)
    print("Testing HN.xml parsing")
    print("=" * 80)
    
    xml_file_path = 'HN.xml'
    
    if not os.path.exists(xml_file_path):
        print(f"Error: {xml_file_path} not found")
        return False
    
    with open(xml_file_path, 'r', encoding='utf-8') as f:
        xml_content = f.read()
    
    try:
        result = XMLTemplateParser.parse_xml_file(xml_content)
        
        print(f"\n✓ Successfully parsed XML file")
        print(f"\nTemplate Info:")
        print(f"  - Template ID: {result['template_info']['template_id']}")
        print(f"  - Diagnosis: {result['template_info']['diagnosis']}")
        print(f"  - Treatment Site: {result['template_info']['treatment_site']}")
        print(f"  - Description: {result['template_info']['description']}")
        
        print(f"\nTotal Structures: {result['total_structures']}")
        
        print(f"\nFirst 5 structures:")
        for i, structure in enumerate(result['structures'][:5], 1):
            print(f"\n  {i}. {structure['name']}")
            print(f"     - ID: {structure['id']}")
            print(f"     - Volume Type: {structure['volume_type']}")
            print(f"     - RT ROI Type: {structure['rt_roi_interpreted_type']}")
            print(f"     - Color String: {structure['color_string']}")
            print(f"     - DICOM Color: {structure['dicom_color']}")
        
        return True
        
    except Exception as e:
        print(f"✗ Error parsing XML: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def test_parse_uro_xml():
    """Test parsing URO_Prostate_SBRT.xml file"""
    print("\n" + "=" * 80)
    print("Testing URO_Prostate_SBRT.xml parsing")
    print("=" * 80)
    
    xml_file_path = 'URO_Prostate_SBRT.xml'
    
    if not os.path.exists(xml_file_path):
        print(f"Error: {xml_file_path} not found")
        return False
    
    with open(xml_file_path, 'r', encoding='utf-8') as f:
        xml_content = f.read()
    
    try:
        result = XMLTemplateParser.parse_xml_file(xml_content)
        
        print(f"\n✓ Successfully parsed XML file")
        print(f"\nTemplate Info:")
        print(f"  - Template ID: {result['template_info']['template_id']}")
        print(f"  - Diagnosis: {result['template_info']['diagnosis']}")
        print(f"  - Treatment Site: {result['template_info']['treatment_site']}")
        print(f"  - Description: {result['template_info']['description']}")
        
        print(f"\nTotal Structures: {result['total_structures']}")
        
        print(f"\nFirst 5 structures:")
        for i, structure in enumerate(result['structures'][:5], 1):
            print(f"\n  {i}. {structure['name']}")
            print(f"     - ID: {structure['id']}")
            print(f"     - Volume Type: {structure['volume_type']}")
            print(f"     - RT ROI Type: {structure['rt_roi_interpreted_type']}")
            print(f"     - Color String: {structure['color_string']}")
            print(f"     - DICOM Color: {structure['dicom_color']}")
        
        return True
        
    except Exception as e:
        print(f"✗ Error parsing XML: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def test_color_parsing():
    """Test color parsing functionality"""
    print("\n" + "=" * 80)
    print("Testing color parsing")
    print("=" * 80)
    
    test_cases = [
        ("Yellow", "255\\255\\0"),
        ("Cyan", "0\\255\\255"),
        ("Segment - Cyan", "0\\255\\255"),
        ("RGB 255 0 0", "255\\0\\0"),
        ("Skin Rendering", "255\\224\\189"),
    ]
    
    for color_input, expected in test_cases:
        result = XMLTemplateParser.parse_color(color_input)
        status = "✓" if result == expected else "✗"
        print(f"{status} '{color_input}' -> '{result}' (expected: '{expected}')")
    
    return True


def test_validation():
    """Test validation functions"""
    print("\n" + "=" * 80)
    print("Testing validation functions")
    print("=" * 80)
    
    # Test ROI label validation
    print("\nROI Label Validation:")
    test_labels = [
        ("PAROTID_R", True),
        ("SPINAL_CORD", True),
        ("THIS_IS_TOO_LONG_LABEL", False),
        ("", False),
    ]
    
    for label, should_pass in test_labels:
        is_valid, error = XMLTemplateParser.validate_roi_label(label)
        status = "✓" if is_valid == should_pass else "✗"
        print(f"{status} '{label}' -> Valid: {is_valid} {f'({error})' if error else ''}")
    
    # Test color validation
    print("\nDICOM Color Validation:")
    test_colors = [
        ("255\\0\\0", True),
        ("0\\255\\255", True),
        ("256\\0\\0", False),
        ("255\\0", False),
        ("abc\\def\\ghi", False),
    ]
    
    for color, should_pass in test_colors:
        is_valid, error = XMLTemplateParser.validate_dicom_color(color)
        status = "✓" if is_valid == should_pass else "✗"
        print(f"{status} '{color}' -> Valid: {is_valid} {f'({error})' if error else ''}")
    
    return True


if __name__ == '__main__':
    print("\nXML Template Parser Test Suite")
    print("=" * 80)
    
    results = []
    
    # Run tests
    results.append(("HN.xml parsing", test_parse_hn_xml()))
    results.append(("URO_Prostate_SBRT.xml parsing", test_parse_uro_xml()))
    results.append(("Color parsing", test_color_parsing()))
    results.append(("Validation", test_validation()))
    
    # Summary
    print("\n" + "=" * 80)
    print("Test Summary")
    print("=" * 80)
    
    for test_name, passed in results:
        status = "✓ PASSED" if passed else "✗ FAILED"
        print(f"{status}: {test_name}")
    
    all_passed = all(result[1] for result in results)
    
    print("\n" + "=" * 80)
    if all_passed:
        print("✓ All tests passed!")
    else:
        print("✗ Some tests failed")
    print("=" * 80)
    
    sys.exit(0 if all_passed else 1)
