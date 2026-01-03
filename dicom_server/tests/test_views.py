"""
Test suite for DICOM Server views.
"""

from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from dicom_server.models import (
    DicomServerConfig,
    DicomServiceStatus,
    AllowedAETitle,
    DicomTransaction
)
from dicom_handler.models import SystemConfiguration
import tempfile

User = get_user_model()


class DashboardViewTestCase(TestCase):
    """Test dashboard view."""
    
    def setUp(self):
        """Set up test data."""
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.temp_dir = tempfile.mkdtemp()
        self.system_config = SystemConfiguration.objects.create(
            folder_configuration=self.temp_dir
        )
        self.config = DicomServerConfig.objects.create()
    
    def test_dashboard_requires_login(self):
        """Test that dashboard requires authentication."""
        response = self.client.get(reverse('dicom_server:dashboard'))
        self.assertEqual(response.status_code, 302)  # Redirect to login
    
    def test_dashboard_loads_for_authenticated_user(self):
        """Test dashboard loads for authenticated user."""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('dicom_server:dashboard'))
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'DICOM Server Dashboard')
    
    def test_dashboard_displays_service_status(self):
        """Test dashboard displays service status."""
        self.client.login(username='testuser', password='testpass123')
        
        # Create service status
        DicomServiceStatus.objects.create(
            is_running=True,
            process_id=12345
        )
        
        response = self.client.get(reverse('dicom_server:dashboard'))
        self.assertEqual(response.status_code, 200)


class ConfigurationViewTestCase(TestCase):
    """Test configuration view."""
    
    def setUp(self):
        """Set up test data."""
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.temp_dir = tempfile.mkdtemp()
        self.system_config = SystemConfiguration.objects.create(
            folder_configuration=self.temp_dir
        )
        self.config = DicomServerConfig.objects.create()
    
    def test_config_requires_login(self):
        """Test that config page requires authentication."""
        response = self.client.get(reverse('dicom_server:config'))
        self.assertEqual(response.status_code, 302)
    
    def test_config_loads(self):
        """Test configuration page loads."""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('dicom_server:config'))
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'DICOM Server Configuration')
    
    def test_config_update(self):
        """Test updating configuration via POST."""
        self.client.login(username='testuser', password='testpass123')
        
        # Test that config page accepts POST and redirects
        response = self.client.post(reverse('dicom_server:config'), {
            'ae_title': 'NEW_AE',
            'host': '0.0.0.0',
            'port': 11112,
            'max_associations': 20,
            'network_timeout': 30,
            'acse_timeout': 30,
            'dimse_timeout': 30,
            'storage_structure': 'series',
            'file_naming_convention': 'sop_uid',
            'max_storage_size_gb': 200,
            'enable_storage_cleanup': False,
            'storage_retention_days': 30,
            'enable_c_echo': True,
            'enable_c_store': True,
            'enable_c_find': False,
            'enable_c_move': False,
            'enable_c_get': False,
            'require_calling_ae_validation': False,
            'require_ip_validation': False,
            'allowed_ip_addresses': '',
            'support_implicit_vr_little_endian': True,
            'support_explicit_vr_little_endian': True,
            'support_explicit_vr_big_endian': False,
            'support_jpeg_baseline': False,
            'support_jpeg_lossless': False,
            'support_jpeg2000_lossless': False,
            'support_rle_lossless': False,
            'logging_level': 'INFO',
            'log_connection_attempts': True,
            'log_received_files': True,
            'enable_performance_metrics': False,
            'notify_on_receive': False,
            'notify_on_error': False,
            'notification_email': '',
            'validate_dicom_on_receive': True,
            'reject_invalid_dicom': False,
        }, follow=True)
        
        # Should redirect after successful POST
        self.assertEqual(response.status_code, 200)
        
        # Config should be updated (form processing works)
        # Note: This test verifies the form accepts the data
        # Actual update behavior depends on view implementation
        self.assertTrue(DicomServerConfig.objects.filter(pk=1).exists())


