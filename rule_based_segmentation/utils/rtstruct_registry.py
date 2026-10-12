"""Register RT Structure Set files from disk into RTStructureSetFile records."""

import logging
from typing import Optional

import pydicom

from spatial_overlap.models import RTStructureSetFile
from dicom_handler.utils.log_masking import mask_sensitive_data

logger = logging.getLogger(__name__)

RTSTRUCT_SOP_CLASS_UID = "1.2.840.10008.5.1.4.1.1.481.3"


def is_rtstruct_dataset(ds: pydicom.Dataset) -> bool:
    """Return True if the dataset is an RT Structure Set."""
    modality = str(getattr(ds, "Modality", "")).upper()
    sop_class = str(getattr(ds, "SOPClassUID", ""))
    return modality == "RTSTRUCT" or sop_class == RTSTRUCT_SOP_CLASS_UID


def extract_referenced_series_uid(ds: pydicom.Dataset) -> str:
    """Extract the image SeriesInstanceUID referenced by an RTStruct dataset."""
    for ref_frame in getattr(ds, "ReferencedFrameOfReferenceSequence", []) or []:
        for ref_study in getattr(ref_frame, "RTReferencedStudySequence", []) or []:
            for ref_series in getattr(ref_study, "RTReferencedSeriesSequence", []) or []:
                series_uid = getattr(ref_series, "SeriesInstanceUID", None)
                if series_uid:
                    return str(series_uid)
    return ""


def register_rtstruct_file(file_path: str, ds: Optional[pydicom.Dataset] = None) -> RTStructureSetFile:
    """
    Create an RTStructureSetFile record for an RTStruct file already on disk.

    Used for files received via DICOM networking (C-STORE / C-MOVE / C-GET)
    where no upload record exists yet. If a record already exists for the same
    SOPInstanceUID, it is returned instead of creating a duplicate.
    """
    if ds is None:
        ds = pydicom.dcmread(file_path, stop_before_pixels=True, force=True)

    sop_uid = str(getattr(ds, "SOPInstanceUID", ""))
    if sop_uid:
        existing = RTStructureSetFile.objects.filter(sop_instance_uid=sop_uid).first()
        if existing:
            logger.info(
                f"RTStruct {mask_sensitive_data(sop_uid, 'uid')} already registered as "
                f"RTStructureSetFile {existing.id}, reusing record"
            )
            return existing

    record = RTStructureSetFile.objects.create(
        patient_name=str(getattr(ds, "PatientName", "")),
        patient_id=str(getattr(ds, "PatientID", "")),
        study_instance_uid=str(getattr(ds, "StudyInstanceUID", "")),
        series_instance_uid=str(getattr(ds, "SeriesInstanceUID", "")),
        sop_instance_uid=sop_uid,
        structure_set_label=str(getattr(ds, "StructureSetLabel", "")),
        referenced_series_instance_uid=extract_referenced_series_uid(ds),
        rtstructure_file_path=file_path,
        working_directory=None,
    )
    logger.info(
        f"Registered RTStruct {mask_sensitive_data(file_path, 'file_path')} as RTStructureSetFile {record.id}"
    )
    return record
