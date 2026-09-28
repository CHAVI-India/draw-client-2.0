import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from .utils.validators import (
    validate_boolean_rule,
    validate_cleanup_rule,
    validate_crop_rule,
    validate_intensity_rule,
    validate_margin_rule,
)


class SegmentationPipeline(models.Model):
    """Reusable pipeline template containing an ordered list of rules."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=256, help_text="Pipeline template name")
    description = models.TextField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_pipelines",
    )
    is_public = models.BooleanField(
        default=False,
        help_text="Public pipelines are visible to all authenticated users.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        permissions = [
            ("view_public_pipeline", "Can view public pipelines"),
        ]

    def __str__(self):
        return self.name


class PipelineRule(models.Model):
    """One step inside a pipeline."""

    RULE_TYPE_CHOICES = [
        ("BOOLEAN", "Boolean Expression"),
        ("INTENSITY", "Intensity Range"),
        ("MARGIN", "Margin"),
        ("CROP", "Crop to Boundary"),
        ("CLEANUP", "Cleanup / Refinement"),
    ]

    OUTPUT_ACTION_CHOICES = [
        ("CREATE_NEW", "Create new ROI"),
        ("REPLACE_EXISTING", "Replace existing ROI"),
    ]

    ROI_TYPE_CHOICES = [
        ("EXTERNAL", "EXTERNAL"),
        ("PTV", "PTV"),
        ("CTV", "CTV"),
        ("GTV", "GTV"),
        ("TREATED_VOLUME", "TREATED_VOLUME"),
        ("IRRAD_VOLUME", "IRRAD_VOLUME"),
        ("OAR", "OAR"),
        ("BOLUS", "BOLUS"),
        ("AVOIDANCE", "AVOIDANCE"),
        ("ORGAN", "ORGAN"),
        ("MARKER", "MARKER"),
        ("REGISTRATION", "REGISTRATION"),
        ("ISOCENTER", "ISOCENTER"),
        ("CONTRAST_AGENT", "CONTRAST_AGENT"),
        ("CAVITY", "CAVITY"),
        ("BRACHY_CHANNEL", "BRACHY_CHANNEL"),
        ("BRACHY_ACCESSORY", "BRACHY_ACCESSORY"),
        ("BRACHY_SRC_APP", "BRACHY_SRC_APP"),
        ("BRACHY_CHNL_SHLD", "BRACHY_CHNL_SHLD"),
        ("SUPPORT", "SUPPORT"),
        ("FIXATION", "FIXATION"),
        ("DOSE_REGION", "DOSE_REGION"),
        ("CONTROL", "CONTROL"),
        ("DOSE_MEASUREMENT", "DOSE_MEASUREMENT"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pipeline = models.ForeignKey(
        SegmentationPipeline,
        on_delete=models.CASCADE,
        related_name="rules",
    )
    order = models.PositiveIntegerField()
    rule_type = models.CharField(max_length=20, choices=RULE_TYPE_CHOICES)
    name = models.CharField(
        max_length=16,
        help_text="Output ROI name. Must be unique within the RTStruct or will be replaced/renamed.",
    )
    output_action = models.CharField(
        max_length=20,
        choices=OUTPUT_ACTION_CHOICES,
        default="CREATE_NEW",
    )
    output_color = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        help_text="DICOM color string e.g. '255\\0\\0'. Defaults to yellow if blank.",
    )
    output_roi_type = models.CharField(
        max_length=32,
        choices=ROI_TYPE_CHOICES,
        null=True,
        blank=True,
        default="ORGAN",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["pipeline", "order"]
        unique_together = [["pipeline", "order"]]

    def clean(self):
        super().clean()
        if not self.output_color:
            self.output_color = "255\\255\\0"

        if self.rule_type == "BOOLEAN":
            validate_boolean_rule(self)
        elif self.rule_type == "INTENSITY":
            validate_intensity_rule(self)
        elif self.rule_type == "MARGIN":
            validate_margin_rule(self)
        elif self.rule_type == "CROP":
            validate_crop_rule(self)
        elif self.rule_type == "CLEANUP":
            validate_cleanup_rule(self)

    def __str__(self):
        return f"{self.order}. {self.name} ({self.rule_type})"


class BooleanExpressionNode(models.Model):
    """Self-referential tree for boolean rules."""

    NODE_TYPE_CHOICES = [
        ("OPERATION", "Operation"),
        ("ROI", "ROI Reference"),
    ]
    OPERATION_TYPE_CHOICES = [
        ("UNION", "Union"),
        ("INTERSECTION", "Intersection"),
        ("SUBTRACT", "Subtract"),
        ("XOR", "Exclusive OR"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pipeline_rule = models.ForeignKey(
        PipelineRule,
        on_delete=models.CASCADE,
        related_name="boolean_nodes",
        limit_choices_to={"rule_type": "BOOLEAN"},
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
    )
    node_type = models.CharField(max_length=20, choices=NODE_TYPE_CHOICES)
    operation_type = models.CharField(
        max_length=20,
        choices=OPERATION_TYPE_CHOICES,
        null=True,
        blank=True,
    )
    roi_name = models.CharField(max_length=256, null=True, blank=True)
    order = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["pipeline_rule", "order"]

    def clean(self):
        super().clean()
        if self.node_type == "OPERATION":
            if not self.operation_type:
                raise ValidationError(
                    {"operation_type": "Operation nodes require an operation_type."}
                )
            if self.roi_name:
                raise ValidationError(
                    {"roi_name": "Operation nodes cannot have roi_name."}
                )
        else:
            if not self.roi_name:
                raise ValidationError({"roi_name": "ROI nodes require roi_name."})
            if self.operation_type:
                raise ValidationError(
                    {"operation_type": "ROI nodes cannot have operation_type."}
                )

    def __str__(self):
        if self.node_type == "OPERATION":
            return f"{self.operation_type} node"
        return f"ROI {self.roi_name}"


class IntensityRuleConfig(models.Model):
    """Configuration for an intensity-range rule."""

    SEED_TYPE_CHOICES = [
        ("STRUCTURE", "Structure"),
        ("IMAGE", "Full image"),
        ("BOUNDARY", "Boundary structure"),
    ]

    pipeline_rule = models.OneToOneField(
        PipelineRule,
        on_delete=models.CASCADE,
        related_name="intensity_config",
        limit_choices_to={"rule_type": "INTENSITY"},
    )
    seed_type = models.CharField(max_length=20, choices=SEED_TYPE_CHOICES)
    seed_roi = models.CharField(max_length=256, null=True, blank=True)
    boundary_roi = models.CharField(max_length=256, null=True, blank=True)
    modality_hint = models.CharField(max_length=16, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class IntensityRange(models.Model):
    """A single intensity range inside an intensity rule."""

    intensity_rule = models.ForeignKey(
        IntensityRuleConfig,
        on_delete=models.CASCADE,
        related_name="ranges",
    )
    min_value = models.FloatField()
    max_value = models.FloatField()
    order = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order"]

    def clean(self):
        super().clean()
        if self.min_value >= self.max_value:
            raise ValidationError("min_value must be less than max_value.")


class MarginRuleConfig(models.Model):
    """Configuration for a margin rule."""

    VARIANT_CHOICES = [
        ("UNIFORM", "Uniform"),
        ("ANISOTROPIC", "Anisotropic"),
    ]
    KERNEL_CHOICES = [
        ("ball", "Ball"),
        ("box", "Box"),
        ("cross", "Cross"),
    ]

    pipeline_rule = models.OneToOneField(
        PipelineRule,
        on_delete=models.CASCADE,
        related_name="margin_config",
        limit_choices_to={"rule_type": "MARGIN"},
    )
    variant = models.CharField(max_length=20, choices=VARIANT_CHOICES)
    source = models.CharField(max_length=256)
    margin_mm = models.FloatField(null=True, blank=True)
    margin_x_mm = models.FloatField(null=True, blank=True)
    margin_y_mm = models.FloatField(null=True, blank=True)
    margin_z_mm = models.FloatField(null=True, blank=True)
    kernel_type = models.CharField(
        max_length=16,
        choices=KERNEL_CHOICES,
        default="ball",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class CropRuleConfig(models.Model):
    """Configuration for a crop-to-boundary rule."""

    pipeline_rule = models.OneToOneField(
        PipelineRule,
        on_delete=models.CASCADE,
        related_name="crop_config",
        limit_choices_to={"rule_type": "CROP"},
    )
    source = models.CharField(max_length=256)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class CropBoundary(models.Model):
    """A single boundary ROI used by a crop rule."""

    crop_rule = models.ForeignKey(
        CropRuleConfig,
        on_delete=models.CASCADE,
        related_name="boundaries",
    )
    boundary_roi = models.CharField(max_length=256)
    order = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order"]


class CleanupRuleConfig(models.Model):
    """Configuration for a cleanup/refinement rule."""

    OPERATION_CHOICES = [
        ("SMOOTH_STRUCTURE", "Smooth Surface"),
        ("GAUSSIAN_SMOOTH", "Gaussian Smooth"),
        ("FILL_HOLES", "Fill Holes"),
        ("REMOVE_SMALL_COMPONENTS", "Remove Small Components"),
        ("KEEP_LARGEST_COMPONENT", "Keep Largest Component"),
    ]

    pipeline_rule = models.OneToOneField(
        PipelineRule,
        on_delete=models.CASCADE,
        related_name="cleanup_config",
        limit_choices_to={"rule_type": "CLEANUP"},
    )
    operation = models.CharField(max_length=30, choices=OPERATION_CHOICES)
    source = models.CharField(max_length=256)
    smoothing_mm = models.FloatField(null=True, blank=True)
    iterations = models.PositiveIntegerField(null=True, blank=True)
    min_size_mm3 = models.FloatField(null=True, blank=True)
    fully_connected = models.BooleanField(null=True, blank=True)
    sigma_mm = models.FloatField(null=True, blank=True)
    threshold = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class SegmentationJob(models.Model):
    """Tracks execution of a pipeline on a specific RTStruct."""

    INPUT_TYPE_CHOICES = [
        ("UPLOAD", "Uploaded RTStruct"),
        ("IMPORT", "Auto-segmented RTStructureFileImport"),
    ]

    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("STARTED", "Started"),
        ("SUCCESS", "Success"),
        ("FAILED", "Failed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pipeline = models.ForeignKey(
        SegmentationPipeline,
        on_delete=models.PROTECT,
        related_name="jobs",
    )
    input_type = models.CharField(
        max_length=10,
        choices=INPUT_TYPE_CHOICES,
    )
    input_upload = models.ForeignKey(
        "spatial_overlap.RTStructureSetFile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="segmentation_jobs",
    )
    input_import = models.ForeignKey(
        "dicom_handler.RTStructureFileImport",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="segmentation_jobs",
    )
    dicom_series = models.ForeignKey(
        "dicom_handler.DICOMSeries",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="segmentation_jobs",
    )
    output_file_path = models.CharField(max_length=512, null=True, blank=True)
    backup_file_path = models.CharField(max_length=512, null=True, blank=True)
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default="PENDING",
    )
    error_message = models.TextField(null=True, blank=True)
    result_summary = models.JSONField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Job {self.id} - {self.pipeline.name} ({self.status})"
