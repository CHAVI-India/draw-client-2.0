from django import forms
from .models import DicomServerConfig, RemoteDicomNode


class DicomServerConfigForm(forms.ModelForm):
    """
    Form for DICOM server configuration.
    """
    class Meta:
        model = DicomServerConfig
        fields = [
            'auto_start',
            'ae_title',
            'host',
            'port',
            'max_associations',
            'max_pdu_size',
            'network_timeout',
            'acse_timeout',
            'dimse_timeout',
            'storage_structure',
            'file_naming_convention',
            'max_storage_size_gb',
            'enable_storage_cleanup',
            'storage_retention_days',
            'require_calling_ae_validation',
            'require_ip_validation',
            'allowed_ip_addresses',
            'support_ct_image_storage',
            'support_mr_image_storage',
            'support_rt_structure_storage',
            'support_rt_plan_storage',
            'support_rt_dose_storage',
            'support_secondary_capture',
            'enable_c_echo',
            'enable_c_store',
            'enable_c_find',
            'enable_c_move',
            'enable_c_get',
            'max_query_results',
            'support_implicit_vr_little_endian',
            'support_explicit_vr_little_endian',
            'support_explicit_vr_big_endian',
            'support_jpeg_baseline',
            'support_jpeg_lossless',
            'support_jpeg2000_lossless',
            'support_rle_lossless',
            'logging_level',
            'log_connection_attempts',
            'log_received_files',
            'enable_performance_metrics',
            'validate_dicom_on_receive',
            'reject_invalid_dicom',
        ]
        widgets = {
            'ae_title': forms.TextInput(attrs={'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent'}),
            'host': forms.TextInput(attrs={'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent'}),
            'port': forms.NumberInput(attrs={'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent'}),
            'max_associations': forms.NumberInput(attrs={'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent'}),
            'max_pdu_size': forms.NumberInput(attrs={'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent'}),
            'network_timeout': forms.NumberInput(attrs={'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent'}),
            'acse_timeout': forms.NumberInput(attrs={'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent'}),
            'dimse_timeout': forms.NumberInput(attrs={'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent'}),
            'storage_structure': forms.Select(attrs={'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent'}),
            'file_naming_convention': forms.Select(attrs={'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent'}),
            'max_storage_size_gb': forms.NumberInput(attrs={'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent'}),
            'storage_retention_days': forms.NumberInput(attrs={'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent'}),
            'allowed_ip_addresses': forms.Textarea(attrs={'rows': 3, 'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent'}),
            'logging_level': forms.Select(attrs={'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent'}),
            'auto_start': forms.CheckboxInput(attrs={'class': 'w-5 h-5 text-blue-600 border-gray-300 rounded focus:ring-blue-500'}),
            'enable_storage_cleanup': forms.CheckboxInput(attrs={'class': 'w-5 h-5 text-blue-600 border-gray-300 rounded focus:ring-blue-500'}),
            'require_calling_ae_validation': forms.CheckboxInput(attrs={'class': 'w-5 h-5 text-blue-600 border-gray-300 rounded focus:ring-blue-500'}),
            'require_ip_validation': forms.CheckboxInput(attrs={'class': 'w-5 h-5 text-blue-600 border-gray-300 rounded focus:ring-blue-500'}),
            'support_ct_image_storage': forms.CheckboxInput(attrs={'class': 'w-5 h-5 text-blue-600 border-gray-300 rounded focus:ring-blue-500'}),
            'support_mr_image_storage': forms.CheckboxInput(attrs={'class': 'w-5 h-5 text-blue-600 border-gray-300 rounded focus:ring-blue-500'}),
            'support_rt_structure_storage': forms.CheckboxInput(attrs={'class': 'w-5 h-5 text-blue-600 border-gray-300 rounded focus:ring-blue-500'}),
            'support_rt_plan_storage': forms.CheckboxInput(attrs={'class': 'w-5 h-5 text-blue-600 border-gray-300 rounded focus:ring-blue-500'}),
            'support_rt_dose_storage': forms.CheckboxInput(attrs={'class': 'w-5 h-5 text-blue-600 border-gray-300 rounded focus:ring-blue-500'}),
            'support_secondary_capture': forms.CheckboxInput(attrs={'class': 'w-5 h-5 text-blue-600 border-gray-300 rounded focus:ring-blue-500'}),
            'enable_c_echo': forms.CheckboxInput(attrs={'class': 'w-5 h-5 text-blue-600 border-gray-300 rounded focus:ring-blue-500'}),
            'enable_c_store': forms.CheckboxInput(attrs={'class': 'w-5 h-5 text-blue-600 border-gray-300 rounded focus:ring-blue-500'}),
            'enable_c_find': forms.CheckboxInput(attrs={'class': 'w-5 h-5 text-blue-600 border-gray-300 rounded focus:ring-blue-500'}),
            'enable_c_move': forms.CheckboxInput(attrs={'class': 'w-5 h-5 text-blue-600 border-gray-300 rounded focus:ring-blue-500'}),
            'enable_c_get': forms.CheckboxInput(attrs={'class': 'w-5 h-5 text-blue-600 border-gray-300 rounded focus:ring-blue-500'}),
            'max_query_results': forms.NumberInput(attrs={'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent'}),
            'support_implicit_vr_little_endian': forms.CheckboxInput(attrs={'class': 'w-5 h-5 text-blue-600 border-gray-300 rounded focus:ring-blue-500'}),
            'support_explicit_vr_little_endian': forms.CheckboxInput(attrs={'class': 'w-5 h-5 text-blue-600 border-gray-300 rounded focus:ring-blue-500'}),
            'support_explicit_vr_big_endian': forms.CheckboxInput(attrs={'class': 'w-5 h-5 text-blue-600 border-gray-300 rounded focus:ring-blue-500'}),
            'support_jpeg_baseline': forms.CheckboxInput(attrs={'class': 'w-5 h-5 text-blue-600 border-gray-300 rounded focus:ring-blue-500'}),
            'support_jpeg_lossless': forms.CheckboxInput(attrs={'class': 'w-5 h-5 text-blue-600 border-gray-300 rounded focus:ring-blue-500'}),
            'support_jpeg2000_lossless': forms.CheckboxInput(attrs={'class': 'w-5 h-5 text-blue-600 border-gray-300 rounded focus:ring-blue-500'}),
            'support_rle_lossless': forms.CheckboxInput(attrs={'class': 'w-5 h-5 text-blue-600 border-gray-300 rounded focus:ring-blue-500'}),
            'log_connection_attempts': forms.CheckboxInput(attrs={'class': 'w-5 h-5 text-blue-600 border-gray-300 rounded focus:ring-blue-500'}),
            'log_received_files': forms.CheckboxInput(attrs={'class': 'w-5 h-5 text-blue-600 border-gray-300 rounded focus:ring-blue-500'}),
            'enable_performance_metrics': forms.CheckboxInput(attrs={'class': 'w-5 h-5 text-blue-600 border-gray-300 rounded focus:ring-blue-500'}),
            'validate_dicom_on_receive': forms.CheckboxInput(attrs={'class': 'w-5 h-5 text-blue-600 border-gray-300 rounded focus:ring-blue-500'}),
            'reject_invalid_dicom': forms.CheckboxInput(attrs={'class': 'w-5 h-5 text-blue-600 border-gray-300 rounded focus:ring-blue-500'}),
        }
    
    def clean_ae_title(self):
        """Clean and normalize AE Title: strip whitespace and convert to uppercase."""
        ae_title = self.cleaned_data.get('ae_title', '')
        if ae_title:
            ae_title = ae_title.strip().upper()
        return ae_title


