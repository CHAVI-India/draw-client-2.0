"""
Comprehensive tests for RuleSet and RuleGroup combination logic
Tests the hierarchical structure: RuleGroup → RuleSet → Rule
"""
import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'draw_client.settings')
django.setup()

from dicom_handler.models import RuleCombinationType, OperatorType
from dicom_handler.export_services.task2_match_autosegmentation_template import (
    evaluate_rule, evaluate_ruleset, evaluate_rulegroup
)


def test_rule_combination_and():
    """Test multiple rules combined with AND - all must match"""
    print("\n" + "="*70)
    print("TEST 1: Rule Combination with AND")
    print("="*70)
    
    metadata = {
        "Modality": "CT",
        "Body Part Examined": "HEAD",
        "Slice Thickness": "3.0"
    }
    
    # Ruleset with 3 rules, all combined with AND
    ruleset = {
        'name': 'Test AND Ruleset',
        'ruleset_combination_type': RuleCombinationType.AND,
        'rules': [
            {
                'rule_order': 1,
                'dicom_tag_name': 'Modality',
                'dicom_tag_id': '(0008,0060)',
                'operator_type': OperatorType.EQUALS,
                'tag_value_to_evaluate': 'CT',
                'rule_combination_type': RuleCombinationType.AND
            },
            {
                'rule_order': 2,
                'dicom_tag_name': 'Body Part Examined',
                'dicom_tag_id': '(0018,0015)',
                'operator_type': OperatorType.EQUALS,
                'tag_value_to_evaluate': 'HEAD',
                'rule_combination_type': RuleCombinationType.AND
            },
            {
                'rule_order': 3,
                'dicom_tag_name': 'Slice Thickness',
                'dicom_tag_id': '(0018,0050)',
                'operator_type': OperatorType.LESS_THAN,
                'tag_value_to_evaluate': '5.0',
                'rule_combination_type': RuleCombinationType.AND
            }
        ]
    }
    
    print("Scenario 1: All 3 rules match")
    print(f"  Metadata: Modality=CT, Body Part=HEAD, Slice Thickness=3.0")
    result = evaluate_ruleset(ruleset, metadata)
    print(f"  Expected: True (all rules match)")
    print(f"  Result: {result}")
    assert result == True, "❌ FAILED: All rules should match with AND"
    print("  ✅ PASSED")
    
    # Test with one rule failing
    metadata_fail = metadata.copy()
    metadata_fail["Modality"] = "MR"
    
    print("\nScenario 2: First rule fails (Modality=MR instead of CT)")
    print(f"  Metadata: Modality=MR, Body Part=HEAD, Slice Thickness=3.0")
    result = evaluate_ruleset(ruleset, metadata_fail)
    print(f"  Expected: False (one rule fails, AND requires all)")
    print(f"  Result: {result}")
    assert result == False, "❌ FAILED: Should fail when one rule doesn't match with AND"
    print("  ✅ PASSED")


