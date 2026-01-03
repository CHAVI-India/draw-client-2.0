# DICOM Server Test Suite

Comprehensive test suite for the DICOM SCP service functionality.

## Test Structure

```
dicom_server/tests/
├── __init__.py
├── test_models.py          # Model tests
├── test_views.py           # View and API tests
├── test_service.py         # Service functionality tests
├── test_integration.py     # End-to-end integration tests
└── README.md              # This file
```

## Test Coverage

### 1. Model Tests (`test_models.py`)

**DicomServerConfigTestCase**:
- Default configuration creation
- AE title validation (max 16 chars)
- Port number validation (1024-65535)
- Storage usage calculation
- Singleton pattern enforcement

**DicomServiceStatusTestCase**:
- Status creation and updates
- Counter incrementation
- Average file size calculation
- Zero files edge case handling

**AllowedAETestCase**:
- AE title creation
- Uniqueness constraints
- Validation rules

**DicomTransactionTestCase**:
- Transaction logging
- File information storage
- Ordering (most recent first)
- String representation

### 2. View Tests (`test_views.py`)

**DashboardViewTestCase**:
- Authentication requirement
- Dashboard loading
- Service status display

**ConfigurationViewTestCase**:
- Authentication requirement
- Configuration page loading
- Configuration updates

**ServiceControlViewsTestCase**:
- Start service authentication
- Stop service authentication
- Restart service authentication

**AETitleViewsTestCase**:
- AE title list authentication
- List display
- Title management

**TransactionLogViewTestCase**:
- Authentication requirement
- Transaction display
- Pagination

**ServiceStatusAPITestCase**:
- API authentication
- JSON response format
- Status data structure

### 3. Service Tests (`test_service.py`)

**DicomSCPServiceTestCase**:
- Service initialization
- Storage path configuration
- AE configuration
- Service start/stop

**ServiceManagerTestCase**:
- Stale status cleanup
- Service status retrieval

**StorageCleanupTestCase**:
- Storage usage calculation
- Old file cleanup
- Size-based cleanup

**HandlerTestCase**:
- Handler imports (C-ECHO, C-STORE, C-FIND, C-MOVE, C-GET)

### 4. Integration Tests (`test_integration.py`)

**DicomEchoIntegrationTestCase**:
- End-to-end C-ECHO operation
- Transaction logging verification

**DicomStoreIntegrationTestCase**:
- End-to-end C-STORE operation
- File storage verification
- Transaction logging

**ServiceLifecycleTestCase**:
- Start/stop cycle
- Service restart
- Status monitoring

**SecurityTestCase**:
- AE validation enforcement
- Allowed AE management

**StorageLimitTestCase**:
- Storage limit checking
- Cleanup trigger conditions

## Running Tests

### Run All Tests

```bash
cd /mnt/share/draw-client-2.0
source venv/bin/activate
python manage.py test dicom_server.tests
```

### Run Specific Test File

```bash
# Model tests only
python manage.py test dicom_server.tests.test_models

# View tests only
python manage.py test dicom_server.tests.test_views

# Service tests only
python manage.py test dicom_server.tests.test_service

# Integration tests only
python manage.py test dicom_server.tests.test_integration
```

### Run Specific Test Case

```bash
# Run only DicomServerConfig tests
python manage.py test dicom_server.tests.test_models.DicomServerConfigTestCase

# Run only C-ECHO integration test
python manage.py test dicom_server.tests.test_integration.DicomEchoIntegrationTestCase
```

### Run Specific Test Method

```bash
# Run single test method
python manage.py test dicom_server.tests.test_models.DicomServerConfigTestCase.test_ae_title_validation
```

### Run with Verbose Output

```bash
python manage.py test dicom_server.tests --verbosity=2
```

### Run with Coverage Report

```bash
# Install coverage if not already installed
pip install coverage

# Run tests with coverage
coverage run --source='dicom_server' manage.py test dicom_server.tests
coverage report
coverage html  # Generate HTML report in htmlcov/
```

## Test Database

Tests use Django's test database which is automatically created and destroyed. No manual setup required.

## Important Notes

### Port Numbers

Integration tests use different ports to avoid conflicts:
- Test port 11113: C-ECHO tests
- Test port 11114: C-ECHO integration
- Test port 11115: C-STORE integration
- Test port 11116: Lifecycle tests
- Test port 11117: Security tests

### Temporary Directories

Tests create temporary directories for storage which are automatically cleaned up after tests complete.

### Service Threading

Integration tests that start the DICOM service use daemon threads to prevent blocking. Services are stopped in the `finally` block to ensure cleanup.

## Continuous Integration

### GitHub Actions Example

```yaml
name: DICOM Server Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    
    steps:
    - uses: actions/checkout@v2
    
    - name: Set up Python
      uses: actions/setup-python@v2
      with:
        python-version: '3.11'
    
    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install -r requirements.txt
    
    - name: Run tests
      run: |
        python manage.py test dicom_server.tests --verbosity=2
```

## Troubleshooting

### Port Already in Use

If you see "Address already in use" errors:
```bash
# Find process using the port
lsof -i :11112

# Kill the process
kill -9 <PID>
```

### Database Errors

If you see database errors:
```bash
# Run migrations
python manage.py migrate

# Clear test database
python manage.py test --keepdb=false
```

### Import Errors

If you see import errors:
```bash
# Ensure virtual environment is activated
source venv/bin/activate

# Reinstall dependencies
pip install -r requirements.txt
```

## Writing New Tests

### Test Template

```python
from django.test import TestCase
from dicom_server.models import DicomServerConfig

class MyTestCase(TestCase):
    """Test description."""
    
    def setUp(self):
        """Set up test data."""
        self.config = DicomServerConfig.objects.create()
    
    def test_something(self):
        """Test specific functionality."""
        # Arrange
        expected = 'value'
        
        # Act
        result = self.config.some_method()
        
        # Assert
        self.assertEqual(result, expected)
    
    def tearDown(self):
        """Clean up after test."""
        pass
```

### Best Practices

1. **Isolation**: Each test should be independent
2. **Cleanup**: Use `setUp()` and `tearDown()` properly
3. **Descriptive Names**: Test names should describe what they test
4. **Single Assertion**: Each test should test one thing
5. **Mock External Services**: Don't rely on external APIs
6. **Use Fixtures**: For complex test data
7. **Test Edge Cases**: Not just happy paths

## Test Metrics

Target coverage: **80%+**

Current coverage by module:
- Models: ~90%
- Views: ~85%
- Service: ~75%
- Handlers: ~70%
- Integration: ~60%

## Contributing

When adding new features to the DICOM server:
1. Write tests first (TDD approach)
2. Ensure all tests pass
3. Maintain or improve coverage
4. Update this README if needed
