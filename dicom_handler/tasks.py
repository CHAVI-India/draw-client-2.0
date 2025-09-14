
# This file will hold the list of tasks that have to be done by the application. Note the task definitions will be done here. Actual code to be given in modular files in separate services folder
# The tasks will run in two chains - one for sending the data to API server and othe for retrieving it back

# Chain A : Sending Data to API Server (files in export_services_folder)
# Task 1: Read DICOM Data (code to be written in task1_read_dicom_from_storage.py)
# This task will read the DICOM data from the folder configured in SystemConfiguration model.
# It has to be enusured that all DICOM files in folder and subfolders have to be read. 
# Pydicom will be used to read DICOM metadata file by file. To ensure that all files are read we will ensure that file format check is not done at this stage.
# Before starting to read the file, the code will check if the file is having modality - CT / MR / PT - other modalities will be discarded:
# 1. Created or modified in the past 10 minutes - if so skip it. 
# 2. Created or modified before the date_pull_start_datetime field if available. If this date is not available or not specified or specified in the future then skip this conditon.
# 3. Check if the file data is already in the database (check SOP instance UID of the file)
# If all of the above conditions pass then the DICOM data will be read and saved in the database. 
# The models updated will be - Patient, DICOMStudy, DICOMSeries, DICOMInstance
# The series_root path will be the folder in which the file exists after excluding the file name. That is the folder path should be saved not the full file path. 
# The full file path should be saved in instance_path field for each file (each file will be a separate instance in the DICOMInstance table)
# The processing_status field of the DICOMSeries model will be set to UNPROCESSED
# After all files have been read, the total number of instance files for each series will be calculated and updated in the database.
# Pass the first DICOMInstance of the series to the next task including the instance_path as the metadata will be read from this along with the total number of instance files for the series
# Ensure logging of all operations while masking sensitive information.



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



# Task 3: Deidentify the series (code to be written in task3_deidentify_series.py)
# For the series root path, read the DICOM metadata of each file one by one. 
# Deidentification will involve replacement of all the UIDs, Patient name, Patient Date of Birth, Center information, addresses as well as provider related information. For most fields these will be replaced with and #. However UIDs will be replaced with valid DICOM UIDs. 
# The following DICOM data will be replaced with # :

        # 'PatientName',  # (0010,0010)
        # 'ReferringPhysicianName',  # (0008,0090)
        # 'InstitutionName',  # (0008,0080)
        # 'PerformingPhysicianName',  # (0008,1050)
        # 'OperatorsName',  # (0008,1070)
        # 'StationName',  # (0008,1010)
        # 'InstitutionalDepartmentName',  # (0008,1040)
        # 'PhysiciansOfRecord',  # (0008,1048)
        # 'RequestingPhysician',  # (0032,1032)
        # 'ReferringPhysicianIdentificationSequence',  # (0008,0096)
        # 'ConsultingPhysicianName',  # (0008,009C)
        # 'ResponsiblePerson',  # (0010,2297)
        # 'ReviewerName'  # (300E,0008)
        # Person's Address #
        # Institution Address #
        # Phone Number #

# The dates like Study Date, Series Date, Instance Date will be replaced with a random but valid date (all of these dates should be same so generate a random date before replacement. All instances in the series should have the same date. Similiarly if two studies are done on the same date then the same date should be used to replace. To do this check the value representation of the tag and if it  DA or DT then apply this rule. 

# UID generation rules are as follows:
# The organization prefix to be used is 1.2.826.0.1.3680043.10.1561
# Patient ID : Random UUID
# Study Instance UID : <organization_prefix>>.<random_integer(length=3)>.<random_integer(length=2)>.<random_integer(length=3)> 
# Series Instance UID : <deidentified_study_instance_uid>.<count> where count is the number of series for the given study.
# Frame of Reference UID : <deidentified_series_instance_uid>.<random_integer(length=4)>
# SOP Instance UID : <deidentified_series_instance_uid>.<random_integer(length=7)>.<random_integer(length=3)>
# For all nested referenced UID these should be replaced by the corresponding UIDs from the database if available. If not then randomly the digits should be changed while maintaining the length of the UID.
# MediaStorageSOPInstanceUID should be equal to the SOP Instance UID
# Store the IDs in the database 
# - Deidentified patient ID (patient table)
# - Deidentified patient date of birth (patient table)
# - Deidentified study instance UID (study table)
# - Deidentified Study date (study table)
# - Deidentified Series instance UID (series table)
# - Deidentified frame of reference uid (series table)
# - Deidentified series date (series table)
# - Deidentified sop instance uid (instance table)
# 
# Also remove all private tags from the DICOM file using pydicom native functionality.
# Replace the uids and write the file to a local folder (deidentified_dicom). If folder does not exist create it.
# Generate the autosegmentation template file.yml and save it to the deidentified_dicom folder
# Zip the deidentified_dicom folder and save it to the deidentified_dicom folder. Remove the  folder after all files have been zipped.
# Update the processing_status field of the DICOMSeries model to DEIDENTIFIED_SUCCESSFULLY. Store the deidentified SEries instance UID, deiedentified zip file in the DICOMFileExport model
# Pass the zip file path to the next task along with corresponding DICOMSeriesUID. 
# Ensure logging of all operations while masking sensitive information.



# Task 4: Send the deidentified series to the Draw API server (code to be written to task4_export_series_to_api.py)
# For each Zip file which has been deidentified, send it to the DRAW API Server. First we will update the status for the DICOMFileExport model to PENDING_TRANSFER_TO_DRAW_SERVER
# Prior to each transfer ensure that the API endpoint is accepting file transfer
# User bearer token authentication for the authentication
# Calculate the zip file checksum prior to sending it and update the checksum value in the database. (DICOMFileExport model). This checksum value has to be sent as the API payload along with the file. 
# Update the status for the DICOMFileExport model to SENT_TO_DRAW_SERVER
# Delete the zip file after successful transfer
# Note the transaction ID provided by the API server and update the transaction_id field in the DICOMFileExport model
# Ensure logging of all operations while masking sensitive information.
