"""
Forms for DICOM Query/Retrieve functionality.
"""

from django import forms
from .models import RemoteDicomNode


class RemoteDicomNodeForm(forms.ModelForm):
    """Form for creating/editing unified remote DICOM nodes (both incoming and outgoing)."""
    
    class Meta:
        model = RemoteDicomNode
        fields = [
            'name',
            'host',
            'port',
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
            'is_active',
            'description',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent', 'placeholder': 'e.g., Main PACS'}),
            'host': forms.TextInput(attrs={'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent', 'placeholder': 'e.g., 192.168.1.100'}),
            'port': forms.NumberInput(attrs={'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent', 'placeholder': '11112'}),
            'incoming_ae_title': forms.TextInput(attrs={'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent', 'placeholder': 'e.g., CT_SCANNER'}),
            'outgoing_ae_title': forms.TextInput(attrs={'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent', 'placeholder': 'e.g., PACS_QR'}),
            'expected_ip': forms.TextInput(attrs={'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent', 'placeholder': 'e.g., 192.168.1.50 (optional)'}),
            'query_retrieve_model': forms.Select(attrs={'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent'}),
            'timeout': forms.NumberInput(attrs={'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent'}),
            'max_pdu_size': forms.NumberInput(attrs={'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent'}),
            'move_destination_ae': forms.TextInput(attrs={'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent', 'placeholder': 'Leave empty to use local AE title'}),
            'description': forms.Textarea(attrs={'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent', 'rows': 3}),
            'allow_incoming': forms.CheckboxInput(attrs={'class': 'w-5 h-5 text-blue-600 border-gray-300 rounded focus:ring-blue-500'}),
            'supports_c_find': forms.CheckboxInput(attrs={'class': 'w-5 h-5 text-blue-600 border-gray-300 rounded focus:ring-blue-500'}),
            'supports_c_move': forms.CheckboxInput(attrs={'class': 'w-5 h-5 text-blue-600 border-gray-300 rounded focus:ring-blue-500'}),
            'supports_c_get': forms.CheckboxInput(attrs={'class': 'w-5 h-5 text-blue-600 border-gray-300 rounded focus:ring-blue-500'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'w-5 h-5 text-blue-600 border-gray-300 rounded focus:ring-blue-500'}),
        }
    
    def clean_incoming_ae_title(self):
        """Clean and normalize incoming AE Title: strip whitespace and convert to uppercase."""
        ae_title = self.cleaned_data.get('incoming_ae_title', '')
        if ae_title:
            ae_title = ae_title.strip().upper()
        return ae_title
    
    def clean_outgoing_ae_title(self):
        """Clean and normalize outgoing AE Title: strip whitespace and convert to uppercase."""
        ae_title = self.cleaned_data.get('outgoing_ae_title', '')
        if ae_title:
            ae_title = ae_title.strip().upper()
        return ae_title
    
    def clean(self):
        """Validate that at least one capability is configured and required fields are present."""
        cleaned_data = super().clean()
        allow_incoming = cleaned_data.get('allow_incoming')
        supports_c_find = cleaned_data.get('supports_c_find')
        supports_c_move = cleaned_data.get('supports_c_move')
        supports_c_get = cleaned_data.get('supports_c_get')
        
        # At least one capability must be enabled
        if not any([allow_incoming, supports_c_find, supports_c_move, supports_c_get]):
            raise forms.ValidationError(
                "At least one capability must be enabled (incoming connections or Query/Retrieve operations)."
            )
        
        # If incoming is enabled, incoming_ae_title is required
        if allow_incoming and not cleaned_data.get('incoming_ae_title'):
            raise forms.ValidationError("Incoming AE Title is required when allowing incoming connections.")
        
        # If outgoing capabilities are enabled, host, port, and outgoing_ae_title are required
        if any([supports_c_find, supports_c_move, supports_c_get]):
            if not cleaned_data.get('host'):
                raise forms.ValidationError("Host is required for Query/Retrieve operations.")
            if not cleaned_data.get('port'):
                raise forms.ValidationError("Port is required for Query/Retrieve operations.")
            if not cleaned_data.get('outgoing_ae_title'):
                raise forms.ValidationError("Outgoing AE Title is required for Query/Retrieve operations.")
        
        return cleaned_data


