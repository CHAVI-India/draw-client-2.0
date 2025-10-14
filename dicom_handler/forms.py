from django import forms
from django.forms import inlineformset_factory, modelformset_factory
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Submit, Row, Column, Fieldset, Div, HTML
from .models import (RuleSet, Rule, DICOMTagType, AutosegmentationTemplate, RuleCombinationType, 
                     OperatorType, SystemConfiguration, RTStructureFileImport, RTStructureFileVOIData,
                     ContourModificationChoices, ContourModificationTypeChoices)
import uuid

class TemplateCreationForm(forms.Form):
    template_name = forms.CharField(
        max_length=256,
        widget=forms.TextInput(attrs={
            'class': 'w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500',
            'placeholder': 'Enter template name'
        }),
        label='Template Name'
    )
    
    template_description = forms.CharField(
        max_length=256,
        widget=forms.Textarea(attrs={
            'class': 'w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500',
            'placeholder': 'Enter template description',
            'rows': 3
        }),
        label='Template Description'
    )

class RuleSetForm(forms.ModelForm):
    class Meta:
        model = RuleSet
        fields = ['ruleset_name', 'rule_combination_type', 'ruleset_description', 'associated_autosegmentation_template']
        widgets = {
            'ruleset_name': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-primary-500 focus:border-primary-500',
                'placeholder': 'Enter ruleset name'
            }),
            'rule_combination_type': forms.Select(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-primary-500 focus:border-primary-500'
            }),
            'ruleset_description': forms.Textarea(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-primary-500 focus:border-primary-500',
                'rows': 3,
                'placeholder': 'Enter ruleset description'
            }),
            'associated_autosegmentation_template': forms.Select(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-primary-500 focus:border-primary-500'
            })
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            Fieldset(
                'RuleSet Information',
                Row(
                    Column('ruleset_name', css_class='form-group col-md-6 mb-0'),
                    Column('rule_combination_type', css_class='form-group col-md-6 mb-0'),
                    css_class='form-row'
                ),
                'ruleset_description',
                'associated_autosegmentation_template',
                css_class='mb-4'
            ),
            Submit('submit', 'Save RuleSet', css_class='btn btn-primary')
        )

class RuleForm(forms.ModelForm):
    class Meta:
        model = Rule
        fields = ['dicom_tag_type', 'operator_type', 'tag_value_to_evaluate']
        widgets = {
            'dicom_tag_type': forms.Select(attrs={
                'class': 'dicom-tag-select w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-primary-500 focus:border-primary-500',
                'data-placeholder': 'Search for DICOM tag...'
            }),
            'operator_type': forms.Select(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-primary-500 focus:border-primary-500',
                'onchange': 'validateOperatorValue(this)'
            }),
            'tag_value_to_evaluate': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-primary-500 focus:border-primary-500',
                'placeholder': 'Enter value to evaluate',
                'oninput': 'validateOperatorValue(this)'
            })
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.disable_csrf = True
        
        # Populate dicom_tag_type choices for Select2
        self.fields['dicom_tag_type'].queryset = DICOMTagType.objects.all()
        self.fields['dicom_tag_type'].empty_label = "Search for DICOM tag..."
        
        # Handle the case where dicom_tag_type might not exist yet
        if self.instance and hasattr(self.instance, 'dicom_tag_type') and self.instance.dicom_tag_type:
            # Set initial value for existing instances
            self.initial['dicom_tag_type'] = self.instance.dicom_tag_type.id
        
        # No layout needed - let the formset helper handle it
        if self.instance and self.instance.pk:
            try:
                if self.instance.dicom_tag_type:
                    self.fields['dicom_tag_type'].widget.attrs['value'] = str(self.instance.dicom_tag_type)
                    self.fields['dicom_tag_type'].widget.attrs['data-tag-id'] = str(self.instance.dicom_tag_type.id)
            except DICOMTagType.DoesNotExist:
                # Handle case where dicom_tag_type relation doesn't exist
                pass

    def clean_dicom_tag_type(self):
        """Custom validation for autocomplete DICOM tag field."""
        dicom_tag_type = self.cleaned_data.get('dicom_tag_type')
        
        # If it's already a DICOMTagType instance, return it
        if isinstance(dicom_tag_type, DICOMTagType):
            return dicom_tag_type
        
        # If it's a string (from autocomplete), try to find the tag by name
        if isinstance(dicom_tag_type, str):
            try:
                # Try to find by exact tag name match
                tag = DICOMTagType.objects.get(tag_name=dicom_tag_type)
                return tag
            except DICOMTagType.DoesNotExist:
                raise forms.ValidationError(f'DICOM tag "{dicom_tag_type}" not found. Please select a valid tag from the suggestions.')
        
        raise forms.ValidationError('Please select a valid DICOM tag.')

    def clean(self):
        from .vr_validators import VRValidator
        cleaned_data = super().clean()
        operator_type = cleaned_data.get('operator_type')
        tag_value = cleaned_data.get('tag_value_to_evaluate')
        dicom_tag_type = cleaned_data.get('dicom_tag_type')
        
        if operator_type and tag_value and dicom_tag_type:
            # Get VR code from the selected DICOM tag
            vr_code = None
            if dicom_tag_type.value_representation:
                vr_code = dicom_tag_type.value_representation
            
            # VR-specific validation
            if vr_code:
                # Validate value format against VR requirements
                is_valid, vr_error = VRValidator.validate_value_for_vr(tag_value, vr_code)
                if not is_valid:
                    raise forms.ValidationError({
                        'tag_value_to_evaluate': f'Value format invalid for {vr_code} VR: {vr_error}'
                    })
                
                # Check operator compatibility with VR
                if not VRValidator.is_operator_compatible(vr_code, operator_type):
                    compatible_ops = VRValidator.get_compatible_operators(vr_code)
                    operator_display = dict(Rule._meta.get_field("operator_type").choices)[operator_type]
                    raise forms.ValidationError({
                        'operator_type': f'Operator "{operator_display}" is not compatible with '
                                       f'{vr_code} VR. Compatible operators: {", ".join(compatible_ops)}'
                    })
            
            # Fallback to original validation if no VR available
            else:
                # Check if value is numeric
                try:
                    float(tag_value)
                    is_numeric = True
                except (ValueError, TypeError):
                    is_numeric = False
                
                # Define string operators that allow string values (contain "STRING" in their name)
                string_operators = [
                    'CASE_SENSITIVE_STRING_CONTAINS',
                    'CASE_INSENSITIVE_STRING_CONTAINS',
                    'CASE_SENSITIVE_STRING_DOES_NOT_CONTAIN',
                    'CASE_INSENSITIVE_STRING_DOES_NOT_CONTAIN',
                    'CASE_SENSITIVE_STRING_EXACT_MATCH',
                    'CASE_INSENSITIVE_STRING_EXACT_MATCH',
                ]
                
                # All operators except string operators require numeric values
                if operator_type not in string_operators and not is_numeric:
                    raise forms.ValidationError({
                        'tag_value_to_evaluate': f'Operator "{dict(Rule._meta.get_field("operator_type").choices)[operator_type]}" can only be used with numeric values. The value "{tag_value}" is not numeric.'
                    })
        
        return cleaned_data

