from django.contrib import admin
from .models import (
    RTStructureSetFile,
    RTStructureSetVOI,
    RTStructureFileComparison,
    ComparisonResult
)


@admin.register(RTStructureSetFile)
class RTStructureSetFileAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'structure_set_label',
        'patient_id',
        'patient_name',
        'series_instance_uid',
        'structure_set_date',
        'created_at'
    ]
    list_filter = ['structure_set_date', 'created_at']
    search_fields = [
        'patient_id',
        'patient_name',
        'structure_set_label',
        'series_instance_uid',
        'sop_instance_uid'
    ]
    readonly_fields = ['created_at', 'updated_at']
    fieldsets = (
        ('Patient Information', {
            'fields': ('patient_name', 'patient_id')
        }),
        ('DICOM Identifiers', {
            'fields': (
                'study_instance_uid',
                'series_instance_uid',
                'sop_instance_uid',
                'referenced_series_instance_uid'
            )
        }),
        ('Structure Set Information', {
            'fields': ('structure_set_label', 'structure_set_date', 'rtstructure_file')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(RTStructureSetVOI)
class RTStructureSetVOIAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'rtstructure_set_file',
        'roi_name',
        'roi_number',
        'roi_volume',
        'created_at'
    ]
    list_filter = ['rtstructure_set_file', 'created_at']
    search_fields = ['roi_name', 'roi_description']
    readonly_fields = ['created_at', 'updated_at']
    fieldsets = (
        ('RT Structure Set', {
            'fields': ('rtstructure_set_file',)
        }),
        ('ROI Information', {
            'fields': ('roi_name', 'roi_description', 'roi_number', 'roi_volume')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


class ComparisonResultInline(admin.TabularInline):
    model = ComparisonResult
    extra = 0
    readonly_fields = ['comparision_type', 'result_value', 'created_at']
    can_delete = False


@admin.register(RTStructureFileComparison)
class RTStructureFileComparisonAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'first_rtstructure',
        'second_rtstructure',
        'user',
        'has_results',
        'created_at'
    ]
    list_filter = ['user', 'created_at']
    search_fields = [
        'first_rtstructure__roi_name',
        'second_rtstructure__roi_name'
    ]
    readonly_fields = ['created_at', 'updated_at']
    inlines = [ComparisonResultInline]
    
    def has_results(self, obj):
        return obj.comparisonresult_set.exists()
    has_results.boolean = True
    has_results.short_description = 'Has Results'
    
    fieldsets = (
        ('Comparison', {
            'fields': ('first_rtstructure', 'second_rtstructure', 'user')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(ComparisonResult)
class ComparisonResultAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'comparison',
        'comparision_type',
        'result_value',
        'created_at'
    ]
    list_filter = ['comparision_type', 'created_at']
    search_fields = ['comparison__first_rtstructure__roi_name']
    readonly_fields = ['created_at', 'updated_at']
    fieldsets = (
        ('Comparison', {
            'fields': ('comparison',)
        }),
        ('Result', {
            'fields': ('comparision_type', 'result_value')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
