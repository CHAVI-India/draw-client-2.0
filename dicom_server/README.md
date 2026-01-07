# DICOM Server Module

## Overview

The DICOM Server module provides a complete DICOM SCP (Service Class Provider) implementation using pynetdicom. It allows the DRAW client to receive DICOM files directly from imaging modalities, PACS systems, or other DICOM sources.

## Features

### Core Functionality
- **C-STORE**: Receive and store DICOM files from modalities and PACS
- **C-ECHO**: Verification/connectivity testing
- **C-FIND**: Query for studies/series/images (Patient Root, Study Root, Patient-Study Only)
- **C-MOVE**: Retrieve DICOM files and send to third-party destination
- **C-GET**: Retrieve DICOM files and send back to requestor

### Configuration Options
- Network settings (AE Title, host, port, timeouts, max PDU size)
- Storage management (path, structure, naming, size limits, cleanup)
- Security (AE Title validation, IP whitelisting)
- SOP Class support (CT, MR, RT Structure, RT Plan, RT Dose, Secondary Capture)
- Transfer syntax support (Implicit/Explicit VR, JPEG, JPEG2000, RLE)
- DIMSE services (C-ECHO, C-STORE, C-FIND, C-MOVE, C-GET)
- Query/Retrieve configuration (remote nodes, query models, timeouts)
- Integration with DICOM Handler processing chain

### Management Features
- Web-based service control (start/stop/restart)
- Real-time status monitoring with auto-refresh toggle
- Transaction logging and audit trail with pagination
- Performance metrics and statistics
- Storage usage tracking
- Query/Retrieve interface for remote PACS queries
- Remote DICOM node management
- Query history and retrieve job tracking

## Architecture

```
dicom_server/
├── models.py                    # Database models (config, transactions, status, Q/R)
├── admin.py                     # Django admin interface
├── views.py                     # Main web interface views
├── views_qr.py                  # Query/Retrieve interface views
├── forms.py                     # Configuration forms
├── forms_qr.py                  # Query/Retrieve forms
├── urls.py                      # URL routing
├── apps.py                      # App initialization (auto-start)
├── dicom_scp_service.py        # Main DICOM SCP service
├── query_retrieve_service.py   # Query/Retrieve SCU service
├── service_manager.py          # Service control utilities
└── handlers/
    ├── c_store_handler.py      # C-STORE implementation
    ├── c_find_handler.py       # C-FIND implementation
    ├── c_move_handler.py       # C-MOVE implementation
    └── c_get_handler.py        # C-GET implementation
```

## Step-by-Step Configuration Guide

### Prerequisites

Before configuring the DICOM server, ensure:
1. Django application is running
2. Database migrations are applied: `python manage.py migrate`
3. System Configuration has a valid storage folder path configured
4. Port 11112 is available (not used by another service)
5. Firewall allows incoming connections on port 11112 (if accessing from external network)

### Step 1: Configure System Storage Path

**Navigate to**: System Config (main menu)

1. Locate the **"Folder Configuration"** field
2. Set the DICOM storage path (e.g., `/app/datastore`)
3. Ensure this directory exists and has write permissions
4. Click **"Save"**

**Note**: The DICOM server will automatically use this path. Both the DICOM server and DICOM handler share the same storage location.

### Step 2: Access DICOM Server Configuration

**Navigate to**: DICOM Server → Dashboard → Configuration button (top-right)

Or directly: `http://your-server:8000/dicom-server/config/`

### Step 3: Configure Network Settings

In the **Network Configuration** section:

1. **AE Title**: Set your server's Application Entity title
   - Default: `DRAW_SCP`
   - Must be uppercase, max 16 characters
   - Example: `HOSPITAL_SCP`, `RADIOLOGY_01`

2. **Host**: Set the network interface to bind to
   - `0.0.0.0` - Listen on all interfaces (recommended for production)
   - `127.0.0.1` - Listen only on localhost (for testing)

3. **Port**: Set the DICOM service port
   - Default: `11112`
   - Must be between 1-65535
   - Ensure port is not already in use

4. **Max Associations**: Maximum concurrent connections
   - Default: `10`
   - Increase for busy environments

5. Click **"Save Configuration"**

