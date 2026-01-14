# Task 2: Check if any of the rulesets match the series (code to be written in task2_match_autosegmentation_template.py)
# Get a dictionary of the all the rules and corresponding rulesets from the database at the begining of the task. This will be used for all files read.
# Note that for operator types : Equals, Not Equals, Greater than, Less than, Greater than or equal to or lesser than equal to the matched value should be cast as a numeric value 
# For the string operators (equals, not equals, string contains, string does not contain and string exact match) this should be a character. Note that equals should be a case sensitive exact match and not equal should be a case sensitive. For string matches case sensitive match and case insensitive match should be implemented. If the match operator is case insensitive, then for that all text should be transformed to lower case for the value to be evaluated and the value in the dicom metadata. May be useful to define this as a function first before proceeding. 
# After this take the DICOMInstances file path one by one and read the DICOM metadata of each file excluding the pixel data. Create a dictionary of the same.
# Check if any of the rulesets match the series based on the rules in the ruleset. 
# Matching can be done using a join operation between the dicom tags specified in the dictionary / dataset of the rules and the dicom tag. 
# After that the operator type will be checked to see each of the rules pass or not for the tag values (tag_value_to_evaluate in the rule vs the value of the tag in the DICOM data). 
# Ensure that for numeric operators, a mathematical match is done whilst for the string operator a string comparison is performed.
# Keep a tally of the rules that pass for each ruleset. 
# If the ruleset combination type is AND then all rules in the ruleset must match for the series to be matched.
# If the ruleset combination type is OR then at least one rule in the ruleset must match for the series to be matched.
# If any of the rulesets match then update the processing_status field of the DICOMSeries model to RULE_MATCHED
# If no rulesets match then update the processing_status field of the DICOMSeries model to RULE_NOT_MATCHED
# If multiple rulesets match then update the processing_status field of the DICOMSeries model to MULTIPLE_RULES_MATCHED
# Pass the related DICOMSeries root path along with the matched ruleset(s) and the autosegmentation template value (corresponding to the matched ruleset(s) - associated_autosegmentation_template) to the next task. If a series has more than one ruleset matched then these should be passed separately.
# Ensure logging of all rule matching operations while masking sensitive operations

import os
import logging
import pydicom
from django.db import transaction
from django.core.exceptions import ObjectDoesNotExist
import json
from ..models import (
    RuleSet, Rule, RuleGroup, DICOMSeries, DICOMInstance, ProcessingStatus,
    OperatorType, RuleCombinationType, AutosegmentationTemplate, DICOMTagType
)

# Configure logging with masking for sensitive information
logger = logging.getLogger(__name__)

def mask_sensitive_data(data, field_name=""):
    """
    Mask sensitive DICOM data for logging purposes
    """
    if not data:
        return "***EMPTY***"
    
    # Mask patient identifiable information
    sensitive_fields = [
        'patient_name', 'patient_id', 'patient_birth_date',
        'PatientName', 'PatientID', 'PatientBirthDate',
        'institution_name', 'InstitutionName'
    ]
    
    if any(field in field_name.lower() for field in ['name', 'id', 'birth']):
        return f"***{field_name.upper()}_MASKED***"
    
    # For UIDs, show only first and last 4 characters
    if 'uid' in field_name.lower() and len(str(data)) > 8:
        return f"{str(data)[:4]}...{str(data)[-4:]}"
    
    return str(data)