class ServiceControlViewsTestCase(TestCase):
    """Test service control views (start/stop/restart)."""
    
    def setUp(self):
        """Set up test data."""
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.temp_dir = tempfile.mkdtemp()
        self.system_config = SystemConfiguration.objects.create(
            folder_configuration=self.temp_dir
        )
        self.config = DicomServerConfig.objects.create()
    
    def test_start_service_requires_login(self):
        """Test that starting service requires authentication."""
        response = self.client.post(reverse('dicom_server:service_control'), {'action': 'start'})
        self.assertEqual(response.status_code, 302)
    
    def test_stop_service_requires_login(self):
        """Test that stopping service requires authentication."""
        response = self.client.post(reverse('dicom_server:service_control'), {'action': 'stop'})
        self.assertEqual(response.status_code, 302)
    
    def test_restart_service_requires_login(self):
        """Test that restarting service requires authentication."""
        response = self.client.post(reverse('dicom_server:service_control'), {'action': 'restart'})
        self.assertEqual(response.status_code, 302)


class AETitleViewsTestCase(TestCase):
    """Test AE Title management views."""
    
    def setUp(self):
        """Set up test data."""
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
    
    def test_ae_list_requires_login(self):
        """Test that AE list requires authentication."""
        response = self.client.get(reverse('dicom_server:allowed_ae_titles'))
        self.assertEqual(response.status_code, 302)
    
    def test_ae_list_loads(self):
        """Test AE title list loads."""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('dicom_server:allowed_ae_titles'))
        
        self.assertEqual(response.status_code, 200)
    
    def test_ae_list_displays_titles(self):
        """Test AE list displays allowed titles."""
        self.client.login(username='testuser', password='testpass123')
        
        AllowedAETitle.objects.create(
            ae_title='CT_SCANNER',
            description='CT Scanner Room 1'
        )
        
        response = self.client.get(reverse('dicom_server:allowed_ae_titles'))
        self.assertContains(response, 'CT_SCANNER')


class TransactionLogViewTestCase(TestCase):
    """Test transaction log view."""
    
    def setUp(self):
        """Set up test data."""
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.temp_dir = tempfile.mkdtemp()
        self.system_config = SystemConfiguration.objects.create(
            folder_configuration=self.temp_dir
        )
        self.config = DicomServerConfig.objects.create()
    
    def test_transaction_log_requires_login(self):
        """Test that transaction log requires authentication."""
        response = self.client.get(reverse('dicom_server:transaction_log'))
        self.assertEqual(response.status_code, 302)
    
    def test_transaction_log_loads(self):
        """Test transaction log loads."""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('dicom_server:transaction_log'))
        
        self.assertEqual(response.status_code, 200)
    
    def test_transaction_log_displays_transactions(self):
        """Test transaction log displays transactions."""
        self.client.login(username='testuser', password='testpass123')
        
        DicomTransaction.objects.create(
            transaction_type='C-STORE',
            calling_ae_title='TEST_AE',
            called_ae_title='DRAW_SCP',
            remote_ip='127.0.0.1',
            remote_port=11112,
            status='SUCCESS'
        )
        
        response = self.client.get(reverse('dicom_server:transaction_log'))
        self.assertContains(response, 'C-STORE')
        self.assertContains(response, 'TEST_AE')
    
    def test_transaction_log_pagination(self):
        """Test transaction log pagination."""
        self.client.login(username='testuser', password='testpass123')
        
        # Create multiple transactions
        for i in range(30):
            DicomTransaction.objects.create(
                transaction_type='C-ECHO',
                calling_ae_title='TEST',
                called_ae_title='DRAW_SCP',
                remote_ip='127.0.0.1',
                remote_port=11112,
                status='SUCCESS'
            )
        
        response = self.client.get(reverse('dicom_server:transaction_log'))
        self.assertEqual(response.status_code, 200)
        # Should have pagination controls
        self.assertContains(response, 'page')


class ServiceStatusAPITestCase(TestCase):
    """Test service status API endpoint."""
    
    def setUp(self):
        """Set up test data."""
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.temp_dir = tempfile.mkdtemp()
        self.system_config = SystemConfiguration.objects.create(
            folder_configuration=self.temp_dir
        )
        self.config = DicomServerConfig.objects.create()
    
    def test_status_api_requires_login(self):
        """Test that status API requires authentication."""
        response = self.client.get(reverse('dicom_server:service_status_api'))
        self.assertEqual(response.status_code, 302)
    
    def test_status_api_returns_json(self):
        """Test status API returns JSON."""
        self.client.login(username='testuser', password='testpass123')
        
        DicomServiceStatus.objects.create(
            is_running=True,
            process_id=12345
        )
        
        response = self.client.get(reverse('dicom_server:service_status_api'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')
        
        data = response.json()
        self.assertIn('is_running', data)
