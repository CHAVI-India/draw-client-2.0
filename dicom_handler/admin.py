from django.contrib import admin
from allauth.account.decorators import secure_admin_login
from .models import (
    SystemConfiguration,
    AutosegmentationTemplate,
    AutosegmentationModel,
    AutosegmentationStructure,
    DICOMTagType,
    RuleSet,
    Rule,
    Patient,
    DICOMStudy,
    DICOMSeries,
    DICOMInstance,
    DICOMFileExport,
    RTStructureFileImport,
    ContourModificationTypeChoices,
    RTStructureFileVOIData,
    ChainExecutionLock,
    Statistics,
)

admin.autodiscover()
admin.site.login = secure_admin_login(admin.site.login)


@admin.register(SystemConfiguration)
class SystemConfigurationAdmin(admin.ModelAdmin):
    list_display = ('id', 'draw_base_url', 'client_id', 'draw_bearer_token_validaty', 'data_pull_start_datetime', 'updated_at')
    search_fields = ('client_id', 'draw_base_url')
    list_filter = ('draw_bearer_token_validaty', 'data_pull_start_datetime', 'updated_at')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('DRAW API Configuration', {
            'fields': ('draw_base_url', 'client_id', 'draw_upload_endpoint', 'draw_status_endpoint', 
                      'draw_download_endpoint', 'draw_notify_endpoint')
        }),
        ('Authentication', {
            'fields': ('draw_bearer_token', 'draw_refresh_token', 'draw_bearer_token_validaty')
        }),
        ('System Settings', {
            'fields': ('folder_configuration', 'data_pull_start_datetime')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(AutosegmentationTemplate)
class AutosegmentationTemplateAdmin(admin.ModelAdmin):
    list_display = ('template_name', 'template_description', 'created_at', 'updated_at')
    search_fields = ('template_name', 'template_description')
    list_filter = ('created_at', 'updated_at')
    
    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]


@admin.register(AutosegmentationModel)
class AutosegmentationModelAdmin(admin.ModelAdmin):
    list_display = ('name', 'autosegmentation_template_name', 'model_id', 'trainer_name', 'created_at')
    search_fields = ('name', 'trainer_name', 'config')
    list_filter = ('autosegmentation_template_name', 'trainer_name', 'created_at')
    autocomplete_fields = ['autosegmentation_template_name']
    
    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]


@admin.register(AutosegmentationStructure)
class AutosegmentationStructureAdmin(admin.ModelAdmin):
    list_display = ('name', 'autosegmentation_model', 'map_id', 'created_at')
    search_fields = ('name',)
    list_filter = ('autosegmentation_model', 'created_at')
    autocomplete_fields = ['autosegmentation_model']
    
    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]


@admin.register(DICOMTagType)
class DICOMTagTypeAdmin(admin.ModelAdmin):
    list_display = ('tag_name', 'tag_id', 'value_representation', 'tag_description')
    search_fields = ('tag_name', 'tag_id', 'tag_description')
    list_filter = ('value_representation', 'created_at')
    
    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]


@admin.register(RuleSet)
class RuleSetAdmin(admin.ModelAdmin):
    list_display = ('ruleset_name', 'rule_combination_type', 'associated_autosegmentation_template', 'created_at')
    search_fields = ('ruleset_name', 'ruleset_description')
    list_filter = ('rule_combination_type', 'associated_autosegmentation_template', 'created_at')
    autocomplete_fields = ['associated_autosegmentation_template']
    
    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]


@admin.register(Rule)
class RuleAdmin(admin.ModelAdmin):
    list_display = ('ruleset', 'dicom_tag_type', 'operator_type', 'tag_value_to_evaluate', 'created_at')
    search_fields = ('tag_value_to_evaluate',)
    list_filter = ('operator_type', 'ruleset', 'dicom_tag_type', 'created_at')
    autocomplete_fields = ['ruleset', 'dicom_tag_type']
    
    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ('patient_name', 'patient_id', 'deidentified_patient_id', 'patient_gender', 'patient_date_of_birth', 'created_at')
    search_fields = ('patient_name', 'patient_id', 'deidentified_patient_id')
    list_filter = ('patient_gender', 'patient_date_of_birth', 'created_at')
    date_hierarchy = 'patient_date_of_birth'
    
    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]


