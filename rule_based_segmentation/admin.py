from django.contrib import admin

from .models import (
    BooleanExpressionNode,
    CleanupRuleConfig,
    CropBoundary,
    CropRuleConfig,
    IntensityRange,
    IntensityRuleConfig,
    MarginRuleConfig,
    PipelineRule,
    SegmentationJob,
    SegmentationPipeline,
)


class PipelineRuleInline(admin.TabularInline):
    model = PipelineRule
    extra = 0
    fields = ("order", "rule_type", "name", "output_action", "output_roi_type")
    ordering = ("order",)


class BooleanExpressionNodeInline(admin.TabularInline):
    model = BooleanExpressionNode
    extra = 0
    fields = ("parent", "node_type", "operation_type", "roi_name", "order")
    ordering = ("order",)


class IntensityRangeInline(admin.TabularInline):
    model = IntensityRange
    extra = 0
    fields = ("min_value", "max_value", "order")
    ordering = ("order",)


class CropBoundaryInline(admin.TabularInline):
    model = CropBoundary
    extra = 0
    fields = ("boundary_roi", "order")
    ordering = ("order",)


@admin.register(SegmentationPipeline)
class SegmentationPipelineAdmin(admin.ModelAdmin):
    list_display = ("name", "created_by", "is_public", "is_active", "created_at", "updated_at")
    list_filter = ("is_public", "is_active", "created_at")
    search_fields = ("name", "description")
    inlines = [PipelineRuleInline]


@admin.register(PipelineRule)
class PipelineRuleAdmin(admin.ModelAdmin):
    list_display = ("pipeline", "order", "rule_type", "name", "output_action")
    list_filter = ("rule_type", "output_action")
    ordering = ("pipeline", "order")

    def get_inlines(self, request, obj=None):
        if obj is None:
            return []
        if obj.rule_type == "BOOLEAN":
            return [BooleanExpressionNodeInline]
        if obj.rule_type == "INTENSITY":
            return [IntensityRangeInline]
        if obj.rule_type == "CROP":
            return [CropBoundaryInline]
        return []


@admin.register(SegmentationJob)
class SegmentationJobAdmin(admin.ModelAdmin):
    list_display = ("id", "pipeline", "status", "created_by", "created_at", "completed_at")
    list_filter = ("status", "created_at")
    readonly_fields = (
        "id",
        "pipeline",
        "input_type",
        "input_upload",
        "input_import",
        "dicom_series",
        "output_file_path",
        "backup_file_path",
        "status",
        "error_message",
        "result_summary",
        "started_at",
        "completed_at",
        "created_by",
        "created_at",
    )


admin.site.register(BooleanExpressionNode)
admin.site.register(IntensityRuleConfig)
admin.site.register(IntensityRange)
admin.site.register(MarginRuleConfig)
admin.site.register(CropRuleConfig)
admin.site.register(CropBoundary)
admin.site.register(CleanupRuleConfig)