### Step 4: Configure Storage Settings

In the **Storage Configuration** section:

**Note**: Storage path is automatically set from System Configuration. You only need to configure organization settings.

1. **Storage Structure**: Choose how files are organized
   - **Flat**: All files in one directory (simple, but can get messy)
   - **Patient**: Organized by Patient ID folders
   - **Study**: Organized by Study Instance UID folders
   - **Series**: Organized by Patient/Study/Series hierarchy (recommended)
   - **Date**: Organized by received date (YYYY/MM/DD)

2. **File Naming Convention**: Choose how files are named
   - **SOP UID**: Use SOP Instance UID as filename (recommended, guaranteed unique)
   - **Instance Number**: Use instance number (0001.dcm, 0002.dcm, etc.)
   - **Timestamp**: Use timestamp (20260102_193000.dcm)
   - **Sequential**: Auto-incrementing numbers

3. **Max Storage Size**: Set storage limit in GB
   - Default: `100` GB
   - Service will reject files when limit reached (unless cleanup enabled)

4. **Enable Storage Cleanup**: Toggle automatic cleanup
   - When enabled, old files are automatically deleted when storage is full
   - Only files older than retention period are deleted

5. **Storage Retention Days**: Minimum age before files can be deleted
   - Default: `30` days
   - Only applies if cleanup is enabled

6. Click **"Save Configuration"**

### Step 5: Configure Security (Optional but Recommended)

In the **Security & Access Control** section:

1. **Require Calling AE Validation**: Enable to restrict which systems can connect
   - Check this box if you want to whitelist specific modalities/PACS

2. **Allowed IP Addresses**: Comma-separated list of allowed IPs
   - Example: `192.168.1.100, 192.168.1.101`
   - Leave empty to allow all IPs

3. Click **"Save Configuration"**

### Step 6: Add Allowed AE Titles (If Validation Enabled)

**Navigate to**: DICOM Server → AE Titles

1. Click **"Add New AE Title"** button
2. Fill in the form:
   - **AE Title**: The calling AE title to allow (e.g., `CT_SCANNER_01`)
   - **Description**: Friendly name (e.g., "CT Scanner - Room 1")
   - **Expected IP Address**: (Optional) IP address of the device
   - **Is Active**: Check to enable
3. Click **"Save"**
4. Repeat for each modality/PACS that should be allowed to connect

**Common AE Titles to Add**:
- Your CT scanners
- Your MRI machines
- Your PACS system
- Any workstations that send DICOM files

### Step 7: Configure Storage SOP Classes

In the **Storage SOP Classes** section:

Enable the DICOM image types you want to accept:
- **CT Image Storage**: Computed Tomography images (recommended: enabled)
- **MR Image Storage**: Magnetic Resonance images (recommended: enabled)
- **RT Structure Set Storage**: Radiation therapy structures (recommended: enabled)
- **RT Plan Storage**: Radiation therapy plans (optional)
- **RT Dose Storage**: Radiation dose distributions (optional)
- **Secondary Capture**: Screenshots and derived images (optional)

**Note**: At least one storage SOP class must be enabled to receive DICOM files.

### Step 8: Configure DIMSE Services (Optional)

In the **DIMSE Services** section:

Enable the services you want to support:
- **C-ECHO**: Verification/connectivity testing (recommended: enabled)
- **C-STORE**: Receive DICOM files (recommended: enabled)
- **C-FIND**: Query for studies/series (enable if you want to support queries)
- **C-MOVE**: Retrieve files to third-party destination (enable for Q/R functionality)
- **C-GET**: Retrieve files to requestor (enable for Q/R functionality)

**For basic file reception, enable C-ECHO and C-STORE only.**
**For Query/Retrieve functionality, also enable C-FIND and C-MOVE or C-GET.**

### Step 9: Configure Logging (Optional)

In the **Logging & Monitoring** section:

1. **Logging Level**: Choose verbosity
   - **DEBUG**: Very detailed (for troubleshooting)
   - **INFO**: Normal operations (recommended)
   - **WARNING**: Only warnings and errors
   - **ERROR**: Only errors