class RemoteDicomNodeForm(forms.ModelForm):
    """
    Form for Remote DICOM Node configuration with export destination support.
    """
    class Meta:
        model = RemoteDicomNode
        fields = [
            'name',
            'host',
            'port',
            'description',
            'allow_incoming',
            'incoming_ae_title',
            'expected_ip',
            'supports_c_find',
            'supports_c_move',
            'supports_c_get',
            'outgoing_ae_title',
            'query_retrieve_model',
            'timeout',
            'max_pdu_size',
            'move_destination_ae',
            'is_export_destination',
            'is_primary_export_destination',
            'is_fallback_export_destination',
            'fallback_export_destination_priority',
            'is_active',
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent',
                'placeholder': 'e.g., Main PACS Server'
            }),
            'host': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent',
                'placeholder': 'e.g., 192.168.1.100 or pacs.example.com'
            }),
            'port': forms.NumberInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent',
                'placeholder': '11112'
            }),
            'description': forms.Textarea(attrs={
                'rows': 3,
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent',
                'placeholder': 'Optional description or notes about this DICOM node'
            }),
            'incoming_ae_title': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent',
                'placeholder': 'REMOTE_AE'
            }),
            'outgoing_ae_title': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent',
                'placeholder': 'REMOTE_AE'
            }),
            'expected_ip': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent',
                'placeholder': '192.168.1.100'
            }),
            'query_retrieve_model': forms.Select(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent'
            }),
            'timeout': forms.NumberInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent',
                'placeholder': '30'
            }),
            'max_pdu_size': forms.NumberInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent',
                'placeholder': '16384'
            }),
            'move_destination_ae': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent',
                'placeholder': 'Leave empty to use default'
            }),
            'fallback_export_destination_priority': forms.NumberInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent',
                'placeholder': '1 (lower = higher priority)',
                'min': '1'
            }),
            'allow_incoming': forms.CheckboxInput(attrs={
                'class': 'w-5 h-5 text-blue-600 border-gray-300 rounded focus:ring-blue-500'
            }),
            'supports_c_find': forms.CheckboxInput(attrs={
                'class': 'w-5 h-5 text-blue-600 border-gray-300 rounded focus:ring-blue-500'
            }),
            'supports_c_move': forms.CheckboxInput(attrs={
                'class': 'w-5 h-5 text-blue-600 border-gray-300 rounded focus:ring-blue-500'
            }),
            'supports_c_get': forms.CheckboxInput(attrs={
                'class': 'w-5 h-5 text-blue-600 border-gray-300 rounded focus:ring-blue-500'
            }),
            'is_export_destination': forms.CheckboxInput(attrs={
                'class': 'w-5 h-5 text-blue-600 border-gray-300 rounded focus:ring-blue-500'
            }),
            'is_primary_export_destination': forms.CheckboxInput(attrs={
                'class': 'w-5 h-5 text-blue-600 border-gray-300 rounded focus:ring-blue-500'
            }),
            'is_fallback_export_destination': forms.CheckboxInput(attrs={
                'class': 'w-5 h-5 text-blue-600 border-gray-300 rounded focus:ring-blue-500'
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'w-5 h-5 text-blue-600 border-gray-300 rounded focus:ring-blue-500'
            }),
        }
        help_texts = {
            'is_primary_export_destination': 'Mark this node as the primary export destination for RT Structure files.',
            'is_fallback_export_destination': 'Mark this node as a fallback export destination. A primary destination must be configured first.',
            'fallback_export_destination_priority': 'Priority for fallback destinations (1 = highest priority, 2 = second, etc.). Required for fallback destinations.',
            'timeout': 'Connection timeout in seconds. Lower values enable faster failover for fallback destinations.',
        }
    
    def clean_incoming_ae_title(self):
        """Clean and normalize incoming AE Title."""
        ae_title = self.cleaned_data.get('incoming_ae_title', '')
        if ae_title:
            ae_title = ae_title.strip().upper()
        return ae_title
    
    def clean_outgoing_ae_title(self):
        """Clean and normalize outgoing AE Title."""
        ae_title = self.cleaned_data.get('outgoing_ae_title', '')
        if ae_title:
            ae_title = ae_title.strip().upper()
        return ae_title