def test_rule_combination_or():
    """Test multiple rules combined with OR - at least one must match"""
    print("\n" + "="*70)
    print("TEST 2: Rule Combination with OR")
    print("="*70)
    
    metadata = {
        "Modality": "MR",  # Doesn't match first rule
        "Body Part Examined": "HEAD",  # Matches second rule
        "Slice Thickness": "10.0"  # Doesn't match third rule
    }
    
    # Ruleset with 3 rules, all combined with OR
    ruleset = {
        'name': 'Test OR Ruleset',
        'ruleset_combination_type': RuleCombinationType.OR,
        'rules': [
            {
                'rule_order': 1,
                'dicom_tag_name': 'Modality',
                'dicom_tag_id': '(0008,0060)',
                'operator_type': OperatorType.EQUALS,
                'tag_value_to_evaluate': 'CT',
                'rule_combination_type': RuleCombinationType.OR
            },
            {
                'rule_order': 2,
                'dicom_tag_name': 'Body Part Examined',
                'dicom_tag_id': '(0018,0015)',
                'operator_type': OperatorType.EQUALS,
                'tag_value_to_evaluate': 'HEAD',
                'rule_combination_type': RuleCombinationType.OR
            },
            {
                'rule_order': 3,
                'dicom_tag_name': 'Slice Thickness',
                'dicom_tag_id': '(0018,0050)',
                'operator_type': OperatorType.LESS_THAN,
                'tag_value_to_evaluate': '5.0',
                'rule_combination_type': RuleCombinationType.OR
            }
        ]
    }
    
    print("Scenario 1: Only middle rule matches (Body Part=HEAD)")
    print(f"  Metadata: Modality=MR, Body Part=HEAD, Slice Thickness=10.0")
    result = evaluate_ruleset(ruleset, metadata)
    print(f"  Expected: True (at least one rule matches)")
    print(f"  Result: {result}")
    assert result == True, "❌ FAILED: Should match when at least one rule matches with OR"
    print("  ✅ PASSED")
    
    # Test with no rules matching
    metadata_fail = {
        "Modality": "MR",
        "Body Part Examined": "CHEST",
        "Slice Thickness": "10.0"
    }
    
    print("\nScenario 2: No rules match")
    print(f"  Metadata: Modality=MR, Body Part=CHEST, Slice Thickness=10.0")
    result = evaluate_ruleset(ruleset, metadata_fail)
    print(f"  Expected: False (no rules match)")
    print(f"  Result: {result}")
    assert result == False, "❌ FAILED: Should fail when no rules match with OR"
    print("  ✅ PASSED")


def test_ruleset_combination_or():
    """Test multiple rulesets combined with OR - at least one must match"""
    print("\n" + "="*70)
    print("TEST 3: RuleSet Combination with OR")
    print("="*70)
    
    # Metadata that matches Breast ruleset but not Head Neck
    metadata = {
        "Modality": "CT",
        "Protocol Name": "Breast Screening",
        "Study Description": "CT CHEST"
    }
    
    rulegroup = {
        'id': 'test-rulegroup',
        'name': 'Breast OR Head Neck',
        'rulesets': [
            {
                'rulset_order': 1,
                'name': 'Breast Ruleset',
                'ruleset_combination_type': RuleCombinationType.OR,  # How this combines with next
                'rules': [
                    {
                        'rule_order': 1,
                        'dicom_tag_name': 'Modality',
                        'dicom_tag_id': '(0008,0060)',
                        'operator_type': OperatorType.EQUALS,
                        'tag_value_to_evaluate': 'CT',
                        'rule_combination_type': RuleCombinationType.AND
                    },
                    {
                        'rule_order': 2,
                        'dicom_tag_name': 'Protocol Name',
                        'dicom_tag_id': '(0018,1030)',
                        'operator_type': OperatorType.CASE_INSENSITIVE_STRING_CONTAINS,
                        'tag_value_to_evaluate': 'Breast',
                        'rule_combination_type': RuleCombinationType.AND
                    }
                ]
            },
            {
                'rulset_order': 2,
                'name': 'Head Neck Ruleset',
                'ruleset_combination_type': RuleCombinationType.OR,
                'rules': [
                    {
                        'rule_order': 1,
                        'dicom_tag_name': 'Modality',
                        'dicom_tag_id': '(0008,0060)',
                        'operator_type': OperatorType.EQUALS,
                        'tag_value_to_evaluate': 'CT',
                        'rule_combination_type': RuleCombinationType.AND
                    },
                    {
                        'rule_order': 2,
                        'dicom_tag_name': 'Study Description',
                        'dicom_tag_id': '(0008,1030)',
                        'operator_type': OperatorType.CASE_INSENSITIVE_STRING_CONTAINS,
                        'tag_value_to_evaluate': 'HEAD',
                        'rule_combination_type': RuleCombinationType.AND
                    }
                ]
            }
        ]
    }
    
    print("Scenario 1: First ruleset matches (Breast), second doesn't (no HEAD)")
    print(f"  Metadata: Modality=CT, Protocol=Breast Screening, Study=CT CHEST")
    result, matched = evaluate_rulegroup(rulegroup, metadata)
    print(f"  Expected: True (first ruleset matches, OR combination)")
    print(f"  Result: {result}, Matched rulesets: {len(matched)}")
    assert result == True, "❌ FAILED: Should match when first ruleset matches with OR"
    assert len(matched) == 1, "❌ FAILED: Should have 1 matched ruleset"
    print("  ✅ PASSED")
    
    # Test with second ruleset matching
    metadata2 = {
        "Modality": "CT",
        "Protocol Name": "Standard",
        "Study Description": "CT HEAD"
    }
    
    print("\nScenario 2: Second ruleset matches (HEAD), first doesn't (no Breast)")
    print(f"  Metadata: Modality=CT, Protocol=Standard, Study=CT HEAD")
    result, matched = evaluate_rulegroup(rulegroup, metadata2)
    print(f"  Expected: True (second ruleset matches, OR combination)")
    print(f"  Result: {result}, Matched rulesets: {len(matched)}")
    assert result == True, "❌ FAILED: Should match when second ruleset matches with OR"
    assert len(matched) == 1, "❌ FAILED: Should have 1 matched ruleset"
    print("  ✅ PASSED")
    
    # Test with both matching
    metadata3 = {
        "Modality": "CT",
        "Protocol Name": "Breast",
        "Study Description": "HEAD NECK"
    }
    
    print("\nScenario 3: Both rulesets match")
    print(f"  Metadata: Modality=CT, Protocol=Breast, Study=HEAD NECK")
    result, matched = evaluate_rulegroup(rulegroup, metadata3)
    print(f"  Expected: True (both match, OR combination)")
    print(f"  Result: {result}, Matched rulesets: {len(matched)}")
    assert result == True, "❌ FAILED: Should match when both rulesets match with OR"
    assert len(matched) == 2, "❌ FAILED: Should have 2 matched rulesets"
    print("  ✅ PASSED")