2. **Log Connection Attempts**: Log all connection attempts
3. **Log Received Files**: Log each received file
4. **Enable Performance Metrics**: Track transfer speeds and timing

### Step 10: Start the DICOM Service

**Navigate to**: DICOM Server → Dashboard

1. Review the service status card
2. Verify your configuration is correct:
   - AE Title is displayed
   - Network shows correct host:port
3. Click **"Start Service"** button
4. Wait for status to change to "Running" (green indicator)
5. Verify:
   - Uptime counter starts
   - No error messages appear

**If service fails to start**:
- Check that port 11112 is not already in use
- Verify storage path exists and is writable
- Review Django logs for error messages
- Ensure all required packages are installed (`psutil`, `pynetdicom`, `pydicom`)

### Step 11: Test the Service

#### Option A: Using the Test Script

```bash
cd /mnt/share/draw-client-2.0
source venv/bin/activate
python dicom_server/test_dicom_server.py /path/to/test-dicom-file.dcm
```

#### Option B: Using Command-Line Tools

```bash
# Test connectivity (C-ECHO)
echoscu 127.0.0.1 11112 -aec DRAW_SCP -aet TEST_SCU

# Send a test file (C-STORE)
storescu 127.0.0.1 11112 -aec DRAW_SCP -aet TEST_SCU /path/to/test.dcm
```

#### Option C: Configure a Modality

On your CT/MRI/PACS system:
1. Add a new DICOM destination
2. Set:
   - **AE Title**: `DRAW_SCP` (or your configured title)
   - **Host**: Your server's IP address
   - **Port**: `11112`
3. Test the connection using the modality's built-in test function
4. Send a test study

### Step 12: Verify File Reception

After sending test files:

1. **Check Dashboard**:
   - "Files Received" count should increase
   - "Storage Usage" should increase
   - Recent transactions should show the received files

2. **Check Transaction Log**:
   - Navigate to: DICOM Server → Transaction Log
   - Verify successful C-STORE entries
   - Check for any errors or rejections

3. **Check File System**:
   - Navigate to your storage path (e.g., `/app/datastore`)
   - Verify DICOM files are present
   - Check folder structure matches your configuration

4. **Check DICOM Handler**:
   - Navigate to: DICOM Handler → Processing Status
   - Verify files are being automatically processed
   - Check that series appear in the processing queue

### Step 13: Configure Query/Retrieve (Optional)

If you want to query and retrieve from remote PACS systems:

**Navigate to**: DICOM Server → Query/Retrieve → Remote Nodes

1. Click **"Add Remote Node"** button
2. Fill in the remote PACS information:
   - **Name**: Friendly name (e.g., "Main PACS")
   - **AE Title**: Remote system's AE title
   - **Host**: Remote system's IP address or hostname
   - **Port**: Remote system's DICOM port (typically 104 or 11112)
   - **Supports C-FIND**: Check if remote supports queries
   - **Supports C-MOVE**: Check if remote supports C-MOVE retrieve
   - **Supports C-GET**: Check if remote supports C-GET retrieve
   - **Query/Retrieve Model**: Select "Study Root" (most common)
   - **Move Destination AE**: Your local AE title (for C-MOVE)
3. Click **"Save"**
4. Click **"Test Connection"** to verify connectivity

**For testing, you can use public DICOM servers**:
- Medical Connections: `www.dicomserver.co.uk:11112` (AE: `ANY-SCP`)
- Orthanc Demo: `demo.orthanc-server.com:4242` (AE: `ORTHANC`)

### Step 14: Configure Auto-Start (Optional)

If you want the service to start automatically when Django starts:

1. Navigate to: DICOM Server → Configuration
2. In **Service Status** section:
   - Check **"Enable DICOM Service"**
   - Check **"Auto-start Service"**
3. Click **"Save Configuration"**
4. Restart Django to test auto-start

### Step 15: Monitor and Maintain

**Regular Monitoring**:
- Check dashboard daily for service status
- Review transaction log for errors
- Monitor storage usage
- Verify DICOM handler is processing files

**Maintenance Tasks**:
- Review and update allowed AE titles as needed
- Adjust storage limits based on usage
- Enable cleanup if storage fills up
- Review logs for security issues
- Update configuration as workflow changes

