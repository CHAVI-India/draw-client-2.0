from django import forms
from .models import DicomServerConfig


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