class DicomQueryForm(forms.Form):
    """Form for performing DICOM queries."""
    
    QUERY_LEVELS = [
        ('PATIENT', 'Patient Level'),
        ('STUDY', 'Study Level'),
        ('SERIES', 'Series Level'),
    ]
    
    # Query Level
    query_level = forms.ChoiceField(
        choices=QUERY_LEVELS,
        initial='STUDY',
        widget=forms.Select(attrs={'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent', 'id': 'query_level'}),
        help_text="Level at which to perform the query"
    )
    
    # Patient Level Fields
    patient_id = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent',
            'placeholder': 'Patient ID (use * for wildcard)',
        }),
        help_text="Patient ID to search for"
    )
    patient_name = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent',
            'placeholder': 'Patient Name (use * for wildcard)',
        }),
        help_text="Patient name to search for"
    )
    
    # Study Level Fields
    study_date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent',
            'type': 'date',
        }),
        help_text="Study date from"
    )
    study_date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent',
            'type': 'date',
        }),
        help_text="Study date to"
    )
    study_description = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent',
            'placeholder': 'Study Description (use * for wildcard)',
        }),
        help_text="Study description to search for"
    )
    accession_number = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent',
            'placeholder': 'Accession Number',
        }),
        help_text="Accession number to search for"
    )
    modality = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent',
            'placeholder': 'Modality (e.g., CT, MR, CR)',
        }),
        help_text="Modality to search for"
    )
    
    # Series Level Fields
    study_instance_uid = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent',
            'placeholder': 'Study Instance UID',
        }),
        help_text="Study Instance UID (required for series-level queries)"
    )
    series_description = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent',
            'placeholder': 'Series Description (use * for wildcard)',
        }),
        help_text="Series description to search for"
    )
    
    def clean(self):
        """Validate query parameters based on query level."""
        cleaned_data = super().clean()
        query_level = cleaned_data.get('query_level')
        
        # For series-level queries, study UID is required
        if query_level == 'SERIES':
            study_uid = cleaned_data.get('study_instance_uid')
            if not study_uid:
                raise forms.ValidationError(
                    "Study Instance UID is required for series-level queries"
                )
        
        return cleaned_data
    
    def get_query_params(self):
        """Convert form data to DICOM query parameters."""
        params = {}
        
        # Patient fields
        if self.cleaned_data.get('patient_id'):
            params['PatientID'] = self.cleaned_data['patient_id']
        if self.cleaned_data.get('patient_name'):
            params['PatientName'] = self.cleaned_data['patient_name']
        
        # Study fields
        if self.cleaned_data.get('study_date_from') or self.cleaned_data.get('study_date_to'):
            date_from = self.cleaned_data.get('study_date_from')
            date_to = self.cleaned_data.get('study_date_to')
            
            if date_from and date_to:
                params['StudyDate'] = f"{date_from.strftime('%Y%m%d')}-{date_to.strftime('%Y%m%d')}"
            elif date_from:
                params['StudyDate'] = f"{date_from.strftime('%Y%m%d')}-"
            elif date_to:
                params['StudyDate'] = f"-{date_to.strftime('%Y%m%d')}"
        
        if self.cleaned_data.get('study_description'):
            params['StudyDescription'] = self.cleaned_data['study_description']
        if self.cleaned_data.get('accession_number'):
            params['AccessionNumber'] = self.cleaned_data['accession_number']
        if self.cleaned_data.get('modality'):
            params['ModalitiesInStudy'] = self.cleaned_data['modality']
        
        # Series fields
        if self.cleaned_data.get('study_instance_uid'):
            params['StudyInstanceUID'] = self.cleaned_data['study_instance_uid']
        if self.cleaned_data.get('series_description'):
            params['SeriesDescription'] = self.cleaned_data['series_description']
        
        return params