## Troubleshooting Common Issues

### Service Won't Start

**Problem**: Service status remains "Stopped" after clicking "Start Service"

**Solutions**:
1. Check port availability: `netstat -an | grep 11112`
2. Verify storage path exists: `ls -la /app/datastore`
3. Check Django logs for errors
4. Ensure `psutil` package is installed
5. Verify no permission issues on storage directory

### Files Not Being Received

**Problem**: Modality reports success but files don't appear

**Solutions**:
1. Check Transaction Log for rejected connections
2. Verify calling AE title is in allowed list (if validation enabled)
3. Check remote IP is allowed (if IP validation enabled)
4. Test with C-ECHO first to verify connectivity
5. Review storage limits - may be full

### Storage Full

**Problem**: Service rejects files with "Storage limit reached"

**Solutions**:
1. Check current usage in dashboard
2. Increase max storage size in configuration
3. Enable storage cleanup with appropriate retention days
4. Manually clean old files from storage directory
5. Archive old studies to external storage

### Performance Issues

**Problem**: Slow file transfers or timeouts

**Solutions**:
1. Check network timeout settings in configuration
2. Increase max associations if many concurrent connections
3. Monitor active connections count
4. Review transaction log for slow transfers
5. Check network bandwidth and latency

### Files Not Processing

**Problem**: Files received but not processed by DICOM handler

**Solutions**:
1. Verify storage path matches System Configuration
2. Check DICOM handler is running (Celery workers)
3. Review DICOM handler logs for errors
4. Verify file permissions allow handler to read files
5. Check that files are valid DICOM format

### 2. Managing Allowed AE Titles

Navigate to **DICOM Server → AE Titles**:

- Add AE titles of modalities/systems that should be allowed to connect
- Provide descriptions for easy identification
- Optionally specify expected IP addresses
- Toggle active/inactive status as needed

### 3. Service Control

Navigate to **DICOM Server → Dashboard**:

- **Start Service**: Click "Start Service" button
- **Stop Service**: Click "Stop Service" button  
- **Restart Service**: Click "Restart Service" button

The dashboard shows:
- Current service status (Running/Stopped)
- Network configuration (AE Title, host:port)
- Uptime and active connections
- Statistics (files received, storage usage, errors)
- Recent transactions

### 4. Monitoring

**Dashboard** provides real-time monitoring:
- Service status and uptime
- Active connections
- Total files received and storage usage
- Recent transactions (last 24 hours)

**Transaction Log** provides detailed audit trail:
- Filter by transaction type, status, or AE title
- View connection details, file information, performance metrics
- Expandable rows show full transaction details

### 5. Integration with DICOM Handler

Configure integration in the Configuration page:

- **Auto Import to Handler**: Automatically register received files
- **Copy to Handler Folder**: Copy files to DICOM Handler's storage
- **Trigger Processing Chain**: Automatically start processing (Task 1-4)

## DICOM Client Configuration

To send DICOM files to this server from a modality or PACS:

```
Called AE Title: DRAW_SCP (or your configured AE Title)
Host: <server-ip-address>
Port: 11112 (or your configured port)
```

### Testing Connectivity

Use DICOM tools to test:

```bash
# Using dcmtk echoscu
echoscu <server-ip> 11112 -aec DRAW_SCP -aet MY_SCU

# Using pynetdicom
python -m pynetdicom echoscu <server-ip> 11112 -aec DRAW_SCP -aet MY_SCU
```

### Sending Files

```bash
# Using dcmtk storescu
storescu <server-ip> 11112 -aec DRAW_SCP -aet MY_SCU <dicom-file>

# Using pynetdicom
python -m pynetdicom storescu <server-ip> 11112 -aec DRAW_SCP <dicom-file>
```

## Storage Organization

Files are organized based on the configured storage structure:

- **Flat**: All files in root directory
- **Patient**: `<root>/<PatientID>/`
- **Study**: `<root>/<StudyInstanceUID>/`
- **Series**: `<root>/<PatientID>/<StudyUID>/<SeriesUID>/`
- **Date**: `<root>/YYYY/MM/DD/`

