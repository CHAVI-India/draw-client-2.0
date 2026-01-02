from django import forms
from .models import DicomServerConfig, AllowedAETitle


class DicomServerConfigForm(forms.ModelForm):
    """
    Form for DICOM server configuration.
    """
    class Meta:
        model = DicomServerConfig
        exclude = ['id', 'created_at', 'updated_at', 'last_service_start', 'last_service_stop']
        widgets = {
            'allowed_ip_addresses': forms.Textarea(attrs={'rows': 3}),
        }


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