def get_all_rulegroups_rulesets_and_rules():
    """
    Get all rulegroups, rulesets and their associated rules from the database
    Returns: Dictionary with rulegroup data organized for efficient hierarchical processing
    Structure: RuleGroup -> RuleSet -> Rule
    """
    try:
        logger.info("Loading all rulegroups, rulesets and rules from database")
        
        rulegroups_data = {}
        
        # Get all rulegroups
        rulegroups = RuleGroup.objects.all()
        
        for rulegroup in rulegroups:
            # Get all rulesets for this rulegroup, ordered by rulset_order
            rulesets = RuleSet.objects.filter(rulegroup=rulegroup).select_related(
                'associated_autosegmentation_template'
            ).order_by('rulset_order')
            
            rulesets_data = []
            for ruleset in rulesets:
                # Get all rules for this ruleset, ordered by rule_order
                rules = Rule.objects.filter(ruleset=ruleset).select_related(
                    'dicom_tag_type'
                ).order_by('rule_order')
                
                rules_data = []
                for rule in rules:
                    rules_data.append({
                        'id': str(rule.id),
                        'rule_order': rule.rule_order,
                        'dicom_tag_name': rule.dicom_tag_type.tag_name,
                        'dicom_tag_id': rule.dicom_tag_type.tag_id,
                        'operator_type': rule.operator_type,
                        'tag_value_to_evaluate': rule.tag_value_to_evaluate,
                        'value_representation': rule.dicom_tag_type.value_representation,
                        'rule_combination_type': rule.rule_combination_type
                    })
                
                rulesets_data.append({
                    'id': str(ruleset.id),
                    'name': ruleset.ruleset_name,
                    'description': ruleset.ruleset_description,
                    'rulset_order': ruleset.rulset_order,
                    'ruleset_combination_type': ruleset.ruleset_combination_type,
                    'associated_template': {
                        'id': str(ruleset.associated_autosegmentation_template.id) if ruleset.associated_autosegmentation_template else None,
                        'name': ruleset.associated_autosegmentation_template.template_name if ruleset.associated_autosegmentation_template else None
                    },
                    'rules': rules_data
                })
            
            rulegroups_data[str(rulegroup.id)] = {
                'id': str(rulegroup.id),
                'name': rulegroup.rulegroup_name,
                'associated_template': {
                    'id': str(rulegroup.associated_autosegmentation_template.id) if rulegroup.associated_autosegmentation_template else None,
                    'name': rulegroup.associated_autosegmentation_template.template_name if rulegroup.associated_autosegmentation_template else None
                },
                'rulesets': rulesets_data
            }
        
        total_rulesets = sum(len(rg['rulesets']) for rg in rulegroups_data.values())
        total_rules = sum(len(rs['rules']) for rg in rulegroups_data.values() for rs in rg['rulesets'])
        logger.info(f"Loaded {len(rulegroups_data)} rulegroups with {total_rulesets} rulesets and {total_rules} total rules")
        return rulegroups_data
        
    except Exception as e:
        logger.error(f"Error loading rulegroups, rulesets and rules: {str(e)}")
        return {}

def read_dicom_metadata(file_path):
    """
    Read DICOM metadata from file, excluding pixel data
    Returns: Dictionary of DICOM tags and values
    """
    try:
        # Read DICOM file without pixel data for efficiency
        dicom_data = pydicom.dcmread(file_path, force=True, stop_before_pixels=True)
        
        # Convert DICOM dataset to dictionary for easier processing
        metadata = {}
        
        # Extract commonly used tags and all available tags
        for element in dicom_data:
            if element.VR != 'SQ':  # Skip sequence elements for now
                tag_name = element.name if hasattr(element, 'name') else str(element.tag)
                tag_value = str(element.value) if element.value is not None else ""
                metadata[tag_name] = tag_value
                
                # Also store by tag ID for direct lookup
                tag_id = f"({element.tag.group:04X},{element.tag.element:04X})"
                metadata[tag_id] = tag_value
        
        logger.debug(f"Extracted {len(metadata)} DICOM tags from {mask_sensitive_data(file_path, 'file_path')}")
        return metadata
        
    except Exception as e:
        logger.error(f"Error reading DICOM metadata from {mask_sensitive_data(file_path, 'file_path')}: {str(e)}")
        return {}

