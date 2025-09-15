# This task will run as a celery task as a seperate task and will poll the DRAW API server at regular intervals to download the segmented RTStructureSet file
# It will first generate a list of all DICOMFileExport objects where the deidentified_zip_file_transfer_status status is COMPLETED and server_segmentation_status value is NOT one of the following:
# - Delivered to Client
# - Transfer Completed
# To poll the server we need to make a reqest to the status endpoint for each object (specified in system configuration) with task_id in the request from the DICOMFileExport Model. Note bearer token authentication will have to be done using the draw_bearer token. Ensure proxy settings in the utils/proxy_conf are included to allow connections to pass through proxy servers.
# If the status turns to Segmentation Completed that means the RTstruct is available for download. Otherwise update the server_segmentation_status field with the status value provided by the server. Keep the file deidentified_zip_file_transfer_status as it is.
# Once the server_segmentation_status shows Segmentation Retrived that means that the RTStructure File is available for download.
# First update the status field in the DICOMFileExport model to reflect the server status
# Download the RTStructure file with the help of the task id using the draw_download_endpoint after bearer token authentication.
# First ensure that the checksum sent by the server along with the response matches the downloaded file checksum. If it does not delete the file that has been downloaded. Update the status in the DICOMFileTransferStatus to CHECKSUM_MATCH_FAILED. 
# Second check if the RTStructureSet is a valid DICOM File using pydicom (try reading it without force = True), and has the modality RTStruct if not then set the status to INVALID_RTSTRUCT_FILE
# Third check if the  Referenced Series Instance UID in the RTStruct File (tag (0x0020, 0x000E)) matches the deidentified series instance UID in the DICOM Series table. Remember that the deidentified series instance UID has to be checked as this file was segmented using deidentified data. If it does not again set the status to INVALID_RTSTRUCT_FILE.
# If Checksum match failes or file is not a valid DICOM file then mark DICOMSeries series_processsing_status also to INVALID_RTSTRUCTURE_RECEIVED. 
# If both these checks pass, make an entry in the RTStructureFileImport table linking the data to the DICOMSeries table. The deidentified_sop_intance_uid will be the actual sop_instance_uid of the rstructure file received. 
# Store the computed checksum. 
# Store the file path (create a downloaded_rtstruct folder if it does not exist). 
# Update the date and time when this file was received. 
# Notify the server that the RTStructure file was received. This can be done by sending a POST request to the notify endpoint (in the System configuration). Note that this is also protected by bearer token based authentication. After the notification has been sent and the the received response is "Transfer confirmation received, files cleaned up" then we update the following statuses:


# 1. Update server_segmentation_status field in the DICOMFileExport model to RTStructure Received
# 2. Update deidentified_zip_file_transfer_status field in the DICOMFileExport model to RTSTRUCT_RECEIVED
# 3. Update the Dicom series model series_processing_status to RTSTRUCTURE_RECEIVED  

# Create a json serializable output which has the full file paths of the RTstructureset files downloaded along with the corresponding DICOMSeries object for the next task in the chain that is reidentification of the RTstructure file and the export to the folder.
