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
        validators=[MinValueValidator(1), MaxValueValidator(65535)],
        help_text="Port number for DICOM communication (default: 11112, range: 1-65535)."
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
    
    # Cached Storage Statistics (to avoid slow filesystem walks on every page load)
    cached_storage_usage_bytes = models.BigIntegerField(
        default=0,
        help_text="Cached storage usage in bytes. Updated periodically to avoid performance issues."
    )
    cached_storage_last_updated = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Timestamp when storage cache was last updated."
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
        Return cached storage usage in GB.
        Uses cached value to avoid slow filesystem walks on every page load.
        Cache is updated by update_storage_cache() method.
        """
        return round(self.cached_storage_usage_bytes / (1024**3), 2)
    
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
    
    def update_storage_cache(self):
        """
        Update the cached storage usage by walking the filesystem.
        This is an expensive operation and should be called periodically,
        not on every page load.
        """
        try:
            from dicom_handler.models import SystemConfiguration
            system_config = SystemConfiguration.objects.get(pk=1)
            storage_path = system_config.folder_configuration
            
            if not storage_path or not os.path.exists(storage_path):
                self.cached_storage_usage_bytes = 0
                self.cached_storage_last_updated = timezone.now()
                self.save(update_fields=['cached_storage_usage_bytes', 'cached_storage_last_updated'])
                return 0
            
            total_size = 0
            for dirpath, dirnames, filenames in os.walk(storage_path):
                for filename in filenames:
                    filepath = os.path.join(dirpath, filename)
                    if os.path.exists(filepath):
                        try:
                            total_size += os.path.getsize(filepath)
                        except (OSError, FileNotFoundError):
                            # Skip files that can't be accessed
                            continue
            
            self.cached_storage_usage_bytes = total_size
            self.cached_storage_last_updated = timezone.now()
            self.save(update_fields=['cached_storage_usage_bytes', 'cached_storage_last_updated'])
            return round(total_size / (1024**3), 2)
        except Exception as e:
            # Log error but don't crash
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error updating storage cache: {e}")
            return 0
    
    def should_update_storage_cache(self, max_age_minutes=5):
        """
        Check if storage cache should be updated based on age.
        Returns True if cache is older than max_age_minutes or has never been updated.
        """
        if not self.cached_storage_last_updated:
            return True
        
        age = timezone.now() - self.cached_storage_last_updated
        return age.total_seconds() > (max_age_minutes * 60)


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
        validators=[MinValueValidator(1), MaxValueValidator(65535)],
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


# ============================================================================
# DICOM Query/Retrieve Models
# ============================================================================

class RemoteDicomNode(models.Model):
    """
    Unified model representing a remote DICOM node (PACS, modality, or other SCP).
    Handles both incoming connections (who can send to us) and outgoing Query/Retrieve operations.
    """
    
    # Identification
    name = models.CharField(
        max_length=100,
        unique=True,
        help_text="Friendly name for this DICOM node (e.g., 'Main PACS', 'CT Scanner 1')"
    )
    
    # Network Information
    host = models.CharField(
        max_length=255,
        blank=True,
        help_text="Hostname or IP address of the remote DICOM node (required for outgoing operations)"
    )
    port = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(65535)],
        blank=True,
        null=True,
        help_text="Port number for DICOM communication (required for outgoing operations)"
    )
    
    # Incoming Connection Settings (replaces AllowedAETitle functionality)
    allow_incoming = models.BooleanField(
        default=False,
        help_text="Allow this node to send DICOM files to our server (C-STORE)"
    )
    incoming_ae_title = models.CharField(
        max_length=16,
        blank=True,
        validators=[
            RegexValidator(
                regex=r'^[A-Z0-9_\-]+$',
                message='AE Title must contain only uppercase letters, numbers, underscores, and hyphens.',
                code='invalid_ae_title'
            )
        ],
        help_text="AE Title used when this node sends files to us (required if allow_incoming is True)"
    )
    expected_ip = models.GenericIPAddressField(
        blank=True,
        null=True,
        help_text="Expected IP address for incoming connections (optional, for documentation/validation)"
    )
    last_incoming_connection = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last time this node successfully sent files to us"
    )
    
    # Outgoing Query/Retrieve Capabilities
    supports_c_find = models.BooleanField(
        default=False,
        help_text="Remote node supports C-FIND (query) operations"
    )
    supports_c_move = models.BooleanField(
        default=False,
        help_text="Remote node supports C-MOVE (retrieve) operations"
    )
    supports_c_get = models.BooleanField(
        default=False,
        help_text="Remote node supports C-GET (retrieve) operations"
    )
    outgoing_ae_title = models.CharField(
        max_length=16,
        blank=True,
        validators=[
            RegexValidator(
                regex=r'^[A-Z0-9_\-]+$',
                message='AE Title must contain only uppercase letters, numbers, underscores, and hyphens.',
                code='invalid_ae_title'
            )
        ],
        help_text="AE Title used for Query/Retrieve operations (required if any Q/R capability is enabled)"
    )
    
    # Query/Retrieve Models
    QUERY_RETRIEVE_MODELS = [
        ('patient', 'Patient Root Query/Retrieve'),
        ('study', 'Study Root Query/Retrieve'),
        ('patient_study', 'Patient/Study Only Query/Retrieve'),
    ]
    query_retrieve_model = models.CharField(
        max_length=20,
        choices=QUERY_RETRIEVE_MODELS,
        default='study',
        blank=True,
        help_text="Query/Retrieve Information Model supported by this node"
    )
    
    # Connection Settings
    timeout = models.IntegerField(
        default=30,
        validators=[MinValueValidator(5), MaxValueValidator(300)],
        help_text="Connection timeout in seconds"
    )
    max_pdu_size = models.IntegerField(
        default=16384,
        validators=[MinValueValidator(4096), MaxValueValidator(131072)],
        help_text="Maximum PDU size in bytes (default: 16384)"
    )
    
    # Move Destination (for C-MOVE)
    move_destination_ae = models.CharField(
        max_length=16,
        blank=True,
        help_text="AE Title to use as move destination (usually our local AE title)"
    )
    
    # Status
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this node is active"
    )
    
    # Metadata
    description = models.TextField(
        blank=True,
        help_text="Optional description or notes about this DICOM node"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_successful_connection = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last time a successful outgoing connection was made to this node"
    )
    
    class Meta:
        ordering = ['name']
        verbose_name = "Remote DICOM Node"
        verbose_name_plural = "Remote DICOM Nodes"
    
    def __str__(self):
        ae_display = []
        if self.incoming_ae_title:
            ae_display.append(f"IN:{self.incoming_ae_title}")
        if self.outgoing_ae_title:
            ae_display.append(f"OUT:{self.outgoing_ae_title}")
        ae_str = "/".join(ae_display) if ae_display else "No AE"
        return f"{self.name} ({ae_str}@{self.host}:{self.port})"
    
    def save(self, *args, **kwargs):
        """
        Save the RemoteDicomNode and sync with DestinationAETitle for C-MOVE operations.
        """
        super().save(*args, **kwargs)
        
        # If this node has an outgoing AE title and host/port configured,
        # create/update a DestinationAETitle entry for C-MOVE operations
        if self.outgoing_ae_title and self.host and self.port:
            DestinationAETitle.objects.update_or_create(
                ae_title=self.outgoing_ae_title,
                defaults={
                    'host': self.host,
                    'port': self.port,
                    'description': f"Auto-synced from Remote Node: {self.name}",
                    'is_active': self.is_active and self.supports_c_move
                }
            )
    
    @property
    def node_type(self):
        """Return the type of node based on configuration."""
        incoming = self.allow_incoming
        outgoing = any([self.supports_c_find, self.supports_c_move, self.supports_c_get])
        
        if incoming and outgoing:
            return "bidirectional"
        elif incoming:
            return "incoming"
        elif outgoing:
            return "outgoing"
        else:
            return "unconfigured"
    
    @property
    def capabilities_summary(self):
        """Return a summary of node capabilities."""
        caps = []
        if self.allow_incoming:
            caps.append("C-STORE (receive)")
        if self.supports_c_find:
            caps.append("C-FIND")
        if self.supports_c_move:
            caps.append("C-MOVE")
        if self.supports_c_get:
            caps.append("C-GET")
        return ", ".join(caps) if caps else "No capabilities configured"
    
    def update_last_connection(self):
        """Update the last successful outgoing connection timestamp."""
        self.last_successful_connection = timezone.now()
        self.save(update_fields=['last_successful_connection'])
    
    def update_last_incoming_connection(self):
        """Update the last successful incoming connection timestamp."""
        self.last_incoming_connection = timezone.now()
        self.save(update_fields=['last_incoming_connection'])


class DicomQuery(models.Model):
    """
    Model to track DICOM query operations (C-FIND).
    Stores query parameters and results.
    """
    
    QUERY_LEVELS = [
        ('PATIENT', 'Patient Level'),
        ('STUDY', 'Study Level'),
        ('SERIES', 'Series Level'),
        ('IMAGE', 'Image Level'),
    ]
    
    QUERY_STATUSES = [
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]
    
    # Query Identification
    query_id = models.UUIDField(
        unique=True,
        editable=False,
        help_text="Unique identifier for this query"
    )
    remote_node = models.ForeignKey(
        RemoteDicomNode,
        on_delete=models.CASCADE,
        related_name='queries',
        help_text="Remote DICOM node that was queried"
    )
    
    # Query Parameters
    query_level = models.CharField(
        max_length=10,
        choices=QUERY_LEVELS,
        help_text="DICOM query level (Patient, Study, Series, or Image)"
    )
    query_parameters = models.JSONField(
        default=dict,
        help_text="Query parameters as JSON (e.g., PatientID, StudyDate, etc.)"
    )
    
    # Query Execution
    initiated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='dicom_queries',
        help_text="User who initiated this query"
    )
    initiated_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    # Query Results
    status = models.CharField(
        max_length=20,
        choices=QUERY_STATUSES,
        default='pending',
        help_text="Current status of the query"
    )
    results_count = models.IntegerField(
        default=0,
        help_text="Number of results returned by the query"
    )
    error_message = models.TextField(
        blank=True,
        help_text="Error message if query failed"
    )
    
    # Performance
    duration_seconds = models.FloatField(
        null=True,
        blank=True,
        help_text="Query execution time in seconds"
    )
    
    class Meta:
        ordering = ['-initiated_at']
        verbose_name = "DICOM Query"
        verbose_name_plural = "DICOM Queries"
        indexes = [
            models.Index(fields=['-initiated_at']),
            models.Index(fields=['status']),
            models.Index(fields=['query_level']),
        ]
    
    def __str__(self):
        return f"Query {self.query_id} - {self.query_level} on {self.remote_node.name}"
    
    def mark_completed(self, results_count, duration=None):
        """Mark query as completed."""
        self.status = 'completed'
        self.results_count = results_count
        self.completed_at = timezone.now()
        if duration:
            self.duration_seconds = duration
        self.save()
    
    def mark_failed(self, error_message):
        """Mark query as failed."""
        self.status = 'failed'
        self.error_message = error_message
        self.completed_at = timezone.now()
        self.save()


class DicomQueryResult(models.Model):
    """
    Model to store individual results from a DICOM query.
    Each result represents one matching entity (patient, study, series, or image).
    """
    
    query = models.ForeignKey(
        DicomQuery,
        on_delete=models.CASCADE,
        related_name='results',
        help_text="Query that returned this result"
    )
    
    # Result Data
    result_data = models.JSONField(
        help_text="Complete DICOM dataset returned as JSON"
    )
    
    # Common DICOM Tags (for quick filtering/searching)
    patient_id = models.CharField(max_length=64, blank=True, db_index=True)
    patient_name = models.CharField(max_length=255, blank=True)
    study_instance_uid = models.CharField(max_length=64, blank=True, db_index=True)
    study_date = models.DateField(null=True, blank=True)
    study_description = models.CharField(max_length=255, blank=True)
    series_instance_uid = models.CharField(max_length=64, blank=True, db_index=True)
    series_description = models.CharField(max_length=255, blank=True)
    modality = models.CharField(max_length=16, blank=True)
    number_of_instances = models.IntegerField(null=True, blank=True)
    
    # Retrieve Status
    retrieved = models.BooleanField(
        default=False,
        help_text="Whether this result has been retrieved"
    )
    retrieved_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['created_at']
        verbose_name = "DICOM Query Result"
        verbose_name_plural = "DICOM Query Results"
        indexes = [
            models.Index(fields=['patient_id']),
            models.Index(fields=['study_instance_uid']),
            models.Index(fields=['series_instance_uid']),
            models.Index(fields=['study_date']),
            models.Index(fields=['modality']),
        ]
    
    def __str__(self):
        if self.patient_name:
            return f"{self.patient_name} - {self.study_description or 'Study'}"
        return f"Result {self.id}"
    
    def mark_retrieved(self):
        """Mark this result as retrieved."""
        self.retrieved = True
        self.retrieved_at = timezone.now()
        self.save()


class DicomRetrieveJob(models.Model):
    """
    Model to track DICOM retrieve operations (C-MOVE or C-GET).
    Represents a job to retrieve one or more studies/series from a remote node.
    """
    
    RETRIEVE_METHODS = [
        ('C-MOVE', 'C-MOVE'),
        ('C-GET', 'C-GET'),
    ]
    
    RETRIEVE_LEVELS = [
        ('STUDY', 'Study Level'),
        ('SERIES', 'Series Level'),
        ('IMAGE', 'Image Level'),
    ]
    
    JOB_STATUSES = [
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('partial', 'Partially Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]
    
    # Job Identification
    job_id = models.UUIDField(
        unique=True,
        editable=False,
        help_text="Unique identifier for this retrieve job"
    )
    remote_node = models.ForeignKey(
        RemoteDicomNode,
        on_delete=models.CASCADE,
        related_name='retrieve_jobs',
        help_text="Remote DICOM node to retrieve from"
    )
    
    # Retrieve Parameters
    retrieve_method = models.CharField(
        max_length=10,
        choices=RETRIEVE_METHODS,
        help_text="Method used for retrieval (C-MOVE or C-GET)"
    )
    retrieve_level = models.CharField(
        max_length=10,
        choices=RETRIEVE_LEVELS,
        help_text="Level of retrieval (Study, Series, or Image)"
    )
    
    # What to Retrieve
    study_instance_uid = models.CharField(
        max_length=64,
        help_text="Study Instance UID to retrieve"
    )
    series_instance_uid = models.CharField(
        max_length=64,
        blank=True,
        help_text="Series Instance UID to retrieve (if series-level)"
    )
    sop_instance_uid = models.CharField(
        max_length=64,
        blank=True,
        help_text="SOP Instance UID to retrieve (if image-level)"
    )
    
    # Associated Query Result
    query_result = models.ForeignKey(
        DicomQueryResult,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='retrieve_jobs',
        help_text="Query result that initiated this retrieve"
    )
    
    # Job Execution
    initiated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='dicom_retrieve_jobs',
        help_text="User who initiated this retrieve job"
    )
    initiated_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    # Job Status
    status = models.CharField(
        max_length=20,
        choices=JOB_STATUSES,
        default='pending',
        help_text="Current status of the retrieve job"
    )
    
    # Progress Tracking
    total_instances = models.IntegerField(
        default=0,
        help_text="Total number of instances to retrieve"
    )
    completed_instances = models.IntegerField(
        default=0,
        help_text="Number of instances successfully retrieved"
    )
    failed_instances = models.IntegerField(
        default=0,
        help_text="Number of instances that failed to retrieve"
    )
    
    # Error Handling
    error_message = models.TextField(
        blank=True,
        help_text="Error message if retrieve failed"
    )
    
    # Performance
    duration_seconds = models.FloatField(
        null=True,
        blank=True,
        help_text="Total retrieve time in seconds"
    )
    transfer_speed_mbps = models.FloatField(
        null=True,
        blank=True,
        help_text="Average transfer speed in MB/s"
    )
    
    # Storage
    destination_path = models.CharField(
        max_length=500,
        blank=True,
        help_text="Local path where retrieved files are stored"
    )
    
    class Meta:
        ordering = ['-initiated_at']
        verbose_name = "DICOM Retrieve Job"
        verbose_name_plural = "DICOM Retrieve Jobs"
        indexes = [
            models.Index(fields=['-initiated_at']),
            models.Index(fields=['status']),
            models.Index(fields=['study_instance_uid']),
        ]
    
    def __str__(self):
        return f"Retrieve Job {self.job_id} - {self.retrieve_method} from {self.remote_node.name}"
    
    @property
    def progress_percent(self):
        """Calculate progress percentage."""
        if self.total_instances == 0:
            return 0
        return round((self.completed_instances / self.total_instances) * 100, 1)
    
    def mark_started(self, total_instances=0):
        """Mark job as started."""
        self.status = 'in_progress'
        self.started_at = timezone.now()
        if total_instances:
            self.total_instances = total_instances
        self.save()
    
    def update_progress(self, completed=0, failed=0):
        """Update job progress."""
        if completed:
            self.completed_instances += completed
        if failed:
            self.failed_instances += failed
        self.save()
    
    def mark_completed(self, duration=None):
        """Mark job as completed."""
        if self.failed_instances > 0 and self.completed_instances < self.total_instances:
            self.status = 'partial'
        else:
            self.status = 'completed'
        
        self.completed_at = timezone.now()
        if duration:
            self.duration_seconds = duration
        self.save()
        
        # Mark associated query result as retrieved
        if self.query_result:
            self.query_result.mark_retrieved()
    
    def mark_failed(self, error_message):
        """Mark job as failed."""
        self.status = 'failed'
        self.error_message = error_message
        self.completed_at = timezone.now()
        self.save()