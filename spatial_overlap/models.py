from django.db import models
from django.contrib.auth.models import User


# Create your models here.

class RTStructureSetFile(models.Model):
    '''
    Model to store RT Structure Set files information.
    This model stores metadata about RT Structure Set files uploaded by users.
    It includes patient information, DICOM identifiers, and file references.
    
    IMPORTANT: Field Definitions
    - study_instance_uid: Study UID of the RT Structure itself
    - series_instance_uid: Series UID of the RT Structure itself (NOT the image series)
    - sop_instance_uid: SOP Instance UID of the RT Structure file
    - referenced_series_instance_uid: Series UID of the image series (CT/MR) that this RT Structure references
    
    The referenced_series_instance_uid is used to find the DICOM image instances in the database
    for spatial overlap calculations.
    '''
    
    id = models.AutoField(primary_key=True)
    patient_name = models.CharField(max_length=255, verbose_name="Patient Name in the RT StructureSet File")
    patient_id = models.CharField(max_length=255, verbose_name="Patient ID in the RT StructureSet File")
    study_instance_uid = models.CharField(max_length=255, verbose_name="Study Instance UID for the RT StructureSet File")
    series_instance_uid = models.CharField(max_length=255, verbose_name="Series Instance UID for the RT StructureSet File")
    sop_instance_uid = models.CharField(max_length=255, verbose_name="SOP Instance UID for the RT StructureSet File")
    structure_set_label = models.CharField(max_length=255, verbose_name="StructureSet Label for the RT StructureSet File")
    referenced_series_instance_uid = models.CharField(max_length=255, verbose_name="Referenced Series Instance UID for the RT StructureSet File")
    rtstructure_file_path = models.CharField(max_length=512, verbose_name="RT Structure File Path", null=True, blank=True, help_text="Path to RT Structure file in working directory")
    working_directory = models.CharField(max_length=512, verbose_name="Working Directory", null=True, blank=True, help_text="Directory containing DICOM images and RT Structure files")
    structure_set_date = models.DateField(null=True, blank=True, verbose_name="Structure Set Date from RT Structure Set File")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At", null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At", null=True, blank=True)

    class Meta:
        db_table = 'rt_structure_set_files'
        verbose_name = 'RT Structure Set File'
        verbose_name_plural = 'RT Structure Set Files'
        ordering = ['-created_at']


    def __str__(self):
        return f"RT Structure Set File - {self.structure_set_label}"


class RTStructureSetVOI(models.Model):
    """
    Model to store information about the ROIs in the RT Structure Set file.
    """
    id = models.AutoField(primary_key=True)
    rtstructure_set_file = models.ForeignKey(RTStructureSetFile, on_delete=models.CASCADE, related_name='vois', verbose_name="RT Structure Set File")
    roi_name = models.CharField(max_length=255, verbose_name="ROI Name")
    roi_description = models.CharField(max_length=255, verbose_name="ROI Description")
    roi_volume = models.FloatField(verbose_name="ROI Volume",null=True,blank=True)
    roi_number = models.IntegerField(verbose_name="ROI Number",null=True,blank=True)
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At", null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At", null=True, blank=True)

    class Meta:
        db_table = 'rt_structure_set_vois'
        verbose_name = 'RT Structure Set VOI'
        verbose_name_plural = 'RT Structure Set VOIs'
        ordering = ['-created_at']

    def __str__(self):
        return f"RT Structure Set VOI - {self.roi_name}"


class RTStructureFileComparison(models.Model):
    """
    Model to store information on the RTStructureSet files being compared. The order of the files does not matter but the combination of files is unique.
    """
    id = models.AutoField(primary_key=True)
    first_rtstructure = models.ForeignKey(RTStructureSetVOI, on_delete=models.CASCADE, related_name='first_rt_structure', verbose_name="First RT Structure Set File")
    second_rtstructure = models.ForeignKey(RTStructureSetVOI, on_delete=models.CASCADE, related_name='second_rt_structure', verbose_name="Second RT Structure Set File")
    user = models.ForeignKey('auth.User', on_delete=models.CASCADE, verbose_name="User who created this comparison", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At", null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At", null=True, blank=True)

    class Meta:
        db_table = 'rt_structure_file_comparisons'
        verbose_name = 'RT Structure File Comparison'
        verbose_name_plural = 'RT Structure File Comparisons'
        ordering = ['-created_at']

    def __str__(self):
        return f"Comparison between {self.first_rtstructure} and {self.second_rtstructure}"
    
class ComparisionTypeChoices(models.TextChoices):
    DSC = 'dsc', 'Dice Similarity Coefficient'
    JSC = 'jsc', 'Jaccard Similarity Coefficient'
    HD95 = 'hd95', 'Hausdorff Distance 95th percentile'
    MSD = 'msd', 'Mean Surface Distance'
    APL = 'apl', 'Added Path Length'
    MDC = 'mdc', 'Mean Distance to Conformity'
    UMDC = 'umdc', 'Undercontouring Mean Distance to Conformity'
    OMDC = 'omdc', 'Overcontouring Mean Distance to Conformity'
    VOE = 'voe', 'Volume Overlap Error'
    VI = 'vi', 'Variation of Information'
    CS = 'cs', 'Cosine Similarity'

class ComparisonResult(models.Model):
    '''
    This model will store information about the comparison results for different metrics.
    '''
    comparison = models.ForeignKey(RTStructureFileComparison, on_delete=models.CASCADE, verbose_name="RT Structure File Comparison")
    comparision_type = models.CharField(max_length=20, choices=ComparisionTypeChoices.choices, verbose_name="Comparison Type")
    result_value = models.FloatField(verbose_name="Result Value")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At", null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At", null=True, blank=True)
    
    class Meta:
        db_table = 'rt_structure_file_comparison_results'
        verbose_name = 'RT Structure File Comparison Result'
        verbose_name_plural = 'RT Structure File Comparison Results'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.comparision_type} result: {self.result_value}"
    
    

    