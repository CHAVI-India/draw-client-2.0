from django import forms
from django.forms import inlineformset_factory
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Submit, Row, Column, Fieldset, Div, HTML
from .models import RuleSet, Rule, DICOMTagType, AutosegmentationTemplate, RuleCombinationType, OperatorType
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
