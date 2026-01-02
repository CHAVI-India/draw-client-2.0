from django.contrib import admin
from .models import DicomServerConfig, AllowedAETitle, DicomTransaction, DicomServiceStatus, DestinationAETitle


@admin.register(DicomServerConfig)
class DicomServerConfigAdmin(admin.ModelAdmin):
    fieldsets = (
        ('Service Status', {
            'fields': ('service_enabled', 'auto_start')
        }),
        ('Network Configuration', {
            'fields': ('ae_title', 'host', 'port', 'max_associations', 'max_pdu_size')
        }),
        ('Timeout Settings', {
            'fields': ('network_timeout', 'acse_timeout', 'dimse_timeout'),
            'classes': ('collapse',)
        }),
        ('Storage Configuration', {
            'fields': ('storage_structure', 'file_naming_convention',
                      'max_storage_size_gb', 'enable_storage_cleanup', 'storage_retention_days'),
            'description': 'Storage path is automatically set from System Configuration.'
        }),
        ('Security & Access Control', {
            'fields': ('require_calling_ae_validation', 'require_ip_validation', 'allowed_ip_addresses')
        }),
        ('Supported SOP Classes', {
            'fields': ('support_ct_image_storage', 'support_mr_image_storage', 
                      'support_rt_structure_storage', 'support_rt_plan_storage',
                      'support_rt_dose_storage', 'support_secondary_capture'),
            'classes': ('collapse',)
        }),
        ('DIMSE Services', {
            'fields': ('enable_c_echo', 'enable_c_store', 'enable_c_find', 'enable_c_move', 'enable_c_get')
        }),
        ('Transfer Syntax Support', {
            'fields': ('support_implicit_vr_little_endian', 'support_explicit_vr_little_endian',
                      'support_explicit_vr_big_endian', 'support_jpeg_baseline',
                      'support_jpeg_lossless', 'support_jpeg2000_lossless', 'support_rle_lossless'),
            'classes': ('collapse',)
        }),
        ('Logging & Monitoring', {
            'fields': ('logging_level', 'log_connection_attempts', 'log_received_files', 'enable_performance_metrics')
        }),
        ('Notifications', {
            'fields': ('notify_on_receive', 'notify_on_error', 'notification_email'),
            'classes': ('collapse',)
        }),
        ('Validation Settings', {
            'fields': ('validate_dicom_on_receive', 'reject_invalid_dicom'),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at', 'last_service_start', 'last_service_stop'),
            'classes': ('collapse',)
        }),
    )
    
    readonly_fields = ('created_at', 'updated_at', 'last_service_start', 'last_service_stop')
    
    def has_add_permission(self, request):
        # Singleton - only one instance allowed
        return not DicomServerConfig.objects.exists()
    
    def has_delete_permission(self, request, obj=None):
        # Prevent deletion of singleton
        return False


@admin.register(AllowedAETitle)
class AllowedAETitleAdmin(admin.ModelAdmin):
    list_display = ('ae_title', 'description', 'ip_address', 'is_active', 'last_connection', 'created_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('ae_title', 'description', 'ip_address')
    readonly_fields = ('created_at', 'updated_at', 'last_connection')
    
    fieldsets = (
        (None, {
            'fields': ('ae_title', 'description', 'ip_address', 'is_active')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'last_connection'),
            'classes': ('collapse',)
        }),
    )


@admin.register(DicomTransaction)
class DicomTransactionAdmin(admin.ModelAdmin):
    list_display = ('transaction_id', 'transaction_type', 'status', 'calling_ae_title', 
                   'remote_ip', 'patient_id', 'timestamp')
    list_filter = ('transaction_type', 'status', 'timestamp', 'calling_ae_title')
    search_fields = ('calling_ae_title', 'patient_id', 'study_instance_uid', 
                    'series_instance_uid', 'sop_instance_uid', 'remote_ip')
    readonly_fields = ('transaction_id', 'timestamp')
    date_hierarchy = 'timestamp'
    
    fieldsets = (
        ('Transaction Information', {
            'fields': ('transaction_id', 'transaction_type', 'status', 'timestamp')
        }),
        ('Connection Details', {
            'fields': ('calling_ae_title', 'called_ae_title', 'remote_ip', 'remote_port')
        }),
        ('DICOM Data', {
            'fields': ('patient_id', 'study_instance_uid', 'series_instance_uid', 
                      'sop_instance_uid', 'sop_class_uid'),
            'classes': ('collapse',)
        }),
        ('File Information', {
            'fields': ('file_path', 'file_size_bytes', 'transfer_syntax'),
            'classes': ('collapse',)
        }),
        ('Performance Metrics', {
            'fields': ('duration_seconds', 'transfer_speed_mbps'),
            'classes': ('collapse',)
        }),
        ('Error Information', {
            'fields': ('error_message',),
            'classes': ('collapse',)
        }),
    )
    
    def has_add_permission(self, request):
        # Transactions are created programmatically
        return False


@admin.register(DestinationAETitle)
class DestinationAETitleAdmin(admin.ModelAdmin):
    list_display = ('ae_title', 'description', 'host', 'port', 'is_active', 'last_used', 'created_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('ae_title', 'description', 'host')
    readonly_fields = ('created_at', 'updated_at', 'last_used')
    
    fieldsets = (
        (None, {
            'fields': ('ae_title', 'description', 'host', 'port', 'is_active')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'last_used'),
            'classes': ('collapse',)
        }),
    )


@admin.register(DicomServiceStatus)
class DicomServiceStatusAdmin(admin.ModelAdmin):
    readonly_fields = ('is_running', 'process_id', 'service_started_at', 'service_stopped_at',
                      'total_connections', 'active_connections', 'total_files_received',
                      'total_bytes_received', 'total_errors', 'last_connection_at',
                      'last_file_received_at', 'updated_at')
    
    fieldsets = (
        ('Service Status', {
            'fields': ('is_running', 'process_id', 'service_started_at', 'service_stopped_at')
        }),
        ('Statistics', {
            'fields': ('total_connections', 'active_connections', 'total_files_received',
                      'total_bytes_received', 'total_errors')
        }),
        ('Last Activity', {
            'fields': ('last_connection_at', 'last_file_received_at', 'updated_at')
        }),
    )
    
    def has_add_permission(self, request):
        # Singleton - managed programmatically
        return False
    
    def has_delete_permission(self, request, obj=None):
        # Prevent deletion of singleton
        return False
