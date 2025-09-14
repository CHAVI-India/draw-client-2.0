# DICOM Handler Export Services - Task Development Rules

## General Guidelines

### Code Structure
1. **Preserve Comments**: Never delete existing comments in task files - they contain important requirements and specifications
2. **Modular Design**: Each task should be implemented in its respective file in the `export_services` folder
3. **Function Naming**: Use descriptive function names that clearly indicate the task purpose
4. **Error Handling**: Implement comprehensive try-catch blocks with appropriate logging

### Logging Requirements
1. **Masking Sensitive Data**: Always mask patient identifiable information in logs
   - Patient names, IDs, birth dates
   - Institution names and addresses
   - Provider information
   - For UIDs: show only first and last 4 characters (e.g., "1234...5678")
   - Use format: `***FIELD_NAME_MASKED***` for sensitive fields

2. **Logging Levels**:
   - `INFO`: Task start/completion, major milestones, record creation
   - `DEBUG`: Detailed processing steps, file-by-file operations
   - `WARNING`: Recoverable errors, skipped files
   - `ERROR`: Critical errors, database issues

3. **Logging Format**: Include context about what is being processed while maintaining privacy

### Database Operations
1. **Atomic Transactions**: Use `transaction.atomic()` for database operations
2. **Error Recovery**: Handle database constraint violations gracefully
3. **Bulk Operations**: Consider bulk operations for large datasets
4. **Status Updates**: Always update processing status fields appropriately

### DICOM Processing Standards
1. **Modality Filtering**: Only process CT, MR, PT modalities unless specified otherwise
2. **UID Validation**: Always check for required DICOM UIDs before processing
3. **Force Reading**: Use `pydicom.dcmread(file_path, force=True)` to handle various file formats
4. **Metadata Extraction**: Use `getattr()` with defaults for optional DICOM tags

### File Handling
1. **Path Management**: 
   - Store full file paths in `instance_path`
   - Store directory paths in `series_root_path` (exclude filename)
2. **File Validation**: Check file existence and permissions before processing
3. **Timestamp Checks**: Implement file modification time filtering as specified

### Task Chain Requirements
1. **Return Values**: Each task should return structured data for the next task
2. **Status Tracking**: Update processing status at each stage
3. **Data Passing**: Pass required information (paths, UIDs, counts) between tasks
4. **Error Propagation**: Handle and log errors without breaking the chain
5. **JSON Serialization for Celery**: ALL return values must be JSON serializable
   - Convert dictionaries with complex keys to lists of dictionaries
   - Use basic Python types: str, int, float, bool, list, dict
   - Example: `{"series_uid": {...}}` → `[{"series_instance_uid": "series_uid", ...}]`
   - Test serialization: `json.dumps(return_value)` should work without errors

## Specific Task Requirements

### Task 1: Read DICOM from Storage
- ✅ Implemented with all requirements
- Filters: 10-minute modification window, date filters, existing records
- Creates: Patient, DICOMStudy, DICOMSeries, DICOMInstance records
- Returns: Series data for next task

### Task 2: Match Autosegmentation Template
- Check rulesets against DICOM metadata
- Handle AND/OR rule combinations
- Support numeric and string operators
- Update series processing status based on matches

### Task 3: Deidentify Series
- Replace UIDs with valid DICOM UIDs following specified patterns
- Mask patient information with # characters
- Generate autosegmentation template YAML
- Create ZIP files for transfer

### Task 4: Export to API
- Bearer token authentication
- Checksum validation
- File transfer with transaction ID tracking
- Clean up local files after successful transfer

## Security and Privacy
1. **Data Masking**: Never log unmasked patient data
2. **File Permissions**: Ensure proper file access controls
3. **Token Management**: Secure handling of bearer tokens
4. **Cleanup**: Remove temporary files after processing

## Testing and Validation
1. **Unit Tests**: Each function should be testable independently
2. **Integration Tests**: Test task chain flow
3. **Error Scenarios**: Test failure conditions and recovery
4. **Performance**: Monitor processing time for large datasets

## Documentation
1. **Docstrings**: Include comprehensive docstrings for all functions
2. **Type Hints**: Use type hints where appropriate
3. **Comments**: Explain complex logic and business rules
4. **Examples**: Provide usage examples in docstrings

## Memory Creation Guidelines
- Create memories for:
  - API response structures and field mappings
  - Database model relationships
  - Processing workflow patterns
  - Error handling strategies
  - Configuration requirements

Remember: These rules ensure consistency, maintainability, and compliance with medical data handling requirements across all export service tasks.
