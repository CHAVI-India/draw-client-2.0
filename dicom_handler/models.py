from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import timedelta
import uuid
from encrypted_model_fields.fields import EncryptedCharField
from django.core.validators import MinValueValidator, MaxValueValidator
# Create your models here.

class SystemConfiguration(models.Model):
    '''
    This is a model to store data about the system configuration. This will be a singleton model.
    '''
    id = models.IntegerField(primary_key=True, default=1, editable=False)
    draw_base_url = models.CharField(max_length=256,null=True,blank=True,help_text="Base URL of the DRAW API server", default="https://draw.chavi.ai/")
    client_id = models.CharField(max_length=256,null=True,blank=True,help_text="Client ID from the DRAW API server. Please rember this is case sensitive and should match what is entered in the server to ensure you can see the data for your center in the server.")
    draw_upload_endpoint = models.CharField(max_length=256,null=True,blank=True,help_text="Upload endpoint of the DRAW API server where the image zip file and checksum is to be uploaded.", default="/api/upload/")
    draw_status_endpoint = models.CharField(max_length=256,null=True,blank=True,help_text="Status endpoint of the DRAW API server where status of segmentation is to be polled. The task_id is returned by the DRAW API server.", default="/api/upload/{task_id}/status/")
    draw_download_endpoint = models.CharField(max_length=256,null=True,blank=True,help_text="Download endpoint of the DRAW API server where the RTStructureSet file is to be downloaded.", default="/api/rtstruct/{task_id}/")
    draw_notify_endpoint = models.CharField(max_length=256,null=True,blank=True,help_text="Notification endpoint of the DRAW API server where notification is sent after completion of RTStructure Download.", default="/api/rtstruct/{task_id}/confirm/")
    draw_token_refresh_endpoint = models.CharField(max_length=256,null=True,blank=True,help_text="Token refresh endpoint of the DRAW API server where the refresh token is to be refreshed.", default="/api/token/refresh/")
    draw_bearer_token = EncryptedCharField(max_length=256,null=True,blank=True,help_text="Bearer token from the DRAW API server")
    draw_refresh_token = EncryptedCharField(max_length=256,null=True,blank=True,help_text="Refresh token from the DRAW API server")
    draw_bearer_token_validaty = models.DateTimeField(null=True,blank=True,help_text="Bearer token validity for the DRAW API server")
    folder_configuration = models.CharField(max_length=256,null=True,blank=True,help_text="Full path of the DICOM folder from which DICOM data will be read and RT Structure file will be exported to. Use the default value if your application has been installed using docker.", default="/app/datastore")
    data_pull_start_datetime = models.DateTimeField(null=True,blank=True,help_text="Data pull start datetime for the DRAW API server. The system will only copy DICOM data which has been created or modified after this date and time.")
    study_date_based_filtering = models.BooleanField(default=False,help_text="If checked then during the DICOM export task, the system will filter out DICOM studies whose study dates are before the date set for the Pull Start Date Time Field above. Note that this will read the DICOM metadata and retrive the study dates from the files.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        """
        Custom validation to ensure draw_base_url has a trailing slash.
        """
        super().clean()
        if self.draw_base_url and not self.draw_base_url.endswith('/'):
            raise ValidationError({
                'draw_base_url': 'The base URL must end with a trailing slash (/). Please add this / at the end of the URL.'
            })

    def save(self, *args, **kwargs):
        # Run validation before saving
        self.full_clean()
        # Ensure only one instance exists
        self.pk = 1
        super(SystemConfiguration, self).save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        # Prevent deletion of the singleton instance
        pass

    def __str__(self):
        return "System Configuration"

    class Meta:
        verbose_name = "System Configuration"
        verbose_name_plural = "System Configuration"

    @classmethod
    def load(cls):
        """
        Load the singleton instance. Creates one if it doesn't exist.
        """
        obj, created = cls.objects.get_or_create(pk=1)
        return obj

    @staticmethod
    def get_singleton():
        """
        Get the singleton instance. Returns None if it doesn't exist.
        """
        try:
            return SystemConfiguration.objects.get(pk=1)
        except SystemConfiguration.DoesNotExist:
            return None

class AutosegmentationTemplate(models.Model):
    '''
    This is a model to store data about the templates.
    '''
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    template_name = models.CharField(max_length=256)
    template_description = models.CharField(max_length=256)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.template_name

    class Meta:
        verbose_name = "Template"
        verbose_name_plural = "Templates"

class AutosegmentationModel(models.Model):
    '''
    This table will hold the information related to models from the DRAW API server for the autosegmentation templates
    '''
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    autosegmentation_template_name= models.ForeignKey(AutosegmentationTemplate,on_delete=models.CASCADE,null=True,blank=True)
    model_id = models.IntegerField(null=True,blank=True)
    name = models.CharField(max_length=256)
    config = models.CharField(max_length=256)
    trainer_name = models.CharField(max_length=256)
    postprocess = models.CharField(max_length=256)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Autosegmentation Model"
        verbose_name_plural = "Autosegmentation Models"

class AutosegmentationStructure(models.Model):
    '''
    This table will hold the information related to the individual structures in a given model.Again data will come from the DRAW API.
    '''
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    autosegmentation_model = models.ForeignKey(AutosegmentationModel,on_delete=models.CASCADE,null=True,blank=True)
    map_id = models.IntegerField(null=True,blank=True)
    name = models.CharField(max_length=256)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Autosegmentation Mapped Structure"
        verbose_name_plural = "Autosegmentation Mapped Structures"
    
class DICOMTagType(models.Model):
    '''
    This is a model to store data about the DICOM tags. Note that only DICOM tags approved by the DICOM standards are allowed.
    '''
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tag_name = models.CharField(max_length=256)
    tag_id = models.CharField(max_length=256, null=True, blank = True)
    tag_description = models.CharField(max_length=256, null=True, blank = True)
    value_representation = models.CharField(max_length=256, null=True, blank = True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.tag_name

    @property
    def vr_guidance(self):
        """Get VR guidance for this DICOM tag"""
        if self.value_representation:
            from .vr_validators import VRValidator
            return VRValidator.get_vr_guidance(self.value_representation)
        return None

    @property
    def compatible_operators(self):
        """Get compatible operators for this DICOM tag's VR"""
        if self.value_representation:
            from .vr_validators import VRValidator
            return VRValidator.get_compatible_operators(self.value_representation)
        return []

    def validate_value_for_vr(self, value):
        """Validate a value against this tag's VR requirements"""
        if self.value_representation:
            from .vr_validators import VRValidator
            return VRValidator.validate_value_for_vr(value, self.value_representation)
        return True, ""

    def is_operator_compatible(self, operator):
        """Check if an operator is compatible with this tag's VR"""
        if self.value_representation:
            from .vr_validators import VRValidator
            return VRValidator.is_operator_compatible(self.value_representation, operator)
        return True

    class Meta:
        verbose_name = "DICOM Tag Type"
        verbose_name_plural = "DICOM Tag Types"

class RuleCombinationType(models.TextChoices):
    '''
    This is an enumerated list of rule combination types for the rulesets.
    '''
    AND = "AND", "And"
    OR = "OR", "Or"

class RuleSet(models.Model):
    '''
    This is a model to store data about the rulesets. A ruleset is a collection of rules that are applied to a DICOM series to determine the automatic segmentation template to be used.
    '''
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ruleset_name = models.CharField(max_length=256, help_text="The name of the ruleset.")
    ruleset_description = models.CharField(max_length=256, help_text="The description of the ruleset.")
    rule_combination_type = models.CharField(max_length=256, choices=RuleCombinationType.choices, help_text="The rule combination type. This can be AND or OR.")
    associated_autosegmentation_template = models.ForeignKey(AutosegmentationTemplate, on_delete=models.CASCADE, null=True, blank=True, help_text="The autosegmentation template associated with the ruleset.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.ruleset_name

    class Meta:
        verbose_name = "Rule Set"
        verbose_name_plural = "Rule Sets"

class OperatorType(models.TextChoices):
    '''
    This is an enumerated list of operator choices for the rules to be evaluated against.
    '''
    EQUALS = "EQUALS", "Equals"
    NOT_EQUALS = "NOT_EQUALS", "Not Equals"
    GREATER_THAN = "GREATER_THAN", "Greater Than"
    LESS_THAN = "LESS_THAN", "Less Than"
    GREATER_THAN_OR_EQUAL_TO = "GREATER_THAN_OR_EQUAL_TO", "Greater Than Or Equal To"
    LESS_THAN_OR_EQUAL_TO = "LESS_THAN_OR_EQUAL_TO", "Less Than Or Equal To"
    CASE_SENSITIVE_STRING_CONTAINS = "CASE_SENSITIVE_STRING_CONTAINS", "Case Sensitive String Contains"
    CASE_INSENSITIVE_STRING_CONTAINS = "CASE_INSENSITIVE_STRING_CONTAINS", "Case Insensitive String Contains"
    CASE_SENSITIVE_STRING_DOES_NOT_CONTAIN = "CASE_SENSITIVE_STRING_DOES_NOT_CONTAIN", "Case Sensitive String Does Not Contain"
    CASE_INSENSITIVE_STRING_DOES_NOT_CONTAIN = "CASE_INSENSITIVE_STRING_DOES_NOT_CONTAIN", "Case Insensitive String Does Not Contain"
    CASE_SENSITIVE_STRING_EXACT_MATCH = "CASE_SENSITIVE_STRING_EXACT_MATCH", "Case Sensitive String Exact Match"
    CASE_INSENSITIVE_STRING_EXACT_MATCH = "CASE_INSENSITIVE_STRING_EXACT_MATCH", "Case Insensitive String Exact Match"
    
class Rule(models.Model):
    '''
    This is a model to store data about the rules. A rule is a condition that is evaluated against a DICOM tag to determine if it matches a specific value.
    '''
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ruleset = models.ForeignKey(RuleSet, on_delete=models.CASCADE, help_text="The ruleset to which this rule belongs to.")
    dicom_tag_type = models.ForeignKey(DICOMTagType, on_delete=models.CASCADE, help_text="The DICOM tag type whose value will be evaluated.")
    operator_type = models.CharField(max_length=256, choices=OperatorType.choices, help_text="The operator type. This can be a string operator to be used for text and number or a numeric operator for numeric values.")
    tag_value_to_evaluate = models.CharField(max_length=256, help_text="The tag value to evaluate. This is the value that the rule will match to.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def is_numeric_value(self, value):
        """Check if the value is numeric (integer or float)"""
        try:
            float(value)
            return True
        except ValueError:
            return False

    def clean(self):
        """Validate that operators are used appropriately with value types and VR requirements"""
        from .vr_validators import VRValidator
        super().clean()
        
        if not self.operator_type or not self.tag_value_to_evaluate:
            return
        
        # Get the VR code from the selected DICOM tag
        vr_code = None
        if self.dicom_tag_type and self.dicom_tag_type.value_representation:
            vr_code = self.dicom_tag_type.value_representation
        
        # VR-specific validation
        if vr_code:
            # Validate value format against VR requirements
            is_valid, vr_error = VRValidator.validate_value_for_vr(
                self.tag_value_to_evaluate, vr_code
            )
            if not is_valid:
                raise ValidationError({
                    'tag_value_to_evaluate': f'Value format invalid for {vr_code} VR: {vr_error}'
                })
            
            # Check operator compatibility with VR
            if not VRValidator.is_operator_compatible(vr_code, self.operator_type):
                compatible_ops = VRValidator.get_compatible_operators(vr_code)
                raise ValidationError({
                    'operator_type': f'Operator "{self.get_operator_type_display()}" is not compatible with '
                                   f'{vr_code} VR. Compatible operators: {", ".join(compatible_ops)}'
                })
        
        # Fallback to original operator-based validation if no VR available
        else:
            # Define string operators that allow string values (contain "STRING" in their name)
            string_operators = [
                OperatorType.CASE_SENSITIVE_STRING_CONTAINS,
                OperatorType.CASE_INSENSITIVE_STRING_CONTAINS,
                OperatorType.CASE_SENSITIVE_STRING_DOES_NOT_CONTAIN,
                OperatorType.CASE_INSENSITIVE_STRING_DOES_NOT_CONTAIN,
                OperatorType.CASE_SENSITIVE_STRING_EXACT_MATCH,
                OperatorType.CASE_INSENSITIVE_STRING_EXACT_MATCH,
            ]
            
            is_numeric = self.is_numeric_value(self.tag_value_to_evaluate)
            
            # All operators except string operators require numeric values
            if self.operator_type not in string_operators and not is_numeric:
                raise ValidationError({
                    'tag_value_to_evaluate': f'Operator "{self.get_operator_type_display()}" can only be used with numeric values. '
                                           f'The value "{self.tag_value_to_evaluate}" is not numeric. Use string operators for text values.'
                })

    def save(self, *args, **kwargs):
        """Override save to run validation"""
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.dicom_tag_type.tag_name} {self.get_operator_type_display()} {self.tag_value_to_evaluate}"

    class Meta:
        verbose_name = "Rule"
        verbose_name_plural = "Rules"

class Patient(models.Model):
    '''
    This is a model to store data about the patients.
    '''
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient_id = models.CharField(max_length=256,null=True,blank=True, unique=True)
    deidentified_patient_id = models.CharField(max_length=256,null=True,blank=True)
    patient_name = models.CharField(max_length=100,null=True,blank=True)
    patient_gender = models.CharField(max_length=10,null=True,blank=True)
    patient_date_of_birth = models.DateField(null=True,blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.patient_name

    class Meta:
        verbose_name = "Patient"
        verbose_name_plural = "Patients"
        ordering = ["-patient_date_of_birth"]    

class DICOMStudy(models.Model):
    '''
    This is a model to store data about the DICOM studies.
    '''
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(Patient,on_delete=models.CASCADE)
    study_instance_uid = models.CharField(max_length=256,null=True,blank=True)
    deidentified_study_instance_uid = models.CharField(max_length=256,null=True,blank=True)
    study_date = models.DateField(null=True,blank=True)
    deidentified_study_date = models.DateField(null=True,blank=True)
    study_description = models.CharField(max_length=256,null=True,blank=True)
    study_protocol = models.CharField(max_length=256,null=True,blank=True)
    study_modality = models.CharField(max_length=256,null=True,blank=True)
    study_date = models.DateField(null=True,blank=True)
    deidentified_study_date = models.DateField(null=True,blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)    

    def __str__(self):
        return self.study_instance_uid
    
    class Meta:
        verbose_name = "DICOM Study"
        verbose_name_plural = "DICOM Studies"
        ordering = ["-study_date"]

class ProcessingStatus(models.TextChoices):
    '''
    This is an enumerated list of processing statuses for the DICOM series.
    '''
    UNPROCESSED = "UNPROCESSED", "Unprocessed"
    RULE_MATCHED = "RULE_MATCHED", "Rule Matched"
    RULE_NOT_MATCHED = "RULE_NOT_MATCHED", "Rule Not Matched"
    MULTIPLE_RULES_MATCHED = "MULTIPLE_RULES_MATCHED", "Multiple Rules Matched"
    DEIDENTIFIED_SUCCESSFULLY = "DEIDENTIFIED_SUCCESSFULLY", "Deidentified Successfully"
    DEIDENTIFICATION_FAILED = "DEIDENTIFICATION_FAILED", "Deidentification Failed"  
    PENDING_TRANSFER_TO_DRAW_SERVER = "PENDING_TRANSFER_TO_DRAW_SERVER", "Pending Transfer to Draw Server"
    SENT_TO_DRAW_SERVER = "SENT_TO_DRAW_SERVER", "Sent to Draw Server"
    FAILED_TRANSFER_TO_DRAW_SERVER = "FAILED_TRANSFER_TO_DRAW_SERVER", "Failed Transfer to Draw Server"
    INVALID_RTSTRUCTURE_RECEIVED = "INVALID_RTSTRUCTURE_RECEIVED", "Invalid RT Structure Received"
    RTSTRUCTURE_RECEIVED = "RTSTRUCTURE_RECEIVED", "RT Structure Received"
    RTSTRUCTURE_EXPORTED  = "RTSTRUCTURE_EXPORTED", "RT Structure Exported"
    RTSTRUCTURE_EXPORT_FAILED = "RTSTRUCTURE_EXPORT_FAILED", "RT Structure Export Failed"    

class DICOMSeries(models.Model):
    '''
    This is a model to store data about the DICOM series. The primary matching of the rules will always be done with the DICOM series.
    '''
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    study = models.ForeignKey(DICOMStudy,on_delete=models.CASCADE)
    series_instance_uid = models.CharField(max_length=256,null=True,blank=True)
    deidentified_series_instance_uid = models.CharField(max_length=256,null=True,blank=True)
    series_root_path = models.CharField(max_length=256,null=True,blank=True)
    frame_of_reference_uid = models.CharField(max_length=256,null=True,blank=True)
    deidentified_frame_of_reference_uid = models.CharField(max_length=256,null=True,blank=True)
    series_description = models.CharField(max_length=256,null=True,blank=True)
    series_date = models.DateField(null=True,blank=True)
    deidentified_series_date = models.DateField(null=True,blank=True)
    series_files_fully_read = models.BooleanField(default=False)
    series_files_fully_read_datetime = models.DateTimeField(null=True,blank=True)
    instance_count = models.IntegerField(null=True,blank=True)
    matched_rule_sets = models.ManyToManyField(RuleSet)
    matched_templates = models.ManyToManyField(AutosegmentationTemplate)
    series_processsing_status = models.CharField(max_length=256,choices=ProcessingStatus.choices,default=ProcessingStatus.UNPROCESSED, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.series_instance_uid
    
    class Meta:
        verbose_name = "DICOM Series"
        verbose_name_plural = "DICOM Series"

class DICOMInstance(models.Model):
    '''
    This is a model to store data about the DICOM instances.
    '''
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    series_instance_uid = models.ForeignKey(DICOMSeries,on_delete=models.CASCADE)
    sop_instance_uid = models.CharField(max_length=256,null=True,blank=True)
    deidentified_sop_instance_uid = models.CharField(max_length=256,null=True,blank=True)
    instance_path = models.CharField(max_length=256,null=True,blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return self.sop_instance_uid
    
    class Meta:
        verbose_name = "DICOM Instance"
        verbose_name_plural = "DICOM Instances"

class DICOMFileTransferStatus(models.TextChoices):
    '''
    This is an enumerated list of DICOM file transfer statuses.
    '''
    PENDING = "PENDING", "Pending"
    IN_PROGRESS = "IN_PROGRESS", "In Progress"
    COMPLETED = "COMPLETED", "Completed"
    FAILED = "FAILED", "Failed"
    CHECKSUM_MATCH_FAILED = 'CHEKSUM_MATCH_FAILED',"Checksum match failed"
    INVALID_RTSTRUCT_FILE = 'INVALID_RT_STRUCT_FILE',"Invalid RTStructureSet FIle Received"
    RTSTRUCT_RECEIVED = "RTSTRUCT_RECEIVED", "RTStructureSet File Received"

class DICOMFileExport(models.Model):
    '''
    This is a model to store data about the DICOM files exported to DRAW server
    '''
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    deidentified_series_instance_uid = models.ForeignKey(DICOMSeries,on_delete=models.CASCADE)
    deidentified_zip_file_path = models.CharField(max_length=256,null=True,blank=True,help_text="Path of the zip file exported to the DRAW API server")
    deidentified_zip_file_checksum = models.CharField(max_length=256,null=True,blank=True,help_text="Checksum of the zip file exported to the DRAW API server")
    deidentified_zip_file_transfer_status = models.CharField(max_length=256,choices=DICOMFileTransferStatus.choices,default=DICOMFileTransferStatus.PENDING, null=True, blank=True,help_text="Status of the zip file transfer to the DRAW API server")
    deidentified_zip_file_transfer_datetime = models.DateTimeField(null=True,blank=True,help_text="Datetime when the zip file was transferred to the DRAW API server")
    server_segmentation_status = models.CharField(max_length=256,null=True, blank=True,help_text="Status of the segmentation returned by the DRAW API server")
    task_id = models.CharField(max_length=256,null=True, blank=True,help_text="Task ID returned by the DRAW API server")
    server_segmentation_updated_datetime = models.DateTimeField(null=True,blank=True,help_text="Datetime when the segmentation was updated by the DRAW API server")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)    
    
    def __str__(self):
        return self.deidentified_zip_file_path  

    class Meta:
        verbose_name = "DICOM File Export"
        verbose_name_plural = "DICOM File Exports"

class RTStructureFileImport(models.Model):
    '''
    This is a model to store data about the RT structure files imported from DRAW server
    '''
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    deidentified_series_instance_uid = models.ForeignKey(DICOMSeries,on_delete=models.CASCADE,null=True,blank=True)
    deidentified_sop_instance_uid = models.CharField(max_length=256,null=True,blank=True)
    deidentified_rt_structure_file_path = models.CharField(max_length=256,null=True,blank=True)
    received_rt_structure_file_checksum = models.CharField(max_length=256,null=True,blank=True)
    received_rt_structure_file_download_datetime = models.DateTimeField(null=True,blank=True)
    server_segmentation_status = models.CharField(max_length=256,null=True, blank=True)
    server_segmentation_updated_datetime = models.DateTimeField(null=True,blank=True)
    reidentified_rt_structure_file_path = models.CharField(max_length=256,null=True,blank=True)
    reidentified_rt_structure_file_export_datetime = models.DateTimeField(null=True,blank=True)
    date_contour_reviewed = models.DateField(null=True,blank=True,help_text="Date when the contour was reviewed")
    contour_modification_time_required = models.IntegerField(null=True,blank=True,help_text="Time required to modify the contours in this structure set in minutes. Please do not include time required to create or edit new structures which were not supposed to be autosegmented.")
    assessor_name = models.CharField(max_length=256,null=True,blank=True,help_text="Name of the assessor who reviewed the contour")
    overall_rating = models.IntegerField(null=True,blank=True,
    help_text="Overall rating of the automatic segementation quality between 0 to 10 where 10 indicates an excellent quality and 0 the worst possible quality.",
    default=5, validators=[MinValueValidator(0), MaxValueValidator(10)])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)    
    
    def __str__(self):
        return self.deidentified_rt_structure_file_path or self.reidentified_rt_structure_file_path or f"RTStruct Import {self.id}"  

    class Meta:
        verbose_name = "RT Structure File Import"
        verbose_name_plural = "RT Structure File Imports"


class ContourModificationChoices(models.TextChoices):
    '''
    This is an enumerated list of contour modification choices.
    '''
    NO_MODIFICATION = "NO_MODIFICATION", "No Modification"
    MAJOR_MODIFICATION = "MAJOR_MODIFICATION", "Major Modification"
    MINOR_MODIFICATION = "MINOR_MODIFICATION", "Minor Modification"
    NOT_SEGMENTED = "NOT_SEGMENTED", "Not Segmented"

class ContourModificationTypeChoices(models.Model):
    '''
    This is a model to store data about the contour modification type choices.
    This model will available as a many to many relationship to the RTStructureFileVOIData model.
    '''
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    modification_type = models.CharField(max_length=256,unique=True,null=True,blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)    
    
    def __str__(self):
        return self.modification_type
    
    class Meta:
        verbose_name = "Contour Modification Type Choice"
        verbose_name_plural = "Contour Modification Type Choices"

class RTStructureFileVOIData(models.Model):
    '''
    This is a model to store data about the RT structure file void data
    '''
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    rt_structure_file_import = models.ForeignKey(RTStructureFileImport,on_delete=models.CASCADE,null=True,blank=True)
    volume_name = models.CharField(max_length=256,null=True,blank=True,help_text="Name of the volume")
    contour_modification = models.CharField(max_length=256,choices=ContourModificationChoices.choices,default=ContourModificationChoices.NO_MODIFICATION, null=True, blank=True,help_text="Contour modification required. If the contour was blank choose Not Segmented. Note that the definiton of major modification can include scenarios where you had to completely redraw the structure, where there was significant risk of underdose to the target or overdose to the organs at risk due to error, and any modification in an axial plane exceeding 1 cm. Additionally any other criteria that you feel made you label this as major modification is also fine as long as that is documented in the comments. ")
    contour_modification_type = models.ManyToManyField(ContourModificationTypeChoices,blank=True,help_text="Type of contour modification made. You can select multiple options here or leave blank if this is not applicable. To add a new type of modification please contact your Administrator. ")
    contour_modification_comments = models.TextField(null=True,blank=True,help_text="Comments about the contour modification.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)    
    
    def __str__(self):
        return self.rt_structure_file_import.deidentified_rt_structure_file_path or self.rt_structure_file_import.reidentified_rt_structure_file_path or f"RTStruct Import {self.id}"  

    class Meta:
        verbose_name = "RT Structure File VOI Data"
        verbose_name_plural = "RT Structure File VOI Data"



class ChainExecutionLock(models.Model):
    '''
    Model to handle atomic locking for DICOM processing chain execution
    Prevents multiple chains from running simultaneously
    '''
    id = models.AutoField(primary_key=True)
    lock_name = models.CharField(max_length=100, unique=True, help_text="Name of the lock")
    chain_id = models.CharField(max_length=100, help_text="Celery chain ID")
    started_at = models.DateTimeField(auto_now_add=True)
    started_by = models.CharField(max_length=100, help_text="Task or process that acquired the lock")
    expires_at = models.DateTimeField(help_text="When this lock expires")
    status = models.CharField(max_length=50, default='running', help_text="Chain execution status")
    
    def __str__(self):
        return f"Lock: {self.lock_name} - Chain: {self.chain_id}"
    
    def is_expired(self):
        """Check if the lock has expired"""
        return timezone.now() > self.expires_at
    
    class Meta:
        verbose_name = "Chain Execution Lock"
        verbose_name_plural = "Chain Execution Locks"

class Statistics(models.Model):
    '''
    Model to store statistics about the DICOM processing chain
    '''
    id = models.AutoField(primary_key=True)
    parameter_name = models.CharField(max_length=256, help_text="Name of the parameter")
    parameter_value = models.CharField(max_length=256, help_text="Value of the parameter")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return self.parameter_name
    
    class Meta:
        verbose_name = "Statistics"
        verbose_name_plural = "Statistics"  