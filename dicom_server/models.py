from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator, RegexValidator
from django.utils import timezone
import os
import re
import uuid

# Create your models here

class DicomServerConfig(models.Model):
    """
    Singleton model for DICOM SCP (Service Class Provider) configuration.
    This model stores all settings required to run a pynetdicom DICOM service.
    """
    id = models.IntegerField(primary_key=True, default=1, editable=False)
    
    # Service Status
    service_enabled = models.BooleanField(
        default=False,
        help_text="Enable or disable the DICOM service. When disabled, the service will not accept connections."
    )
    auto_start = models.BooleanField(
        default=False,
        help_text="Automatically start the DICOM service when the Django application starts."
    )
    
    # Network Configuration
    ae_title = models.CharField(
        max_length=16,
        default="DRAW_SCP",
        validators=[
            RegexValidator(
                regex=r'^[A-Z0-9_\-]+$',
                message='AE Title must contain only uppercase letters, numbers, underscores, and hyphens.',
                code='invalid_ae_title'
            )
        ],
        help_text="Application Entity Title for this DICOM service (max 16 characters, uppercase alphanumeric)."
    )
    host = models.CharField(
        max_length=45,
        default="0.0.0.0",
        help_text="IP address to bind the DICOM service (0.0.0.0 for all interfaces, or specific IP)."
    )
    port = models.IntegerField(
        default=11112,
        validators=[MinValueValidator(1024), MaxValueValidator(65535)],
        help_text="Port number for DICOM communication (default: 11112, range: 1024-65535)."
    )
    max_associations = models.IntegerField(
        default=10,
        validators=[MinValueValidator(1), MaxValueValidator(100)],
        help_text="Maximum number of concurrent DICOM associations/connections."
    )
    max_pdu_size = models.IntegerField(
        default=16384,
        validators=[MinValueValidator(4096), MaxValueValidator(131072)],
        help_text="Maximum Protocol Data Unit size in bytes (default: 16384, range: 4096-131072)."
    )
    
    # Timeout Settings
    network_timeout = models.IntegerField(
        default=30,
        validators=[MinValueValidator(5), MaxValueValidator(300)],
        help_text="Network timeout in seconds (default: 30)."
    )
    acse_timeout = models.IntegerField(
        default=30,
        validators=[MinValueValidator(5), MaxValueValidator(300)],
        help_text="ACSE (Association Control Service Element) timeout in seconds (default: 30)."
    )
    dimse_timeout = models.IntegerField(
        default=30,
        validators=[MinValueValidator(5), MaxValueValidator(300)],
        help_text="DIMSE (DICOM Message Service Element) timeout in seconds (default: 30)."
    )
    
    # Storage Configuration
    # Note: This field is automatically populated from SystemConfiguration.folder_configuration at runtime
    # and does not need to be manually configured
    
    STORAGE_STRUCTURE_CHOICES = [
        ('flat', 'Flat - All files in root directory'),
        ('patient', 'Patient ID - Organized by Patient ID'),
        ('study', 'Study UID - Organized by Study Instance UID'),
        ('series', 'Series UID - Organized by Patient/Study/Series hierarchy'),
        ('date', 'Date - Organized by received date (YYYY/MM/DD)'),
    ]
    storage_structure = models.CharField(
        max_length=20,
        choices=STORAGE_STRUCTURE_CHOICES,
        default='series',
        help_text="Directory structure for organizing stored DICOM files."
    )
    
    FILE_NAMING_CHOICES = [
        ('sop_uid', 'SOP Instance UID'),
        ('instance_number', 'Instance Number'),
        ('timestamp', 'Timestamp'),
        ('sequential', 'Sequential Number'),
    ]
    file_naming_convention = models.CharField(
        max_length=20,
        choices=FILE_NAMING_CHOICES,
        default='sop_uid',
        help_text="Naming convention for stored DICOM files."
    )
    
    max_storage_size_gb = models.IntegerField(
        default=100,
        validators=[MinValueValidator(1), MaxValueValidator(10000)],
        help_text="Maximum storage size in GB. Service will reject new files when limit is reached."
    )
    
    enable_storage_cleanup = models.BooleanField(
        default=False,
        help_text="Enable automatic cleanup of old files when storage limit is reached."
    )
    
    storage_retention_days = models.IntegerField(
        default=30,
        validators=[MinValueValidator(1), MaxValueValidator(3650)],
        help_text="Number of days to retain files before cleanup (only if cleanup is enabled)."
    )
    
    # Security & Access Control
    require_calling_ae_validation = models.BooleanField(
        default=True,
        help_text="Require validation of calling AE titles. Only allowed AE titles can connect."
    )
    
    require_ip_validation = models.BooleanField(
        default=False,
        help_text="Require IP address validation. Only whitelisted IPs can connect."
    )
    
    allowed_ip_addresses = models.TextField(
        blank=True,
        null=True,
        help_text="Comma-separated list of allowed IP addresses or CIDR ranges (e.g., 192.168.1.0/24, 10.0.0.5)."
    )
    
    # Service Capabilities - SOP Classes
    support_ct_image_storage = models.BooleanField(
        default=True,
        help_text="Accept CT Image Storage (1.2.840.10008.5.1.4.1.1.2)."
    )
    support_mr_image_storage = models.BooleanField(
        default=True,
        help_text="Accept MR Image Storage (1.2.840.10008.5.1.4.1.1.4)."
    )
    support_rt_structure_storage = models.BooleanField(
        default=True,
        help_text="Accept RT Structure Set Storage (1.2.840.10008.5.1.4.1.1.481.3)."
    )
    support_rt_plan_storage = models.BooleanField(
        default=True,
        help_text="Accept RT Plan Storage (1.2.840.10008.5.1.4.1.1.481.5)."
    )
    support_rt_dose_storage = models.BooleanField(
        default=True,
        help_text="Accept RT Dose Storage (1.2.840.10008.5.1.4.1.1.481.2)."
    )
    support_secondary_capture = models.BooleanField(
        default=True,
        help_text="Accept Secondary Capture Image Storage (1.2.840.10008.5.1.4.1.1.7)."
    )
    
    # Service Capabilities - DIMSE Services
    enable_c_echo = models.BooleanField(
        default=True,
        help_text="Enable C-ECHO (verification/ping) service."
    )
    enable_c_store = models.BooleanField(
        default=True,
        help_text="Enable C-STORE (receive DICOM files) service."
    )
    enable_c_find = models.BooleanField(
        default=False,
        help_text="Enable C-FIND (query) service for Patient/Study/Series level queries."
    )
    enable_c_move = models.BooleanField(
        default=False,
        help_text="Enable C-MOVE (retrieve) service to send DICOM files to remote destinations."
    )
    enable_c_get = models.BooleanField(
        default=False,
        help_text="Enable C-GET (retrieve) service to send DICOM files over the same association."
    )
    
    # Transfer Syntax Support
    support_implicit_vr_little_endian = models.BooleanField(
        default=True,
        help_text="Support Implicit VR Little Endian transfer syntax (1.2.840.10008.1.2)."
    )
    support_explicit_vr_little_endian = models.BooleanField(
        default=True,
        help_text="Support Explicit VR Little Endian transfer syntax (1.2.840.10008.1.2.1)."
    )
    support_explicit_vr_big_endian = models.BooleanField(
        default=False,
        help_text="Support Explicit VR Big Endian transfer syntax (1.2.840.10008.1.2.2)."
    )
    support_jpeg_baseline = models.BooleanField(
        default=True,
        help_text="Support JPEG Baseline compression (1.2.840.10008.1.2.4.50)."
    )
    support_jpeg_lossless = models.BooleanField(
        default=True,
        help_text="Support JPEG Lossless compression (1.2.840.10008.1.2.4.70)."
    )
    support_jpeg2000_lossless = models.BooleanField(
        default=False,
        help_text="Support JPEG 2000 Lossless compression (1.2.840.10008.1.2.4.90)."
    )
    support_rle_lossless = models.BooleanField(
        default=False,
        help_text="Support RLE Lossless compression (1.2.840.10008.1.2.5)."
    )
    
    
    # Logging & Monitoring
    LOGGING_LEVEL_CHOICES = [
        ('DEBUG', 'Debug - Verbose logging'),
        ('INFO', 'Info - Normal logging'),
        ('WARNING', 'Warning - Only warnings and errors'),
        ('ERROR', 'Error - Only errors'),
    ]
    logging_level = models.CharField(
        max_length=10,
        choices=LOGGING_LEVEL_CHOICES,
        default='INFO',
        help_text="Logging level for DICOM service operations."
    )
    
    log_connection_attempts = models.BooleanField(
        default=True,
        help_text="Log all connection attempts (successful and failed)."
    )
    
    log_received_files = models.BooleanField(
        default=True,
        help_text="Log details of all received DICOM files."
    )
    
    enable_performance_metrics = models.BooleanField(
        default=True,
        help_text="Track and log performance metrics (transfer speeds, processing times)."
    )
    
    # Notification Settings
    notify_on_receive = models.BooleanField(
        default=False,
        help_text="Send notification when new DICOM data is received."
    )
    
    notify_on_error = models.BooleanField(
        default=True,
        help_text="Send notification when errors occur during DICOM operations."
    )
    
    notification_email = models.EmailField(
        blank=True,
        null=True,
        help_text="Email address for notifications (leave blank to disable email notifications)."
    )
    
    # Validation Settings
    validate_dicom_on_receive = models.BooleanField(
        default=True,
        help_text="Validate DICOM file structure and required tags on receive."
    )
    
    reject_invalid_dicom = models.BooleanField(
        default=False,
        help_text="Reject and do not store invalid DICOM files."
    )
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_service_start = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Timestamp of last service start."
    )
    last_service_stop = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Timestamp of last service stop."
    )
    
    class Meta:
        verbose_name = "DICOM Server Configuration"
        verbose_name_plural = "DICOM Server Configuration"
    
    def clean(self):
        """
        Custom validation for configuration settings.
        """
        super().clean()
        
        # Validate AE Title length and format
        if self.ae_title and len(self.ae_title) > 16:
            raise ValidationError({
                'ae_title': 'AE Title cannot exceed 16 characters.'
            })
        
        # Validate IP addresses format if IP validation is enabled
        if self.require_ip_validation and self.allowed_ip_addresses:
            ip_list = [ip.strip() for ip in self.allowed_ip_addresses.split(',')]
            for ip in ip_list:
                # Basic IP/CIDR validation
                if not re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(/\d{1,2})?$', ip):
                    raise ValidationError({
                        'allowed_ip_addresses': f'Invalid IP address or CIDR format: {ip}'
                    })
        
        # Ensure at least one service is enabled
        if not any([self.enable_c_echo, self.enable_c_store, self.enable_c_find, 
                    self.enable_c_move, self.enable_c_get]):
            raise ValidationError(
                'At least one DIMSE service (C-ECHO, C-STORE, C-FIND, C-MOVE, or C-GET) must be enabled.'
            )
        
        # Ensure at least one transfer syntax is supported
        if not any([self.support_implicit_vr_little_endian, self.support_explicit_vr_little_endian,
                    self.support_explicit_vr_big_endian, self.support_jpeg_baseline,
                    self.support_jpeg_lossless, self.support_jpeg2000_lossless, self.support_rle_lossless]):
            raise ValidationError(
                'At least one transfer syntax must be supported.'
            )
    
    def save(self, *args, **kwargs):
        # Run validation before saving
        self.full_clean()
        # Ensure only one instance exists (singleton pattern)
        self.pk = 1
        super(DicomServerConfig, self).save(*args, **kwargs)
    
    def delete(self, *args, **kwargs):
        # Prevent deletion of the singleton instance
        pass
    
    def __str__(self):
        return f"DICOM Server Config - {self.ae_title} ({self.host}:{self.port})"
    
    @property
    def is_running(self):
        """
        Check if the service is currently running.
        This will be implemented in the service management logic.
        """
        # Placeholder - actual implementation will check process status
        return False
    
    @property
    def storage_usage_gb(self):
        """
        Calculate current storage usage in GB.
        """
        try:
            from dicom_handler.models import SystemConfiguration
            system_config = SystemConfiguration.objects.get(pk=1)
            storage_path = system_config.folder_configuration
            
            if not storage_path or not os.path.exists(storage_path):
                return 0
            
            total_size = 0
            for dirpath, dirnames, filenames in os.walk(storage_path):
                for filename in filenames:
                    filepath = os.path.join(dirpath, filename)
                    if os.path.exists(filepath):
                        total_size += os.path.getsize(filepath)
            
            return round(total_size / (1024**3), 2)
        except:
            return 0
    
    @property
    def storage_available_gb(self):
        """
        Calculate available storage in GB.
        """
        return max(0, self.max_storage_size_gb - self.storage_usage_gb)
    
    @property
    def storage_usage_percent(self):
        """
        Calculate storage usage percentage.
        """
        if self.max_storage_size_gb == 0:
            return 0
        return round((self.storage_usage_gb / self.max_storage_size_gb) * 100, 2)


