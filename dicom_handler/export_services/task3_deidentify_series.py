# Task 3: Deidentify the series (code to be written in task3_deidentify_series.py)
# For the series root path, read the DICOM metadata of each file one by one. 
# Deidentification will involve replacement of all the UIDs, Patient name, Patient Date of Birth, Center information, addresses as well as provider related information. For most fields these will be replaced with and #. However UIDs will be replaced with valid DICOM UIDs. 
# UID generation rules are as follows:
# Patient ID : Random UUID
# Study Instance UID : 1.2.840.113619.<random 5 digit number>.<random 4 digit number> 
# Series Instance UID : 1.2.840.113619.<random 5 digit number>.<random 4 digit number>.<random 5 digit number>
# SOP Instance UID : 1.2.840.113619.<random 5 digit number>.<random 4 digit number>.<random 5 digit number>.001, 002, 003 and so for the instance serially.
# Store the IDs in the database 
# - Deidentified patient ID (patient table)
# - Deidentified patient date of birth (patient table)
# - Deidentified study instance UID (study table)
# - Deidentified Study date (study table)
# - Deidentified Series instance UID (series table)
# - Deidentified frame of reference uid (series table)
# - Deidentified series date (series table)
# - Deidentified sop instance uid (instance table)
# Replace the uids and write the file to a local folder (deidentified_dicom). If folder does not exist create it.
# Generate the autosegmentation template file.yml and save it to the deidentified_dicom folder
# Zip the deidentified_dicom folder and save it to the deidentified_dicom folder. Remove the  folder after all files have been zipped.
# Update the processing_status field of the DICOMSeries model to DEIDENTIFIED_SUCCESSFULLY. Store the deidentified SEries instance UID, deiedentified zip file in the DICOMFileExport model
# Pass the zip file path to the next task along with corresponding DICOMSeriesUID. 
# Ensure logging of all operations while masking sensitive information.