def evaluate_rule(rule_data, dicom_metadata):
    """
    Evaluate a single rule against DICOM metadata
    Returns: Boolean indicating if rule matches
    """
    try:
        # Get the DICOM tag value
        tag_name = rule_data['dicom_tag_name']
        tag_id = rule_data['dicom_tag_id']
        
        # Try to find the tag value by name first, then by ID
        dicom_value = dicom_metadata.get(tag_name)
        if dicom_value is None and tag_id:
            dicom_value = dicom_metadata.get(tag_id)
        
        if dicom_value is None:
            logger.debug(f"DICOM tag '{tag_name}' not found in metadata")
            return False
        
        # Get rule parameters
        operator = rule_data['operator_type']
        rule_value = rule_data['tag_value_to_evaluate']
        
        logger.debug(f"Evaluating rule: {tag_name} {operator} {rule_value} (DICOM value: {mask_sensitive_data(dicom_value, tag_name)})")
        
        # Evaluate based on operator type
        if operator in [OperatorType.GREATER_THAN, OperatorType.LESS_THAN,
                       OperatorType.GREATER_THAN_OR_EQUAL_TO, OperatorType.LESS_THAN_OR_EQUAL_TO]:
            # Numeric operators
            try:
                dicom_numeric = float(dicom_value)
                rule_numeric = float(rule_value)
                if operator == OperatorType.GREATER_THAN:
                    return dicom_numeric > rule_numeric
                elif operator == OperatorType.LESS_THAN:
                    return dicom_numeric < rule_numeric
                elif operator == OperatorType.GREATER_THAN_OR_EQUAL_TO:
                    return dicom_numeric >= rule_numeric
                elif operator == OperatorType.LESS_THAN_OR_EQUAL_TO:
                    return dicom_numeric <= rule_numeric
                    
            except ValueError:
                logger.warning(f"Cannot convert values to numeric for comparison: DICOM='{dicom_value}', Rule='{rule_value}'")
                return False
        
        elif operator in [OperatorType.EQUALS, OperatorType.NOT_EQUALS]:
            # Sring match equal
            if operator == OperatorType.EQUALS:
                return str(dicom_value) == str(rule_value)
            else: # String match not equals
                return str(dicom_value) != str(rule_value)
        elif operator in [OperatorType.CASE_SENSITIVE_STRING_EXACT_MATCH, OperatorType.CASE_INSENSITIVE_STRING_EXACT_MATCH]:
            # String exact match operators
            if operator == OperatorType.CASE_SENSITIVE_STRING_EXACT_MATCH:
                return str(dicom_value) == str(rule_value)
            else:  # Case insensitive
                return str(dicom_value).lower() == str(rule_value).lower()
        
        elif operator in [OperatorType.CASE_SENSITIVE_STRING_CONTAINS, OperatorType.CASE_INSENSITIVE_STRING_CONTAINS]:
            # String contains operators
            if operator == OperatorType.CASE_SENSITIVE_STRING_CONTAINS:
                return str(rule_value) in str(dicom_value)
            else:  # Case insensitive
                return str(rule_value).lower() in str(dicom_value).lower()
        
        elif operator in [OperatorType.CASE_SENSITIVE_STRING_DOES_NOT_CONTAIN, OperatorType.CASE_INSENSITIVE_STRING_DOES_NOT_CONTAIN]:
            # String does not contain operators
            if operator == OperatorType.CASE_SENSITIVE_STRING_DOES_NOT_CONTAIN:
                return str(rule_value) not in str(dicom_value)
            else:  # Case insensitive
                return str(rule_value).lower() not in str(dicom_value).lower()
        
        else:
            logger.error(f"Unknown operator type: {operator}")
            return False
            
    except Exception as e:
        logger.error(f"Error evaluating rule: {str(e)}")
        return False