class AllowedAETitle(models.Model):
    """
    Model to store allowed Application Entity Titles for DICOM connections.
    Only AE titles in this list will be allowed to connect if validation is enabled.
    """
    ae_title = models.CharField(
        max_length=16,
        unique=True,
        validators=[
            RegexValidator(
                regex=r'^[A-Z0-9_\-]+$',
                message='AE Title must contain only uppercase letters, numbers, underscores, and hyphens.',
                code='invalid_ae_title'
            )
        ],
        help_text="Application Entity Title to allow (max 16 characters)."
    )
    description = models.CharField(
        max_length=255,
        blank=True,
        help_text="Description of this AE (e.g., 'Main CT Scanner', 'MR Console')."
    )
    ip_address = models.GenericIPAddressField(
        blank=True,
        null=True,
        help_text="Expected IP address for this AE (optional, for documentation)."
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this AE is currently allowed to connect."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_connection = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Timestamp of last successful connection from this AE."
    )
    
    class Meta:
        verbose_name = "Allowed AE Title"
        verbose_name_plural = "Allowed AE Titles"
        ordering = ['ae_title']
    
    def __str__(self):
        return f"{self.ae_title} - {self.description if self.description else 'No description'}"


class DicomTransaction(models.Model):
    """
    Audit log for all DICOM transactions (C-STORE, C-FIND, C-MOVE, etc.).
    Tracks all operations for monitoring and troubleshooting.
    """
    TRANSACTION_TYPE_CHOICES = [
        ('C-ECHO', 'C-ECHO (Verification)'),
        ('C-STORE', 'C-STORE (Storage)'),
        ('C-FIND', 'C-FIND (Query)'),
        ('C-MOVE', 'C-MOVE (Move)'),
        ('C-GET', 'C-GET (Get)'),
        ('ASSOCIATION', 'Association Request'),
    ]
    
    STATUS_CHOICES = [
        ('SUCCESS', 'Success'),
        ('FAILURE', 'Failure'),
        ('REJECTED', 'Rejected'),
        ('TIMEOUT', 'Timeout'),
        ('ABORTED', 'Aborted'),
    ]
    
    transaction_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )
    transaction_type = models.CharField(
        max_length=20,
        choices=TRANSACTION_TYPE_CHOICES,
        help_text="Type of DICOM operation."
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        help_text="Status of the transaction."
    )
    
    # Connection Information
    calling_ae_title = models.CharField(
        max_length=16,
        help_text="AE Title of the calling entity."
    )
    called_ae_title = models.CharField(
        max_length=16,
        help_text="AE Title of the called entity (this server)."
    )
    remote_ip = models.GenericIPAddressField(
        help_text="IP address of the remote entity."
    )
    remote_port = models.IntegerField(
        help_text="Port of the remote entity."
    )
    
    # DICOM Data Information (for C-STORE)
    patient_id = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        help_text="Patient ID from DICOM file."
    )
    study_instance_uid = models.CharField(
        max_length=128,
        blank=True,
        null=True,
        help_text="Study Instance UID."
    )
    series_instance_uid = models.CharField(
        max_length=128,
        blank=True,
        null=True,
        help_text="Series Instance UID."
    )
    sop_instance_uid = models.CharField(
        max_length=128,
        blank=True,
        null=True,
        help_text="SOP Instance UID."
    )
    sop_class_uid = models.CharField(
        max_length=128,
        blank=True,
        null=True,
        help_text="SOP Class UID (modality type)."
    )
    
    # File Information
    file_path = models.CharField(
        max_length=512,
        blank=True,
        null=True,
        help_text="Path where the file was stored (for C-STORE)."
    )
    file_size_bytes = models.BigIntegerField(
        blank=True,
        null=True,
        help_text="Size of the received file in bytes."
    )
    transfer_syntax = models.CharField(
        max_length=128,
        blank=True,
        null=True,
        help_text="Transfer syntax used for the operation."
    )
    
    # Performance Metrics
    duration_seconds = models.FloatField(
        blank=True,
        null=True,
        help_text="Duration of the transaction in seconds."
    )
    transfer_speed_mbps = models.FloatField(
        blank=True,
        null=True,
        help_text="Transfer speed in MB/s (for C-STORE)."
    )
    
    # Error Information
    error_message = models.TextField(
        blank=True,
        null=True,
        help_text="Error message if transaction failed."
    )
    
    # Metadata
    timestamp = models.DateTimeField(
        auto_now_add=True,
        help_text="Timestamp when the transaction occurred."
    )
    
    class Meta:
        verbose_name = "DICOM Transaction"
        verbose_name_plural = "DICOM Transactions"
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['-timestamp']),
            models.Index(fields=['calling_ae_title']),
            models.Index(fields=['study_instance_uid']),
            models.Index(fields=['status']),
        ]
    
    def __str__(self):
        return f"{self.transaction_type} - {self.calling_ae_title} - {self.status} ({self.timestamp})"


