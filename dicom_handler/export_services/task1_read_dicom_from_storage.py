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