@admin.register(DICOMStudy)
class DICOMStudyAdmin(admin.ModelAdmin):
    list_display = ('study_instance_uid', 'patient', 'study_date', 'study_description', 'study_modality', 'created_at')
    search_fields = ('study_instance_uid', 'deidentified_study_instance_uid', 'study_description', 'patient__patient_name')
    list_filter = ('study_modality', 'study_date', 'created_at')
    autocomplete_fields = ['patient']
    date_hierarchy = 'study_date'
    
    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]


@admin.register(DICOMSeries)
class DICOMSeriesAdmin(admin.ModelAdmin):
    list_display = ('series_instance_uid', 'study', 'series_description', 'series_processsing_status', 'instance_count', 'created_at')
    search_fields = ('series_instance_uid', 'deidentified_series_instance_uid', 'series_description', 'study__study_instance_uid')
    list_filter = ('series_processsing_status', 'series_date', 'created_at')
    autocomplete_fields = ['study']
    filter_horizontal = ('matched_rule_sets', 'matched_templates')
    date_hierarchy = 'series_date'
    
    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]


@admin.register(DICOMInstance)
class DICOMInstanceAdmin(admin.ModelAdmin):
    list_display = ('sop_instance_uid', 'series_instance_uid', 'instance_path', 'created_at')
    search_fields = ('sop_instance_uid', 'deidentified_sop_instance_uid', 'instance_path')
    list_filter = ('created_at',)
    autocomplete_fields = ['series_instance_uid']
    
    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]


@admin.register(DICOMFileExport)
class DICOMFileExportAdmin(admin.ModelAdmin):
    list_display = ('task_id', 'deidentified_series_instance_uid', 'deidentified_zip_file_transfer_status', 
                   'server_segmentation_status', 'deidentified_zip_file_transfer_datetime', 'created_at')
    search_fields = ('task_id', 'deidentified_zip_file_path', 'deidentified_zip_file_checksum')
    list_filter = ('deidentified_zip_file_transfer_status', 'server_segmentation_status', 
                  'deidentified_zip_file_transfer_datetime', 'created_at')
    autocomplete_fields = ['deidentified_series_instance_uid']
    date_hierarchy = 'deidentified_zip_file_transfer_datetime'
    
    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]


@admin.register(RTStructureFileImport)
class RTStructureFileImportAdmin(admin.ModelAdmin):
    list_display = ('deidentified_series_instance_uid', 'server_segmentation_status', 'overall_rating', 
                   'assessor_name', 'date_contour_reviewed', 'created_at')
    search_fields = ('deidentified_sop_instance_uid', 'deidentified_rt_structure_file_path', 
                    'reidentified_rt_structure_file_path', 'assessor_name')
    list_filter = ('server_segmentation_status', 'overall_rating', 'date_contour_reviewed', 
                  'received_rt_structure_file_download_datetime', 'created_at')
    autocomplete_fields = ['deidentified_series_instance_uid']
    date_hierarchy = 'date_contour_reviewed'
    
    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]


@admin.register(ContourModificationTypeChoices)
class ContourModificationTypeChoicesAdmin(admin.ModelAdmin):
    list_display = ('modification_type', 'created_at', 'updated_at')
    search_fields = ('modification_type',)
    list_filter = ('created_at',)
    
    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]


@admin.register(RTStructureFileVOIData)
class RTStructureFileVOIDataAdmin(admin.ModelAdmin):
    list_display = ('volume_name', 'rt_structure_file_import', 'contour_modification', 'created_at')
    search_fields = ('volume_name', 'contour_modification_comments')
    list_filter = ('contour_modification', 'created_at')
    autocomplete_fields = ['rt_structure_file_import']
    filter_horizontal = ('contour_modification_type',)
    
    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]


@admin.register(ChainExecutionLock)
class ChainExecutionLockAdmin(admin.ModelAdmin):
    list_display = ('lock_name', 'chain_id', 'status', 'started_by', 'started_at', 'expires_at')
    search_fields = ('lock_name', 'chain_id', 'started_by')
    list_filter = ('status', 'started_at', 'expires_at')
    date_hierarchy = 'started_at'
    
    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]


@admin.register(Statistics)
class StatisticsAdmin(admin.ModelAdmin):
    list_display = ('parameter_name', 'parameter_value', 'created_at', 'updated_at')
    search_fields = ('parameter_name', 'parameter_value')
    list_filter = ('created_at', 'updated_at')
    date_hierarchy = 'created_at'
    
    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]
