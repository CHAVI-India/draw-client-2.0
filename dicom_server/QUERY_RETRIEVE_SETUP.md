# DICOM Query/Retrieve Implementation Guide

## Overview
Complete DICOM Query/Retrieve (C-FIND/C-MOVE/C-GET) interface for querying and retrieving DICOM data from remote PACS and modalities.

## ✅ Completed Components

### 1. Database Models (`models.py`)
- **RemoteDicomNode**: Manage remote PACS/modalities with connection settings
- **DicomQuery**: Track C-FIND query operations with parameters and results
- **DicomQueryResult**: Store individual query results with DICOM metadata
- **DicomRetrieveJob**: Track C-MOVE/C-GET retrieve operations with progress

### 2. Query/Retrieve Service (`query_retrieve_service.py`)
- **C-FIND (Query)**: Query remote nodes at Patient, Study, Series, or Image level
- **C-MOVE (Retrieve)**: Pull DICOM data from remote nodes to local storage
- **C-GET (Retrieve)**: Alternative retrieve method with direct transfer
- **Connection Testing**: C-ECHO verification for remote nodes
- **Progress Tracking**: Real-time monitoring of retrieve operations

### 3. Forms (`forms_qr.py`)
- **RemoteDicomNodeForm**: Add/edit remote DICOM nodes
- **DicomQueryForm**: Advanced query interface with date ranges and wildcards

### 4. Views (`views_qr.py`)
- Remote node management (list, add, edit, delete, test)
- Query interface with search form
- Query results display with retrieve buttons
- Retrieve job monitoring
- Query history

### 5. Templates (`templates/dicom_server/qr/`)
- `remote_nodes_list.html` - List and manage remote nodes
- `remote_node_form.html` - Add/edit remote node
- `remote_node_confirm_delete.html` - Delete confirmation
- `query_interface.html` - Search interface with filters
- `query_results.html` - Display query results with retrieve actions
- `query_history.html` - View past queries
- `retrieve_jobs.html` - Monitor retrieve operations

### 6. URL Patterns (`urls.py`)
All Query/Retrieve routes configured under `/dicom-server/qr/`

### 7. Django Admin (`admin.py`)
Full admin interface for all Query/Retrieve models

## 🚧 Next Steps to Complete

### Step 1: Create Database Migrations
```bash
cd /mnt/share/draw-client-2.0
source venv/bin/activate
python manage.py makemigrations dicom_server
python manage.py migrate
```

### Step 2: Add Navigation Links

#### Option A: Update DICOM Server Dashboard
Add Query/Retrieve quick actions to `templates/dicom_server/dashboard.html`:

```html
<!-- Add after existing quick actions -->
<div class="bg-white rounded-lg shadow-md p-6">
    <h3 class="text-lg font-semibold text-gray-900 mb-4">Query/Retrieve</h3>
    <div class="space-y-3">
        <a href="{% url 'dicom_server:query_interface' %}" 
           class="block px-4 py-3 bg-blue-50 text-blue-700 rounded-lg hover:bg-blue-100 transition">
            <div class="flex items-center">
                <svg class="w-5 h-5 mr-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path>
                </svg>
                <span class="font-medium">Query Remote Nodes</span>
            </div>
        </a>
        <a href="{% url 'dicom_server:remote_nodes_list' %}" 
           class="block px-4 py-3 bg-purple-50 text-purple-700 rounded-lg hover:bg-purple-100 transition">
            <div class="flex items-center">
                <svg class="w-5 h-5 mr-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 12h14M12 5l7 7-7 7"></path>
                </svg>
                <span class="font-medium">Manage Remote Nodes</span>
            </div>
        </a>
        <a href="{% url 'dicom_server:retrieve_jobs' %}" 
           class="block px-4 py-3 bg-green-50 text-green-700 rounded-lg hover:bg-green-100 transition">
            <div class="flex items-center">
                <svg class="w-5 h-5 mr-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M9 19l3 3m0 0l3-3m-3 3V10"></path>
                </svg>
                <span class="font-medium">Retrieve Jobs</span>
            </div>
        </a>
    </div>
</div>
```

#### Option B: Update Main Navigation
Add to main navbar if desired.

### Step 3: Test the Interface

1. **Start Django server**:
   ```bash
   python manage.py runserver
   ```

2. **Access Query/Retrieve**:
   - Navigate to: http://localhost:8000/dicom-server/qr/nodes/
   - Add a remote DICOM node (PACS or modality)
   - Test connection
   - Perform queries
   - Retrieve studies/series

### Step 4: Configure Remote Nodes

For each remote PACS/modality, configure:
- **Name**: Friendly identifier (e.g., "Main PACS")
- **AE Title**: Remote application entity title
- **Host**: IP address or hostname
- **Port**: DICOM port (usually 11112 or 104)
- **Capabilities**: C-FIND, C-MOVE, C-GET support
- **Query/Retrieve Model**: Patient Root, Study Root, or Patient/Study Only
- **Move Destination**: Your local AE title (for C-MOVE)

## Features

### Query Capabilities
- **Multi-level queries**: Patient, Study, Series, Image
- **Wildcard support**: Use `*` for partial matches
- **Date ranges**: Search by study date ranges
- **Modality filtering**: Filter by CT, MR, CR, etc.
- **Query history**: Track all past queries
- **Result pagination**: Handle large result sets

### Retrieve Capabilities
- **C-MOVE support**: Standard DICOM retrieve
- **C-GET support**: Alternative retrieve method
- **Progress tracking**: Real-time progress monitoring
- **Study/Series level**: Retrieve entire studies or specific series
- **Job history**: Track all retrieve operations
- **Error handling**: Detailed error messages and retry capability

### Security Features
- **Authentication required**: All operations require login
- **User tracking**: Track who initiated queries and retrieves
- **Connection validation**: Test connections before use
- **Timeout settings**: Configurable connection timeouts
- **IP validation**: Optional IP address restrictions

## Usage Workflow

1. **Add Remote Node**: Configure connection to PACS/modality
2. **Test Connection**: Verify connectivity with C-ECHO
3. **Query**: Search for patients/studies/series
4. **Review Results**: Browse query results with metadata
5. **Retrieve**: Pull selected studies/series to local storage
6. **Monitor**: Track retrieve job progress
7. **Verify**: Check received files in local storage

## Integration with DICOM Handler

Retrieved DICOM files are stored in the configured storage directory and will be automatically picked up by the `dicom_handler` app's polling mechanism for further processing (deidentification, autosegmentation, export).

## Troubleshooting

### Connection Issues
- Verify remote node is accessible (ping, telnet)
- Check firewall rules
- Confirm AE title matches remote configuration
- Verify port number

### Query Issues
- Check query level matches remote node capabilities
- Verify query/retrieve model setting
- Use wildcards for broader searches
- Check remote node logs

### Retrieve Issues
- Ensure local DICOM server (SCP) is running
- Verify move destination AE title matches local config
- Check storage permissions
- Monitor retrieve job status for errors

## Notes

- **Lint Warnings**: CSS `@apply` and JavaScript template syntax warnings in templates are harmless - they're processed correctly by Django/Tailwind
- **Performance**: Large queries may take time - use date ranges and filters to narrow results
- **Storage**: Monitor disk space when retrieving large studies
- **Concurrency**: Multiple retrieve jobs can run simultaneously

## Support

For issues or questions:
1. Check Django logs for detailed error messages
2. Review transaction log in DICOM server dashboard
3. Test connection with C-ECHO before querying
4. Verify remote node configuration matches PACS settings