# Create FormSet Helper for Rules following Crispy Forms documentation
class RuleFormSetHelper(FormHelper):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.form_method = 'post'
        self.layout = Layout(
            Row(
                Column('dicom_tag_type', css_class='form-group col-md-4 mb-0'),
                Column('operator_type', css_class='form-group col-md-4 mb-0'),
                Column('tag_value_to_evaluate', css_class='form-group col-md-4 mb-0'),
                css_class='form-row'
            ),
            # VR Guidance placeholder - will be populated by JavaScript
            HTML('<div class="vr-guidance mt-2" style="display: none;"></div>')
        )
        self.render_required_fields = True

# Create inline formset for Rules
RuleFormSet = inlineformset_factory(
    RuleSet, 
    Rule, 
    form=RuleForm,
    fields=['dicom_tag_type', 'operator_type', 'tag_value_to_evaluate'],
    extra=1,  # Show 1 empty form initially
    can_delete=True,
    min_num=1,  # Require at least 1 rule
    validate_min=True
)

class SystemConfigurationForm(forms.ModelForm):
    class Meta:
        model = SystemConfiguration
        fields = [
            'draw_base_url', 'client_id', 'draw_upload_endpoint', 'draw_status_endpoint',
            'draw_download_endpoint', 'draw_notify_endpoint', 'draw_token_refresh_endpoint',
            'draw_bearer_token', 'draw_refresh_token', 'draw_bearer_token_validaty',
            'folder_configuration', 'data_pull_start_datetime'
        ]
        widgets = {
            'draw_base_url': forms.URLInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-primary-500 focus:border-primary-500',
                'placeholder': 'https://draw.chavi.ai'
            }),
            'client_id': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-primary-500 focus:border-primary-500',
                'placeholder': 'Enter client ID from DRAW API server'
            }),
            'draw_upload_endpoint': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-primary-500 focus:border-primary-500',
                'placeholder': '/api/upload/'
            }),
            'draw_status_endpoint': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-primary-500 focus:border-primary-500',
                'placeholder': '/api/upload/{task_id}/status/'
            }),
            'draw_download_endpoint': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-primary-500 focus:border-primary-500',
                'placeholder': '/api/rtstruct/{task_id}/'
            }),
            'draw_notify_endpoint': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-primary-500 focus:border-primary-500',
                'placeholder': '/api/rtstruct/{task_id}/confirm/'
            }),
            'draw_token_refresh_endpoint': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-primary-500 focus:border-primary-500',
                'placeholder': '/api/token/refresh/'
            }),
            'draw_bearer_token': forms.PasswordInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-primary-500 focus:border-primary-500',
                'placeholder': 'Enter bearer token (leave blank to keep existing)'
            }, render_value=False),
            'draw_refresh_token': forms.PasswordInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-primary-500 focus:border-primary-500',
                'placeholder': 'Enter refresh token (leave blank to keep existing)'
            }, render_value=False),
            'draw_bearer_token_validaty': forms.DateTimeInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-primary-500 focus:border-primary-500',
                'type': 'datetime-local'
            }),
            'folder_configuration': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-primary-500 focus:border-primary-500',
                'placeholder': '/path/to/dicom/folder'
            }),
            'data_pull_start_datetime': forms.DateTimeInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-primary-500 focus:border-primary-500',
                'type': 'datetime-local'
            })
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            Fieldset(
                'DRAW API Configuration',
                Row(
                    Column('draw_base_url', css_class='form-group col-md-6 mb-0'),
                    Column('client_id', css_class='form-group col-md-6 mb-0'),
                    css_class='form-row'
                ),
                css_class='mb-4'
            ),
            Fieldset(
                'API Endpoints (Default Values)',
                Row(
                    Column('draw_upload_endpoint', css_class='form-group col-md-6 mb-0'),
                    Column('draw_status_endpoint', css_class='form-group col-md-6 mb-0'),
                    css_class='form-row'
                ),
                Row(
                    Column('draw_download_endpoint', css_class='form-group col-md-6 mb-0'),
                    Column('draw_notify_endpoint', css_class='form-group col-md-6 mb-0'),
                    css_class='form-row'
                ),
                Row(
                    Column('draw_token_refresh_endpoint', css_class='form-group col-md-6 mb-0'),
                    css_class='form-row'
                ),
                css_class='mb-4 collapse-fieldset',
                css_id='endpoints-fieldset'
            ),
            Fieldset(
                'Authentication',
                Row(
                    Column('draw_bearer_token', css_class='form-group col-md-6 mb-0'),
                    Column('draw_refresh_token', css_class='form-group col-md-6 mb-0'),
                    css_class='form-row'
                ),
                'draw_bearer_token_validaty',
                css_class='mb-4'
            ),
            Fieldset(
                'System Configuration',
                'folder_configuration',
                'data_pull_start_datetime',
                css_class='mb-4'
            ),
            Submit('submit', 'Save Configuration', css_class='btn btn-primary')
        )

    def clean_draw_bearer_token(self):
        """Only update bearer token if a new value is provided"""
        token = self.cleaned_data.get('draw_bearer_token')
        if not token and self.instance and self.instance.pk:
            # Keep existing token if no new value provided
            return self.instance.draw_bearer_token
        return token

    def clean_draw_refresh_token(self):
        """Only update refresh token if a new value is provided"""
        token = self.cleaned_data.get('draw_refresh_token')
        if not token and self.instance and self.instance.pk:
            # Keep existing token if no new value provided
            return self.instance.draw_refresh_token
        return token


