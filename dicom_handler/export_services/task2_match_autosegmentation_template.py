# Task 2: Check if any of the rulesets match the series (code to be written in task2_match_autosegmentation_template.py)
# Get a dictionary of the all the rules and corresponding rulesets from the database at the begining of the task. This will be used for all files read.
# Note that for operator types : Equals, Not Equals, Greater than, Less than, Greater than or equal to or lesser than equal to the matched value should be cast as a numeric value 
# For the string operators (string contains, string does not contain and string exact match) this should be a character.
# For this the take the DICOMInstances file path one by one and read the DICOM metadata of each file excluding the pixel data. Create a dictionary of the same.
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
# Pass the related DICOMSeries root path along with the matched ruleset and the autosegmentation template value (corresponding to the matched ruleset - associated_autosegmentation_template) to the next task. If a series has more than one ruleset matched then these should be passed separately.
# Ensure logging of all rule matching operations while masking sensitive operations