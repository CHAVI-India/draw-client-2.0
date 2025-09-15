# This will run after task1_poll_and_retrieve_rtstruct code runs and will take output from that.
# The purpose is to reidentify the RT struct file 
# For this we need to replace all UID values with the corresponding values from the database.
# The database lookup is to be done with respect to the deidentified_series_instance_uid value in the DICOMSeries table which should match with the referenced_series_intance_uid value in the RTStruct File.
# The following will need to be replaced:
# Referenced Series Instance UID : Series instance UID from the DICOMSeries table
# Patient ID: Patient ID from the Patient table
# Paitient Name: Patient Name from the Patient table
# Patient date of birth : Patient date of birth from the Patient table
# Study Instance UID: From the DicomStudy table
# Study Description: From the DicomStudy table
# Study Date : From the DicomStudy table
# Referring Physician Name : "DRAW"
# Accession Number : 202514789
# Frame of reference UIDs (0x0020,0x0052), (0x3006,0x0024) from the DICOM series Table
# Referenced SOP Instance UID  (0x0008,0x1155), (0x0020,0x000E) from the DICOM Instance table.
# After this file is written to the series_root_path available in the DICOMSeries table. This will ensure that the file is sent back to the same folder where the DICOM data was available. The filename should be starting with <PATIENT_ID>_<DRAW>_<DATETIME>_RTSTRUCT.dcm format.
# Update the series_processsing_status to RTSTRUCTURE_EXPORTED if successful else to RTSTRUCTURE_EXPORT_FAILED in the DICOMSeries model. 
# Update the path where the file was saved in the RTStructureFileImport model in the reidentified_rt_structure_file_path field and update the date time in reidentified_rt_structure_file_export_datetime field.
# Following this the RTstructurefile should be deleted from the folder where it was downloaded into. 