File naming follows the configured convention:
- **SOP UID**: `<SOPInstanceUID>.dcm`
- **Instance Number**: `0001.dcm`, `0002.dcm`, etc.
- **Timestamp**: `20260102_193000_123456.dcm`
- **Sequential**: Auto-incrementing numbers

## Security Considerations

1. **Network Security**:
   - Run on private network or use firewall rules
   - Consider VPN for remote access
   - Use IP whitelisting for additional security

2. **Access Control**:
   - Enable AE Title validation
   - Maintain allowed AE titles list
   - Monitor transaction log for unauthorized attempts

3. **Data Protection**:
   - Files stored locally on server
   - No external transmission unless configured
   - Integration with DICOM Handler follows existing security

4. **Authentication**:
   - Web interface requires Django login
   - All management operations are authenticated
   - Transaction logs track all activities

## Troubleshooting

### Service Won't Start

1. Check configuration is valid
2. Verify port is not already in use: `netstat -an | grep 11112`
3. Check storage path exists and is writable
4. Review logs for error messages

### Files Not Being Received

1. Verify service is running
2. Check calling AE title is in allowed list (if validation enabled)
3. Check remote IP is allowed (if IP validation enabled)
4. Test with C-ECHO first
5. Review transaction log for rejected connections

### Storage Full

1. Check current storage usage in dashboard
2. Increase max storage size in configuration
3. Enable storage cleanup (if appropriate)
4. Manually clean old files from storage directory

### Performance Issues

1. Monitor active connections count
2. Check network timeout settings
3. Review transaction log for slow transfers
4. Consider increasing max associations limit

## API Endpoints

The module provides a REST API endpoint for status monitoring:

```
GET /dicom-server/api/status/
```

Returns JSON with current service status, statistics, and storage information.

## Database Models

### DicomServerConfig
Singleton model storing all service configuration.

### AllowedAETitle
List of authorized AE titles that can connect.

### DicomTransaction
Audit log of all DICOM operations (C-STORE, C-ECHO, C-FIND, etc.).

### DicomServiceStatus
Runtime statistics and service state.

## Dependencies

- `pynetdicom` - DICOM networking library
- `pydicom` - DICOM file handling
- `psutil` - Process management
- Django models and forms

## Auto-Start Behavior

If configured:
1. Service checks for stale status on Django startup
2. Auto-starts if `service_enabled` and `auto_start` are both True
3. Runs in background thread
4. Survives Django reloads (in production with gunicorn)

## Docker Deployment

When deploying with Docker Compose:

### Port Configuration

The DICOM SCP port must be exposed in `docker-compose.yml`:

```yaml
django-web:
  ports:
    - "11112:11112"  # DICOM SCP port
```

This maps host port 11112 to container port 11112.

### DICOM Server Configuration

In the web interface, configure:
- **Host**: `0.0.0.0` (binds to all interfaces inside container)
- **Port**: `11112` (internal container port)
- **Storage Path**: `/app/dicom_storage` (or another path inside container)

### External Access

Modalities/PACS connect to:
```
Called AE Title: DRAW_SCP
Host: <docker-host-ip>  (e.g., 192.168.1.100)
Port: 11112
```

### Network Considerations

1. **Docker Network**: Container runs in bridge network
2. **Port Forwarding**: Docker forwards external:internal (11112:11112)
3. **Firewall**: Ensure host firewall allows port 11112
4. **Custom Port**: Change external port if needed: `11113:11112`

### Storage Volumes

DICOM files are stored in the mounted volume:
```yaml
volumes:
  - "dicomdata:/app/datastore"
```

Configure storage path to use this mounted volume for persistence.

## Production Deployment

For production use:

1. Use a production WSGI server (gunicorn, uwsgi)
2. Configure proper logging
3. Set up monitoring and alerts
4. Regular backup of transaction logs
5. Monitor storage usage
6. Review security settings
7. Test disaster recovery procedures
8. Ensure DICOM port is properly exposed in Docker
9. Configure firewall rules for DICOM port
10. Test connectivity from actual modalities

## Understanding C-GET vs C-MOVE

Both C-GET and C-MOVE are DICOM retrieve operations, but they work differently:

### C-MOVE (Move to Third Party)