def evaluate_ruleset(ruleset_data, dicom_metadata):
    """
    Evaluate a complete ruleset against DICOM metadata with rule combination logic
    Rules are evaluated in order based on rule_order field
    Rules are combined based on each rule's rule_combination_type
    Returns: Boolean indicating if ruleset matches
    """
    try:
        rules = ruleset_data['rules']
        
        if not rules:
            logger.debug(f"Ruleset '{ruleset_data['name']}' has no rules")
            return False
        
        # Rules are already ordered by rule_order from the database query
        # Evaluate rules in order and combine based on each rule's combination type
        
        # Start with the first rule's result
        current_result = evaluate_rule(rules[0], dicom_metadata)
        logger.debug(f"Rule 1 (order {rules[0]['rule_order']}) '{rules[0]['dicom_tag_name']}': {current_result}")
        
        # Process remaining rules in order
        for i in range(1, len(rules)):
            rule = rules[i]
            rule_result = evaluate_rule(rule, dicom_metadata)
            logger.debug(f"Rule {i+1} (order {rule['rule_order']}) '{rule['dicom_tag_name']}': {rule_result}")
            
            # The previous rule's combination type determines how to combine with current result
            prev_rule_combination = rules[i-1]['rule_combination_type']
            
            if prev_rule_combination == RuleCombinationType.AND:
                # AND: Both must be true
                current_result = current_result and rule_result
            elif prev_rule_combination == RuleCombinationType.OR:
                # OR: At least one must be true
                current_result = current_result or rule_result
            else:
                logger.error(f"Unknown rule combination type: {prev_rule_combination}")
                return False
            
            logger.debug(f"Combined result after rule {i+1}: {current_result}")
        
        logger.info(f"Ruleset '{ruleset_data['name']}': Final result = {current_result}")
        return current_result
        
    except Exception as e:
        logger.error(f"Error evaluating ruleset '{ruleset_data.get('name', 'unknown')}': {str(e)}")
        return False

def evaluate_rulegroup(rulegroup_data, dicom_metadata):
    """
    Evaluate a complete rulegroup against DICOM metadata
    Rulesets are evaluated in order based on rulset_order field
    Rulesets are combined based on each ruleset's ruleset_combination_type
    Returns: Tuple of (Boolean indicating if rulegroup matches, List of matched rulesets)
    """
    try:
        rulesets = rulegroup_data['rulesets']
        
        if not rulesets:
            logger.debug(f"Rulegroup '{rulegroup_data['id']}' has no rulesets")
            return False, []
        
        # Rulesets are already ordered by rulset_order from the database query
        matched_rulesets = []
        
        # Start with the first ruleset's result
        first_ruleset_match = evaluate_ruleset(rulesets[0], dicom_metadata)
        if first_ruleset_match:
            matched_rulesets.append(rulesets[0])
        
        current_result = first_ruleset_match
        logger.debug(f"Ruleset 1 (order {rulesets[0]['rulset_order']}) '{rulesets[0]['name']}': {current_result}")
        
        # Process remaining rulesets in order
        for i in range(1, len(rulesets)):
            ruleset = rulesets[i]
            ruleset_result = evaluate_ruleset(ruleset, dicom_metadata)
            if ruleset_result:
                matched_rulesets.append(ruleset)
            
            logger.debug(f"Ruleset {i+1} (order {ruleset['rulset_order']}) '{ruleset['name']}': {ruleset_result}")
            
            # The previous ruleset's combination type determines how to combine with current result
            prev_ruleset_combination = rulesets[i-1]['ruleset_combination_type']
            
            if prev_ruleset_combination == RuleCombinationType.AND:
                # AND: Both must be true
                current_result = current_result and ruleset_result
            elif prev_ruleset_combination == RuleCombinationType.OR:
                # OR: At least one must be true
                current_result = current_result or ruleset_result
            else:
                logger.error(f"Unknown ruleset combination type: {prev_ruleset_combination}")
                return False, []
            
            logger.debug(f"Combined result after ruleset {i+1}: {current_result}")
        
        logger.info(f"Rulegroup '{rulegroup_data['id']}': Final result = {current_result}, Matched {len(matched_rulesets)} rulesets")
        return current_result, matched_rulesets
        
    except Exception as e:
        logger.error(f"Error evaluating rulegroup '{rulegroup_data.get('id', 'unknown')}': {str(e)}")
        return False, []

