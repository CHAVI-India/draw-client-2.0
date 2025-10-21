#!/usr/bin/env python
"""
Test script for autosegmentation templates migration
This script tests the loading of seed data from the fixture file.
"""

import os
import sys
import django
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'draw_client.settings')
django.setup()

# Now import Django models
from dicom_handler.models import AutosegmentationTemplate, AutosegmentationModel, AutosegmentationStructure
import json


def check_fixture_file():
    """
    Check if the fixture file exists and is valid
    """
    print("\n" + "="*70)
    print("CHECKING FIXTURE FILE")
    print("="*70)
    
    fixture_path = project_root / 'seed_data' / 'autosegmentation_templates.json'
    
    if not fixture_path.exists():
        print(f"✗ Fixture file not found at {fixture_path}")
        return False
    
    print(f"✓ Fixture file found at {fixture_path}")
    
    try:
        with open(fixture_path, 'r', encoding='utf-8') as f:
            fixture_data = json.load(f)
        
        templates_count = len([item for item in fixture_data if item['model'] == 'dicom_handler.autosegmentationtemplate'])
        models_count = len([item for item in fixture_data if item['model'] == 'dicom_handler.autosegmentationmodel'])
        structures_count = len([item for item in fixture_data if item['model'] == 'dicom_handler.autosegmentationstructure'])
        
        print(f"✓ Fixture file is valid JSON")
        print(f"  - Templates: {templates_count}")
        print(f"  - Models: {models_count}")
        print(f"  - Structures: {structures_count}")
        
        return True
    except Exception as e:
        print(f"✗ Error reading fixture file: {e}")
        return False


def check_current_database_state():
    """
    Check the current state of templates in the database
    """
    print("\n" + "="*70)
    print("CHECKING CURRENT DATABASE STATE")
    print("="*70)
    
    templates_count = AutosegmentationTemplate.objects.count()
    models_count = AutosegmentationModel.objects.count()
    structures_count = AutosegmentationStructure.objects.count()
    
    print(f"Current database contains:")
    print(f"  - Templates: {templates_count}")
    print(f"  - Models: {models_count}")
    print(f"  - Structures: {structures_count}")
    
    if templates_count > 0:
        print("\nExisting templates:")
        for template in AutosegmentationTemplate.objects.all():
            model_count = AutosegmentationModel.objects.filter(autosegmentation_template_name=template).count()
            print(f"  - {template.template_name} ({model_count} models)")
    
    return templates_count, models_count, structures_count


def test_template_relationships():
    """
    Test that template relationships are properly maintained
    """
    print("\n" + "="*70)
    print("TESTING TEMPLATE RELATIONSHIPS")
    print("="*70)
    
    templates = AutosegmentationTemplate.objects.all()
    
    if not templates.exists():
        print("✗ No templates found in database")
        return False
    
    all_valid = True
    
    for template in templates:
        models = AutosegmentationModel.objects.filter(autosegmentation_template_name=template)
        
        if not models.exists():
            print(f"✗ Template '{template.template_name}' has no associated models")
            all_valid = False
            continue
        
        print(f"\n✓ Template: {template.template_name}")
        print(f"  Description: {template.template_description}")
        print(f"  Models: {models.count()}")
        
        total_structures = 0
        for model in models:
            structures = AutosegmentationStructure.objects.filter(autosegmentation_model=model)
            structure_count = structures.count()
            total_structures += structure_count
            print(f"    - {model.name} (model_id: {model.model_id}): {structure_count} structures")
        
        print(f"  Total structures: {total_structures}")
    
    if all_valid:
        print("\n✓ All templates have valid relationships")
    
    return all_valid


def test_specific_template_data():
    """
    Test specific template data to ensure it was loaded correctly
    """
    print("\n" + "="*70)
    print("TESTING SPECIFIC TEMPLATE DATA")
    print("="*70)
    
    # Test for a specific template (e.g., Head Neck Template)
    try:
        template = AutosegmentationTemplate.objects.get(template_name="Example Head Neck Template")
        print(f"✓ Found 'Example Head Neck Template'")
        print(f"  ID: {template.id}")
        print(f"  Description: {template.template_description}")
        
        models = AutosegmentationModel.objects.filter(autosegmentation_template_name=template)
        print(f"  Associated models: {models.count()}")
        
        for model in models:
            structures = AutosegmentationStructure.objects.filter(autosegmentation_model=model)
            print(f"    - {model.name}: {structures.count()} structures")
            # Show first 5 structures as sample
            for structure in structures[:5]:
                print(f"      • {structure.name} (map_id: {structure.map_id})")
            if structures.count() > 5:
                print(f"      ... and {structures.count() - 5} more")
        
        return True
    except AutosegmentationTemplate.DoesNotExist:
        print("✗ 'Example Head Neck Template' not found")
        return False
    except Exception as e:
        print(f"✗ Error testing specific template: {e}")
        return False


def run_all_tests():
    """
    Run all tests
    """
    print("\n" + "="*70)
    print("AUTOSEGMENTATION TEMPLATES MIGRATION TEST")
    print("="*70)
    
    results = []
    
    # Test 1: Check fixture file
    results.append(("Fixture file check", check_fixture_file()))
    
    # Test 2: Check database state
    check_current_database_state()
    
    # Test 3: Test relationships
    results.append(("Template relationships", test_template_relationships()))
    
    # Test 4: Test specific data
    results.append(("Specific template data", test_specific_template_data()))
    
    # Summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {test_name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed!")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    exit_code = run_all_tests()
    sys.exit(exit_code)