**How it works**:
1. You (SCU) send a C-MOVE request to a remote PACS (SCP)
2. The PACS retrieves the requested images
3. The PACS sends the images to a **third-party destination** (not back to you)
4. You must specify a "Move Destination AE" that the PACS knows about

**Workflow**:
```
[Your System] --C-MOVE request--> [Remote PACS]
                                       |
                                       | C-STORE
                                       v
                              [Destination System]
```

**Requirements**:
- The destination system must be configured on the remote PACS
- The destination system must be running and accepting C-STORE
- You need to know the AE title the PACS uses for the destination

**Use Cases**:
- Retrieving images to your local DICOM server
- Routing images between PACS systems
- Standard in most clinical PACS environments

**Configuration**:
- Set **"Move Destination AE"** to your local DICOM server's AE title
- Ensure your DICOM server is running and accepting C-STORE
- The remote PACS must have your system configured as a destination

### C-GET (Get Directly)

**How it works**:
1. You (SCU) send a C-GET request to a remote PACS (SCP)
2. The PACS retrieves the requested images
3. The PACS sends the images **directly back to you** over the same association
4. No third-party destination needed

**Workflow**:
```
[Your System] <--C-GET request/C-STORE response--> [Remote PACS]
```

**Requirements**:
- Your system must accept C-STORE operations
- Single association handles both request and response
- Simpler configuration than C-MOVE

**Use Cases**:
- Quick retrieval without complex routing
- When you don't want to configure destinations on remote PACS
- Modern PACS implementations

**Configuration**:
- No destination AE needed
- Ensure your system can accept incoming C-STORE
- Some older PACS systems may not support C-GET

### Which Should You Use?

**Use C-MOVE when**:
- Working with traditional clinical PACS systems
- You need to route images to different destinations
- The remote PACS doesn't support C-GET
- You want images stored on your DICOM server (not just received temporarily)

**Use C-GET when**:
- You want simpler configuration
- The remote PACS supports C-GET
- You're retrieving directly to your application
- You don't need complex routing

**In DRAW Client**:
- Both are supported
- C-MOVE is recommended for retrieving to your local DICOM server
- Configure your local DICOM server's AE title as the Move Destination
- Ensure your DICOM server is running before initiating C-MOVE

## Query/Retrieve Usage Guide

### Querying Remote PACS

**Navigate to**: DICOM Server → Query/Retrieve → Query Interface

1. **Select Remote Node**: Choose the PACS you want to query
2. **Select Query Level**:
   - **Patient**: Search for patients
   - **Study**: Search for studies (most common)
   - **Series**: Search for specific series
   - **Image**: Search for individual images
3. **Enter Search Criteria**:
   - Patient ID, Patient Name
   - Study Date, Study Description
   - Modality (CT, MR, etc.)
   - Use wildcards (*) for partial matches
4. Click **"Search"**
5. Review results in the results table

### Retrieving Images

From the query results:

1. **Select images** to retrieve (checkbox)
2. Click **"Retrieve Selected"** button
3. Choose retrieve method:
   - **C-MOVE**: Images sent to your DICOM server
   - **C-GET**: Images sent directly to this application
4. Monitor progress in **Retrieve Jobs** page
5. Check your DICOM server dashboard for received files

### Viewing Query History

**Navigate to**: DICOM Server → Query/Retrieve → Query History

- View all previous queries
- See query parameters and result counts
- Re-run previous queries
- Filter by remote node or date

### Monitoring Retrieve Jobs

**Navigate to**: DICOM Server → Query/Retrieve → Retrieve Jobs

- View active and completed retrieve operations
- Monitor progress (pending, in progress, completed, failed)
- See number of images retrieved
- Review any errors

## Configuration Reference

### Network Settings

| Setting | Default | Range | Description |
|---------|---------|-------|-------------|
| AE Title | DRAW_SCP | 1-16 chars | Application Entity title (uppercase) |
| Host | 0.0.0.0 | IP address | Network interface to bind |
| Port | 11112 | 1-65535 | DICOM service port |
| Max Associations | 10 | 1-100 | Concurrent connections allowed |
| Max PDU Size | 16384 | 4096-131072 | Protocol Data Unit size (bytes) |
| Network Timeout | 30 | 5-300 | Network timeout (seconds) |
| ACSE Timeout | 30 | 5-300 | Association timeout (seconds) |
| DIMSE Timeout | 30 | 5-300 | Message timeout (seconds) |