def test_ruleset_combination_and():
    """Test multiple rulesets combined with AND - all must match"""
    print("\n" + "="*70)
    print("TEST 4: RuleSet Combination with AND")
    print("="*70)
    
    # Metadata that matches both rulesets
    metadata = {
        "Modality": "CT",
        "Body Part Examined": "CHEST",
        "Slice Thickness": "3.0"
    }
    
    rulegroup = {
        'id': 'test-rulegroup-and',
        'name': 'CT AND Thin Slices',
        'rulesets': [
            {
                'rulset_order': 1,
                'name': 'CT Modality Check',
                'ruleset_combination_type': RuleCombinationType.AND,  # Requires next ruleset to also match
                'rules': [
                    {
                        'rule_order': 1,
                        'dicom_tag_name': 'Modality',
                        'dicom_tag_id': '(0008,0060)',
                        'operator_type': OperatorType.EQUALS,
                        'tag_value_to_evaluate': 'CT',
                        'rule_combination_type': RuleCombinationType.AND
                    }
                ]
            },
            {
                'rulset_order': 2,
                'name': 'Thin Slice Check',
                'ruleset_combination_type': RuleCombinationType.AND,
                'rules': [
                    {
                        'rule_order': 1,
                        'dicom_tag_name': 'Slice Thickness',
                        'dicom_tag_id': '(0018,0050)',
                        'operator_type': OperatorType.LESS_THAN,
                        'tag_value_to_evaluate': '5.0',
                        'rule_combination_type': RuleCombinationType.AND
                    }
                ]
            }
        ]
    }
    
    print("Scenario 1: Both rulesets match")
    print(f"  Metadata: Modality=CT, Slice Thickness=3.0")
    result, matched = evaluate_rulegroup(rulegroup, metadata)
    print(f"  Expected: True (both rulesets match, AND combination)")
    print(f"  Result: {result}, Matched rulesets: {len(matched)}")
    assert result == True, "❌ FAILED: Should match when both rulesets match with AND"
    assert len(matched) == 2, "❌ FAILED: Should have 2 matched rulesets"
    print("  ✅ PASSED")
    
    # Test with second ruleset failing
    metadata_fail = {
        "Modality": "CT",
        "Body Part Examined": "CHEST",
        "Slice Thickness": "10.0"  # Too thick
    }
    
    print("\nScenario 2: First ruleset matches, second fails (thick slices)")
    print(f"  Metadata: Modality=CT, Slice Thickness=10.0")
    result, matched = evaluate_rulegroup(rulegroup, metadata_fail)
    print(f"  Expected: False (second ruleset fails, AND requires both)")
    print(f"  Result: {result}, Matched rulesets: {len(matched)}")
    assert result == False, "❌ FAILED: Should fail when one ruleset doesn't match with AND"
    print("  ✅ PASSED")


