# Task 4: Send the deidentified series to the Draw API server (code to be written to task4_export_series_to_api.py)
# For each Zip file which has been deidentified, send it to the DRAW API Server. First we will update the status for the DICOMFileExport model to PENDING_TRANSFER_TO_DRAW_SERVER
# Prior to each transfer ensure that the API endpoint is accepting file transfer
# User bearer token authentication for the authentication
# Calculate the zip file checksum prior to sending it and update the checksum value in the database. (DICOMFileExport model). This checksum value has to be sent as the API payload along with the file. 
# Update the status for the DICOMFileExport model to SENT_TO_DRAW_SERVER
# Delete the zip file after successful transfer
# Note the transaction ID provided by the API server and update the transaction_id field in the DICOMFileExport model
# Ensure logging of all operations while masking sensitive information.