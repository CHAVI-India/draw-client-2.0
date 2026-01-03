from django import forms
from .models import DicomServerConfig, AllowedAETitle


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
            'notify_on_receive',
            'notify_on_error',
            'notification_email',
            'validate_dicom_on_receive',
            'reject_invalid_dicom',
        ]
        widgets = {
            'allowed_ip_addresses': forms.Textarea(attrs={'rows': 3}),
        }
    
    def clean_ae_title(self):
        """Clean and normalize AE Title: strip whitespace and convert to uppercase."""
        ae_title = self.cleaned_data.get('ae_title', '')
        if ae_title:
            ae_title = ae_title.strip().upper()
        return ae_title


class AllowedAETitleForm(forms.ModelForm):
    """
    Form for adding/editing allowed AE titles.
    """
    class Meta:
        model = AllowedAETitle
        fields = ['ae_title', 'description', 'ip_address', 'is_active']
        widgets = {
            'ae_title': forms.TextInput(attrs={'class': 'uppercase'}),
        }
    
    def clean_ae_title(self):
        """Clean and normalize AE Title: strip whitespace and convert to uppercase."""
        ae_title = self.cleaned_data.get('ae_title', '')
        if ae_title:
            ae_title = ae_title.strip().upper()
        return ae_title