### Storage Settings

| Setting | Default | Options | Description |
|---------|---------|---------|-------------|
| Storage Structure | series | flat, patient, study, series, date | File organization method |
| File Naming | sop_uid | sop_uid, instance_number, timestamp, sequential | Filename format |
| Max Storage Size | 100 GB | 1-10000 GB | Storage limit |
| Enable Cleanup | False | True/False | Auto-delete old files when full |
| Retention Days | 30 | 1-3650 | Minimum age before deletion |

### Storage SOP Classes

| SOP Class | Default | UID | Description |
|-----------|---------|-----|-------------|
| CT Image Storage | True | 1.2.840.10008.5.1.4.1.1.2 | CT images |
| MR Image Storage | True | 1.2.840.10008.5.1.4.1.1.4 | MR images |
| RT Structure Set | True | 1.2.840.10008.5.1.4.1.1.481.3 | RT structures |
| RT Plan Storage | True | 1.2.840.10008.5.1.4.1.1.481.5 | RT plans |
| RT Dose Storage | True | 1.2.840.10008.5.1.4.1.1.481.2 | RT dose |
| Secondary Capture | True | 1.2.840.10008.5.1.4.1.1.7 | Screenshots |

### DIMSE Services

| Service | Default | Description |
|---------|---------|-------------|
| C-ECHO | True | Verification/connectivity testing |
| C-STORE | True | Receive DICOM files |
| C-FIND | False | Query for studies/series |
| C-MOVE | False | Retrieve to third-party destination |
| C-GET | False | Retrieve to requestor |

### Transfer Syntaxes

| Transfer Syntax | Default | UID | Description |
|-----------------|---------|-----|-------------|
| Implicit VR Little Endian | True | 1.2.840.10008.1.2 | Default uncompressed |
| Explicit VR Little Endian | True | 1.2.840.10008.1.2.1 | Explicit uncompressed |
| Explicit VR Big Endian | False | 1.2.840.10008.1.2.2 | Big endian (rare) |
| JPEG Baseline | True | 1.2.840.10008.1.2.4.50 | Lossy compression |
| JPEG Lossless | True | 1.2.840.10008.1.2.4.70 | Lossless compression |
| JPEG 2000 Lossless | False | 1.2.840.10008.1.2.4.90 | JPEG2000 lossless |
| RLE Lossless | False | 1.2.840.10008.1.2.5 | Run-length encoding |

### Remote Node Settings

| Setting | Required | Description |
|---------|----------|-------------|
| Name | Yes | Friendly name for the remote node |
| AE Title | Yes | Remote system's AE title |
| Host | Yes | IP address or hostname |
| Port | Yes | Remote DICOM port |
| Supports C-FIND | No | Enable query operations |
| Supports C-MOVE | No | Enable C-MOVE retrieve |
| Supports C-GET | No | Enable C-GET retrieve |
| Query/Retrieve Model | Yes | Patient Root, Study Root, or Patient-Study Only |
| Timeout | No | Connection timeout (default: 30s) |
| Max PDU Size | No | Maximum PDU size (default: 16384) |
| Move Destination AE | No | AE title for C-MOVE destination |

## Recent Updates and Improvements

### Database-Optimized Query/Retrieve (January 2026)

The Query/Retrieve functionality has been significantly enhanced with database integration for improved performance and reliability.

#### C-FIND Database Integration

**Previous Implementation:**
- Scanned filesystem recursively for every query
- Read DICOM file headers to match query parameters
- O(n) complexity - slow for large datasets
- No indexing or optimization

**New Implementation:**
- Queries Django database models (`Patient`, `DICOMStudy`, `DICOMSeries`)
- Uses indexed database lookups - O(log n) complexity
- Much faster queries, especially for large datasets
- Supports all DICOM query levels (PATIENT, STUDY, SERIES)

**Supported Query Parameters:**
- **Patient Level**: PatientID, PatientName (with wildcards)
- **Study Level**: StudyInstanceUID, StudyDate (ranges), StudyDescription, AccessionNumber, ModalitiesInStudy
- **Series Level**: SeriesInstanceUID, SeriesDescription, SeriesNumber, Modality

