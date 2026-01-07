# DICOM Server Configuration Settings Guide

This document describes which configuration settings can be updated without restarting the DICOM service (hot-reload) and which require a full service restart.

## Hot-Reload Settings (No Restart Required)

These settings are read fresh from the database on every operation and take effect immediately:

### Storage Management
- **`max_storage_size_gb`** - Maximum storage size limit
  - Used by: C-STORE handler, storage cleanup
  - Effect: Immediate - next file transfer will use new limit
  
- **`enable_storage_cleanup`** - Enable automatic cleanup
  - Used by: Storage cleanup function
  - Effect: Immediate - next storage check will use new setting
  
- **`storage_retention_days`** - Days to retain files before cleanup
  - Used by: Storage cleanup function
  - Effect: Immediate - next cleanup will use new retention period

### File Processing
- **`validate_dicom_on_receive`** - Validate DICOM files on receive
  - Used by: C-STORE handler
  - Effect: Immediate - next file will be validated per new setting
  
- **`reject_invalid_dicom`** - Reject invalid DICOM files
  - Used by: C-STORE handler
  - Effect: Immediate - next invalid file will be handled per new setting
  
- **`log_received_files`** - Log details of received files
  - Used by: C-STORE handler
  - Effect: Immediate - next file transfer will be logged per new setting

### Storage Organization
- **`storage_structure`** - Directory structure (flat/patient/study/series/date)
  - Used by: C-STORE handler
  - Effect: Immediate - next file will be stored per new structure
  
- **`file_naming_convention`** - File naming convention
  - Used by: C-STORE handler
  - Effect: Immediate - next file will be named per new convention

### Integration
- **`copy_to_handler_folder`** - Copy files to handler folder
  - Used by: C-STORE handler
  - Effect: Immediate - next file will be copied per new setting
  
- **`trigger_processing_chain`** - Trigger processing chain
  - Used by: C-STORE handler
  - Effect: Immediate - next file will trigger processing per new setting

### Logging
- **`logging_level`** - Logging level (DEBUG/INFO/WARNING/ERROR)
  - Used by: Service initialization, config refresh
  - Effect: Immediate via `refresh_config()` method

## Restart Required Settings

These settings are loaded once at service initialization and require a full service restart to take effect:

### Network Configuration
- **`ae_title`** - Application Entity Title
- **`host`** - IP address to bind
- **`port`** - Port number
- **`max_associations`** - Maximum concurrent connections
- **`max_pdu_size`** - Maximum PDU size

### Timeout Settings
- **`network_timeout`** - Network timeout
- **`acse_timeout`** - ACSE timeout
- **`dimse_timeout`** - DIMSE timeout

### Security & Access Control
- **`require_calling_ae_validation`** - Require AE validation
- **`require_ip_validation`** - Require IP validation
- **`allowed_ip_addresses`** - Allowed IP addresses

### Service Capabilities - SOP Classes
- **`support_ct_image_storage`** - Accept CT images
- **`support_mr_image_storage`** - Accept MR images
- **`support_rt_structure_storage`** - Accept RT structures
- **`support_rt_plan_storage`** - Accept RT plans
- **`support_rt_dose_storage`** - Accept RT dose
- **`support_secondary_capture`** - Accept secondary capture

### Service Capabilities - DIMSE Services
- **`enable_c_echo`** - Enable C-ECHO
- **`enable_c_store`** - Enable C-STORE
- **`enable_c_find`** - Enable C-FIND
- **`enable_c_move`** - Enable C-MOVE
- **`enable_c_get`** - Enable C-GET

### Transfer Syntax Support
- **`support_implicit_vr_little_endian`** - Implicit VR Little Endian
- **`support_explicit_vr_little_endian`** - Explicit VR Little Endian
- **`support_explicit_vr_big_endian`** - Explicit VR Big Endian
- **`support_jpeg_baseline`** - JPEG Baseline
- **`support_jpeg_lossless`** - JPEG Lossless
- **`support_jpeg2000_lossless`** - JPEG 2000 Lossless
- **`support_rle_lossless`** - RLE Lossless

### Performance Monitoring
- **`log_connection_attempts`** - Log connection attempts
- **`enable_performance_metrics`** - Track performance metrics

## How to Apply Configuration Changes

### For Hot-Reload Settings
1. Update the setting in the Django admin panel or via API
2. The change takes effect immediately on the next operation
3. No service restart required

### For Restart Required Settings
1. Update the setting in the Django admin panel or via API
2. Restart the DICOM service:
   - Via Dashboard: Go to DICOM Server Dashboard → Click "Restart Service"
   - Via Docker: `docker-compose restart` or restart the container
   - Via Command: Use the service management commands

## Implementation Details

### Database Query Strategy
The system uses two strategies for configuration access:

1. **Fresh Config (Hot-Reload)**: Critical settings like storage limits are read directly from the database on every operation using `DicomServerConfig.objects.get(pk=1)`

2. **Cached Config (Restart Required)**: Network and protocol settings are loaded once at service initialization and cached in memory for performance

### Config Refresh Method
The service includes a `refresh_config()` method that can reload certain settings without full restart:

```python
service.refresh_config(force=True)  # Force refresh from database
```

This is useful for settings like logging level that can be updated without affecting network operations.

## Troubleshooting

### Setting Not Taking Effect
1. **Check if setting requires restart**: Refer to the lists above
2. **Verify database update**: Confirm the setting was saved in the database
3. **Check logs**: Look for "Configuration refreshed" or "Storage check" log messages
4. **Restart if needed**: For restart-required settings, restart the service

### Storage Limit Issues
If you update `max_storage_size_gb` and still see "storage limit reached" errors:
1. The fix ensures this setting is always read fresh from database
2. No restart should be needed after the fix is deployed
3. Check logs for "Storage check: XGB used / YGB max" messages
4. Verify the database value is correct in Django admin

## Version History

- **v2.0** (2026-01-07): Implemented hot-reload for storage and processing settings
- **v1.0** (Initial): All settings required restart