def test_mixed_combinations():
    """Test complex scenario with mixed AND/OR combinations"""
    print("\n" + "="*70)
    print("TEST 5: Mixed AND/OR Combinations")
    print("="*70)
    
    metadata = {
        "Modality": "CT",
        "Body Part Examined": "CHEST",
        "Protocol Name": "Breast",
        "Slice Thickness": "3.0"
    }
    
    # Complex ruleset: (Rule1 AND Rule2) OR Rule3
    ruleset = {
        'name': 'Complex Mixed Rules',
        'ruleset_combination_type': RuleCombinationType.AND,
        'rules': [
            {
                'rule_order': 1,
                'dicom_tag_name': 'Modality',
                'dicom_tag_id': '(0008,0060)',
                'operator_type': OperatorType.EQUALS,
                'tag_value_to_evaluate': 'CT',
                'rule_combination_type': RuleCombinationType.AND  # Must match with next
            },
            {
                'rule_order': 2,
                'dicom_tag_name': 'Body Part Examined',
                'dicom_tag_id': '(0018,0015)',
                'operator_type': OperatorType.EQUALS,
                'tag_value_to_evaluate': 'CHEST',
                'rule_combination_type': RuleCombinationType.OR  # OR with next
            },
            {
                'rule_order': 3,
                'dicom_tag_name': 'Slice Thickness',
                'dicom_tag_id': '(0018,0050)',
                'operator_type': OperatorType.LESS_THAN,
                'tag_value_to_evaluate': '5.0',
                'rule_combination_type': RuleCombinationType.AND
            }
        ]
    }
    
    print("Scenario: (Modality=CT AND Body Part=CHEST) OR Slice<5.0")
    print(f"  Metadata: All conditions true")
    result = evaluate_ruleset(ruleset, metadata)
    print(f"  Expected: True")
    print(f"  Result: {result}")
    assert result == True, "❌ FAILED: Mixed combination should work"
    print("  ✅ PASSED")


def main():
    """Run all comprehensive combination tests"""
    print("\n" + "="*70)
    print("COMPREHENSIVE RULESET AND RULEGROUP COMBINATION TESTS")
    print("="*70)
    print("\nThese tests verify:")
    print("  1. Multiple rules combined with AND (all must match)")
    print("  2. Multiple rules combined with OR (at least one must match)")
    print("  3. Multiple rulesets combined with OR (at least one must match)")
    print("  4. Multiple rulesets combined with AND (all must match)")
    print("  5. Mixed AND/OR combinations")
    
    try:
        test_rule_combination_and()
        test_rule_combination_or()
        test_ruleset_combination_or()
        test_ruleset_combination_and()
        test_mixed_combinations()
        
        print("\n" + "="*70)
        print("✅ ALL COMPREHENSIVE TESTS PASSED!")
        print("="*70)
        print("\nThe hierarchical rule matching logic is working correctly:")
        print("  ✓ Rules combine properly with AND/OR")
        print("  ✓ RuleSets combine properly with AND/OR")
        print("  ✓ RuleGroups evaluate correctly")
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