class RTStructureReviewForm(forms.ModelForm):
    """Form for reviewing RT Structure Set level data"""
    class Meta:
        model = RTStructureFileImport
        fields = ['assessor_name', 'date_contour_reviewed', 'contour_modification_time_required', 'overall_rating']
        widgets = {
            'assessor_name': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-primary-500 focus:border-primary-500',
                'placeholder': 'Enter assessor name'
            }),
            'date_contour_reviewed': forms.DateInput(attrs={
                'type': 'date',
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-primary-500 focus:border-primary-500'
            }),
            'contour_modification_time_required': forms.NumberInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-primary-500 focus:border-primary-500',
                'placeholder': 'Time in minutes',
                'min': '0'
            }),
            'overall_rating': forms.NumberInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-primary-500 focus:border-primary-500',
                'placeholder': 'Rating (0-10)',
                'min': '0',
                'max': '10',
                'step': '1'
            })
        }
        labels = {
            'assessor_name': 'Assessor Name',
            'date_contour_reviewed': 'Date Contour Reviewed',
            'contour_modification_time_required': 'Total Modification Time (minutes)',
            'overall_rating': 'Overall Segmentation Quality Rating (0-10)'
        }


class VOIRatingForm(forms.ModelForm):
    """Form for rating individual VOI (Volume of Interest) quality"""
    
    class Meta:
        model = RTStructureFileVOIData
        fields = ['volume_name', 'contour_modification', 'contour_modification_type', 'contour_modification_comments']
        widgets = {
            'volume_name': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 bg-gray-100 border border-gray-300 rounded-md',
                'readonly': 'readonly'
            }),
            'contour_modification': forms.Select(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-primary-500 focus:border-primary-500'
            }),
            'contour_modification_type': forms.CheckboxSelectMultiple(attrs={
                'class': 'form-checkbox h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 rounded'
            }),
            'contour_modification_comments': forms.Textarea(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-primary-500 focus:border-primary-500',
                'rows': 3,
                'placeholder': 'Enter any comments about the contour modifications...'
            })
        }
        labels = {
            'volume_name': 'Structure Name',
            'contour_modification': 'Modification Required',
            'contour_modification_type': 'Modification Types',
            'contour_modification_comments': 'Comments'
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Make volume_name readonly
        self.fields['volume_name'].disabled = True


# Create formset for VOI ratings
VOIRatingFormSet = modelformset_factory(
    RTStructureFileVOIData,
    form=VOIRatingForm,
    extra=0,  # Don't show empty forms
    can_delete=False
)