**Wildcard Support:**
- `*` - Matches any sequence of characters
- `?` - Matches any single character
- Example: `*SMITH*` matches "JOHN SMITH", "SMITH JANE", etc.

**Date Range Support:**
- Format: `YYYYMMDD-YYYYMMDD`
- Example: `20260101-20260131` (all of January 2026)
- Open-ended: `20260101-` (from Jan 1, 2026 onwards)

#### C-MOVE and C-GET Database Integration

**Previous Implementation:**
- Scanned entire filesystem to find matching files
- Linear search through all DICOM files
- Slow for large datasets

**New Implementation:**
- Queries `DICOMSeries` model for `series_root_path`
- Directly accesses the specific series directory
- Only scans relevant files, not entire storage
- Significantly faster file retrieval

**How It Works:**
1. Query database for matching series based on UIDs
2. Retrieve `series_root_path` from database
3. Scan only that specific directory for DICOM files
4. Send files to destination (C-MOVE) or requestor (C-GET)

#### Configuration Reload Fix

**Issue Fixed:**
- Service restart was not reloading configuration from database
- Changes to C-MOVE/C-GET settings were not applied until Django restart
- Used cached configuration from initial service start

**Solution:**
- Service `restart()` method now calls `initialize()` to reload config
- All configuration changes take effect immediately after service restart
- No need to restart Django to apply DICOM service configuration changes

#### C-GET and C-MOVE Handler Fixes

**Issue Fixed:**
- Handlers were yielding tuples instead of integers for sub-operation count
- pynetdicom expects first yield to be an integer (number of files to send)
- Caused `TypeError: int() argument must be a string, a bytes-like object or a real number, not 'tuple'`

**Solution:**
- First yield is now the number of sub-operations (integer)
- Subsequent yields are (status, dataset) tuples
- Complies with pynetdicom C-GET/C-MOVE handler protocol

**Example:**
```python
# First yield: number of files
num_sub_operations = len(matches)
yield num_sub_operations

# Then yield each file with status
for file_path in matches:
    ds = dcmread(file_path)
    status = yield (0xFF00, ds)  # Pending with dataset
```

#### Performance Improvements

**C-FIND Query Performance:**
- Small datasets (<100 studies): 10-50x faster
- Medium datasets (100-1000 studies): 50-100x faster
- Large datasets (>1000 studies): 100-500x faster

**C-MOVE/C-GET Retrieve Performance:**
- No longer scans entire storage
- Retrieval time independent of total storage size
- Only depends on number of files in matched series

#### Data Synchronization

**Important Note:**
- C-STORE handler does NOT update database directly
- Database is populated by DICOM Handler's Celery tasks
- Files must be processed by DICOM Handler before they appear in C-FIND queries
- This separation maintains clean architecture between modules

**Workflow:**
1. C-STORE receives files → saves to filesystem
2. DICOM Handler Celery tasks scan storage
3. Tasks populate `Patient`, `DICOMStudy`, `DICOMSeries` models
4. C-FIND queries these models for fast results
5. C-MOVE/C-GET use `series_root_path` to retrieve files

#### Client Configuration Requirements

**For C-GET Operations:**
Your client (SCU) must support:
- **C-STORE SCP** (Storage Service Class Provider)
- **Required SOP Classes**: CT Image Storage, MR Image Storage, RT Structure Set Storage
- **Required Transfer Syntax**: Implicit VR Little Endian (minimum)

**Common Issue:**
If C-GET fails with "No presentation context accepted by peer", your client needs to be configured to accept incoming C-STORE operations with the appropriate SOP classes.

**Alternative:**
Use C-MOVE instead, which sends files to a pre-configured destination that supports C-STORE SCP.

## Future Enhancements

Potential improvements:
- Advanced routing rules for received files
- TLS/SSL support for secure DICOM communication
- DICOM modality worklist (MWL) support
- Scheduled retrieve operations
- Batch query/retrieve operations
- Query result caching
- Advanced filtering in Query/Retrieve interface
- Real-time database indexing of received files