class DestinationAETitle(models.Model):
    """
    Model to store destination AE configurations for C-MOVE operations.
    These are remote DICOM nodes where files can be sent via C-MOVE.
    """
    ae_title = models.CharField(
        max_length=16,
        unique=True,
        validators=[
            RegexValidator(
                regex=r'^[A-Z0-9_\-]+$',
                message='AE Title must contain only uppercase letters, numbers, underscores, and hyphens.',
                code='invalid_ae_title'
            )
        ],
        help_text="Destination Application Entity Title (max 16 characters)."
    )
    description = models.CharField(
        max_length=255,
        blank=True,
        help_text="Description of this destination (e.g., 'PACS Server', 'Backup Archive')."
    )
    host = models.CharField(
        max_length=255,
        help_text="Hostname or IP address of the destination."
    )
    port = models.IntegerField(
        validators=[MinValueValidator(1024), MaxValueValidator(65535)],
        default=11112,
        help_text="Port number of the destination DICOM service."
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this destination is currently available for C-MOVE operations."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_used = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Timestamp of last successful C-MOVE to this destination."
    )
    
    class Meta:
        verbose_name = "Destination AE Title"
        verbose_name_plural = "Destination AE Titles"
        ordering = ['ae_title']
    
    def __str__(self):
        return f"{self.ae_title} ({self.host}:{self.port})"