def match_autosegmentation_template(task1_output):
    """
    Main function to match autosegmentation templates against DICOM series
    Input: Output from task1 (series data)
    Returns: Dictionary containing matched series information for next task
    """
    logger.info("Starting autosegmentation template matching task")
    
    try:
        # Validate input
        if not task1_output or task1_output.get('status') != 'success':
            logger.error("Invalid input from task1 or task1 failed")
            return {"status": "error", "message": "Invalid input from previous task"}
        
        series_data = task1_output.get('series_data', [])
        if not series_data:
            logger.info("No series data to process")
            return {"status": "success", "processed_series": 0, "matched_series": []}
        
        logger.info(f"Processing {len(series_data)} series for rule matching")
        
        # Load all rulegroups, rulesets and rules
        rulegroups_data = get_all_rulegroups_rulesets_and_rules()
        if not rulegroups_data:
            logger.warning("No rulegroups found in database")
            # Update all series to RULE_NOT_MATCHED
            for series_info in series_data:
                try:
                    series = DICOMSeries.objects.get(series_instance_uid=series_info['series_instance_uid'])
                    series.series_processsing_status = ProcessingStatus.RULE_NOT_MATCHED
                    series.save()
                except DICOMSeries.DoesNotExist:
                    logger.error(f"Series not found: {mask_sensitive_data(series_info['series_instance_uid'], 'series_uid')}")
            
            return {"status": "success", "processed_series": len(series_data), "matched_series": []}
        
        matched_series_results = []
        processed_count = 0
        
        # Process each series
        for series_info in series_data:
            try:
                series_uid = series_info['series_instance_uid']
                first_instance_path = series_info['first_instance_path']
                series_root_path = series_info['series_root_path']
                
                logger.info(f"Processing series: {mask_sensitive_data(series_uid, 'series_uid')}")
                
                # Read DICOM metadata from first instance
                if not os.path.exists(first_instance_path):
                    logger.error(f"First instance file not found: {mask_sensitive_data(first_instance_path, 'file_path')}")
                    continue
                
                dicom_metadata = read_dicom_metadata(first_instance_path)
                if not dicom_metadata:
                    logger.error(f"Could not read DICOM metadata for series: {mask_sensitive_data(series_uid, 'series_uid')}")
                    continue
                
                # Test each rulegroup against this series
                # Collect all matched rulegroups with their rulesets
                matched_rulegroups = []
                
                for rulegroup_id, rulegroup_data in rulegroups_data.items():
                    rulegroup_match, matched_rulesets_in_group = evaluate_rulegroup(rulegroup_data, dicom_metadata)
                    
                    if rulegroup_match and matched_rulesets_in_group:
                        logger.info(f"Series {mask_sensitive_data(series_uid, 'series_uid')} matched rulegroup: {rulegroup_data['name']}")
                        # Store rulegroup info with its matched rulesets
                        matched_rulegroups.append({
                            'rulegroup_id': rulegroup_data['id'],
                            'rulegroup_name': rulegroup_data['name'],
                            'matched_rulesets': matched_rulesets_in_group
                        })
                
                # Flatten to get all matched rulesets for database updates
                matched_rulesets = []
                for rg in matched_rulegroups:
                    matched_rulesets.extend(rg['matched_rulesets'])
                
                # Update series status and relationships based on matches
                with transaction.atomic():
                    try:
                        series = DICOMSeries.objects.get(series_instance_uid=series_uid)
                        
                        if len(matched_rulegroups) == 0:
                            # No matches
                            series.series_processsing_status = ProcessingStatus.RULE_NOT_MATCHED
                            series.matched_rule_sets.clear()
                            series.matched_templates.clear()
                            logger.info(f"Series {mask_sensitive_data(series_uid, 'series_uid')}: No rulegroups matched")
                            
                        elif len(matched_rulegroups) == 1:
                            # Single rulegroup match
                            series.series_processsing_status = ProcessingStatus.RULE_MATCHED
                            
                            # Clear existing relationships
                            series.matched_rule_sets.clear()
                            series.matched_templates.clear()
                            
                            # Add all rulesets from the matched rulegroup
                            rulegroup = matched_rulegroups[0]
                            rulegroup_data = rulegroups_data[rulegroup['rulegroup_id']]
                            
                            for matched_ruleset in rulegroup['matched_rulesets']:
                                ruleset_obj = RuleSet.objects.get(id=matched_ruleset['id'])
                                series.matched_rule_sets.add(ruleset_obj)
                            
                            # Add associated template from RuleGroup (not RuleSet)
                            if rulegroup_data['associated_template']['id']:
                                template_obj = AutosegmentationTemplate.objects.get(id=rulegroup_data['associated_template']['id'])
                                series.matched_templates.add(template_obj)
                                logger.info(f"Added template: {rulegroup_data['associated_template']['name']}")
                            
                            logger.info(f"Series {mask_sensitive_data(series_uid, 'series_uid')}: Single rulegroup matched: {rulegroup['rulegroup_name']}")
                            
                        else:
                            # Multiple rulegroups matched
                            series.series_processsing_status = ProcessingStatus.MULTIPLE_RULES_MATCHED
                            
                            # Clear existing relationships
                            series.matched_rule_sets.clear()
                            series.matched_templates.clear()
                            
                            # Add all rulesets from all matched rulegroups
                            for rulegroup in matched_rulegroups:
                                rulegroup_data = rulegroups_data[rulegroup['rulegroup_id']]
                                
                                for matched_ruleset in rulegroup['matched_rulesets']:
                                    ruleset_obj = RuleSet.objects.get(id=matched_ruleset['id'])
                                    series.matched_rule_sets.add(ruleset_obj)
                                
                                # Add associated template from RuleGroup (not RuleSet)
                                if rulegroup_data['associated_template']['id']:
                                    template_obj = AutosegmentationTemplate.objects.get(id=rulegroup_data['associated_template']['id'])
                                    series.matched_templates.add(template_obj)
                                    logger.info(f"Added template: {rulegroup_data['associated_template']['name']}")
                            
                            logger.info(f"Series {mask_sensitive_data(series_uid, 'series_uid')}: Multiple rulegroups matched ({len(matched_rulegroups)})")
                        
                        series.save()
                        
                        # Prepare data for next task if there are matches
                        # Pass only RuleGroup info since template comes from RuleGroup
                        if matched_rulegroups:
                            for rulegroup in matched_rulegroups:
                                # Get template from the RuleGroup (not from RuleSet)
                                rulegroup_data = rulegroups_data[rulegroup['rulegroup_id']]
                                matched_series_results.append({
                                    'series_instance_uid': series_uid,
                                    'series_root_path': series_root_path,
                                    'matched_rulegroup_id': rulegroup['rulegroup_id'],
                                    'matched_rulegroup_name': rulegroup['rulegroup_name'],
                                    'associated_template_id': rulegroup_data['associated_template']['id'],
                                    'associated_template_name': rulegroup_data['associated_template']['name'],
                                    'instance_count': series_info.get('instance_count', 0)
                                })
                        
                        processed_count += 1
                        
                    except DICOMSeries.DoesNotExist:
                        logger.error(f"Series not found in database: {mask_sensitive_data(series_uid, 'series_uid')}")
                        continue
                        
            except Exception as e:
                logger.error(f"Error processing series {mask_sensitive_data(series_info.get('series_instance_uid', 'unknown'), 'series_uid')}: {str(e)}")
                continue
        
        logger.info(f"Template matching completed. Processed: {processed_count}, Matched: {len(matched_series_results)}")
        
        return {
            "status": "success",
            "processed_series": processed_count,
            "total_matches": len(matched_series_results),
            "matched_series": matched_series_results
        }
        
    except Exception as e:
        logger.error(f"Critical error in template matching task: {str(e)}")
        return {"status": "error", "message": str(e)}