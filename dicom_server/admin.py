from django.contrib import admin
from .models import (
    DicomServerConfig, 
    AllowedAETitle, 
    DicomTransaction, 
    DicomServiceStatus, 
    DestinationAETitle,
    RemoteDicomNode,
    DicomQuery,
    DicomQueryResult,
    DicomRetrieveJob
)


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


# ============================================================================
# Query/Retrieve Admin
# ============================================================================

@admin.register(RemoteDicomNode)
class RemoteDicomNodeAdmin(admin.ModelAdmin):
    list_display = ('name', 'ae_title', 'host', 'port', 'is_active', 'supports_c_find', 
                   'supports_c_move', 'supports_c_get', 'last_successful_connection')
    list_filter = ('is_active', 'supports_c_find', 'supports_c_move', 'supports_c_get', 
                   'query_retrieve_model')
    search_fields = ('name', 'ae_title', 'host', 'description')
    readonly_fields = ('created_at', 'updated_at', 'last_successful_connection')
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'ae_title', 'host', 'port', 'description')
        }),
        ('Capabilities', {
            'fields': ('supports_c_find', 'supports_c_move', 'supports_c_get', 'query_retrieve_model')
        }),
        ('Connection Settings', {
            'fields': ('timeout', 'max_pdu_size', 'move_destination_ae')
        }),
        ('Status', {
            'fields': ('is_active', 'last_successful_connection')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(DicomQuery)
class DicomQueryAdmin(admin.ModelAdmin):
    list_display = ('query_id', 'remote_node', 'query_level', 'status', 'results_count', 
                   'initiated_by', 'initiated_at', 'duration_seconds')
    list_filter = ('status', 'query_level', 'remote_node', 'initiated_at')
    search_fields = ('query_id', 'remote_node__name')
    readonly_fields = ('query_id', 'initiated_at', 'completed_at', 'duration_seconds')
    date_hierarchy = 'initiated_at'
    
    fieldsets = (
        ('Query Information', {
            'fields': ('query_id', 'remote_node', 'query_level', 'status')
        }),
        ('Query Parameters', {
            'fields': ('query_parameters',)
        }),
        ('Execution', {
            'fields': ('initiated_by', 'initiated_at', 'completed_at', 'duration_seconds')
        }),
        ('Results', {
            'fields': ('results_count', 'error_message')
        }),
    )
    
    def has_add_permission(self, request):
        return False


@admin.register(DicomQueryResult)
class DicomQueryResultAdmin(admin.ModelAdmin):
    list_display = ('id', 'query', 'patient_name', 'patient_id', 'study_date', 
                   'modality', 'retrieved', 'created_at')
    list_filter = ('retrieved', 'modality', 'study_date', 'created_at')
    search_fields = ('patient_id', 'patient_name', 'study_instance_uid', 
                    'series_instance_uid', 'study_description')
    readonly_fields = ('created_at', 'retrieved_at')
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Query', {
            'fields': ('query',)
        }),
        ('Patient Information', {
            'fields': ('patient_id', 'patient_name')
        }),
        ('Study Information', {
            'fields': ('study_instance_uid', 'study_date', 'study_description', 'modality')
        }),
        ('Series Information', {
            'fields': ('series_instance_uid', 'series_description', 'number_of_instances')
        }),
        ('Retrieve Status', {
            'fields': ('retrieved', 'retrieved_at')
        }),
        ('Raw Data', {
            'fields': ('result_data',),
            'classes': ('collapse',)
        }),
    )
    
    def has_add_permission(self, request):
        return False


@admin.register(DicomRetrieveJob)
class DicomRetrieveJobAdmin(admin.ModelAdmin):
    list_display = ('job_id', 'remote_node', 'retrieve_method', 'retrieve_level', 
                   'status', 'progress_percent', 'initiated_by', 'initiated_at')
    list_filter = ('status', 'retrieve_method', 'retrieve_level', 'remote_node', 'initiated_at')
    search_fields = ('job_id', 'study_instance_uid', 'series_instance_uid')
    readonly_fields = ('job_id', 'initiated_at', 'started_at', 'completed_at', 
                      'duration_seconds', 'progress_percent')
    date_hierarchy = 'initiated_at'
    
    fieldsets = (
        ('Job Information', {
            'fields': ('job_id', 'remote_node', 'retrieve_method', 'retrieve_level', 'status')
        }),
        ('What to Retrieve', {
            'fields': ('study_instance_uid', 'series_instance_uid', 'sop_instance_uid')
        }),
        ('Execution', {
            'fields': ('initiated_by', 'initiated_at', 'started_at', 'completed_at', 'duration_seconds')
        }),
        ('Progress', {
            'fields': ('total_instances', 'completed_instances', 'failed_instances', 'progress_percent')
        }),
        ('Storage', {
            'fields': ('destination_path',)
        }),
        ('Error Information', {
            'fields': ('error_message',),
            'classes': ('collapse',)
        }),
        ('Performance', {
            'fields': ('transfer_speed_mbps',),
            'classes': ('collapse',)
        }),
    )
    
    def has_add_permission(self, request):
        return False