class DicomServiceStatus(models.Model):
    """
    Model to track DICOM service runtime status and statistics.
    Updated periodically while the service is running.
    """
    id = models.IntegerField(primary_key=True, default=1, editable=False)
    
    is_running = models.BooleanField(
        default=False,
        help_text="Whether the DICOM service is currently running."
    )
    process_id = models.IntegerField(
        blank=True,
        null=True,
        help_text="Process ID of the running DICOM service."
    )
    
    # Service Uptime
    service_started_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Timestamp when the service was started."
    )
    service_stopped_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Timestamp when the service was stopped."
    )
    
    # Statistics
    total_connections = models.IntegerField(
        default=0,
        help_text="Total number of connections since service start."
    )
    active_connections = models.IntegerField(
        default=0,
        help_text="Current number of active connections."
    )
    total_files_received = models.IntegerField(
        default=0,
        help_text="Total number of DICOM files received since service start."
    )
    total_bytes_received = models.BigIntegerField(
        default=0,
        help_text="Total bytes received since service start."
    )
    total_errors = models.IntegerField(
        default=0,
        help_text="Total number of errors since service start."
    )
    
    # Last Activity
    last_connection_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Timestamp of last connection."
    )
    last_file_received_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Timestamp of last file received."
    )
    
    # Metadata
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="Last update timestamp."
    )
    
    class Meta:
        verbose_name = "DICOM Service Status"
        verbose_name_plural = "DICOM Service Status"
    
    def save(self, *args, **kwargs):
        # Ensure only one instance exists (singleton pattern)
        self.pk = 1
        super(DicomServiceStatus, self).save(*args, **kwargs)
    
    def delete(self, *args, **kwargs):
        # Prevent deletion of the singleton instance
        pass
    
    def __str__(self):
        status = "Running" if self.is_running else "Stopped"
        return f"DICOM Service Status: {status}"
    
    @property
    def uptime_seconds(self):
        """
        Calculate service uptime in seconds.
        """
        if self.is_running and self.service_started_at:
            return (timezone.now() - self.service_started_at).total_seconds()
        return 0
    
    @property
    def uptime_formatted(self):
        """
        Return formatted uptime string.
        """
        if not self.is_running or not self.service_started_at:
            return "Not running"
        
        uptime = timezone.now() - self.service_started_at
        days = uptime.days
        hours, remainder = divmod(uptime.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        if days > 0:
            return f"{days}d {hours}h {minutes}m"
        elif hours > 0:
            return f"{hours}h {minutes}m"
        else:
            return f"{minutes}m {seconds}s"
    
    @property
    def average_file_size_mb(self):
        """
        Calculate average file size in MB.
        """
        if self.total_files_received == 0:
            return 0
        return round((self.total_bytes_received / self.total_files_received) / (1024**2), 2)