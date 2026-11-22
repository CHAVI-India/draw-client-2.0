"""Build the rule-based OUTPUT structure set.

Produces a NEW RTSTRUCT DICOM file (new SOP/Series UIDs) that contains the
original structures plus the rule-generated ones, and registers it as a new
RTStructureSetFile with per-ROI approval:

  * original ROIs (untouched by any rule) inherit the INPUT file's DICOM
    Approval Module (300E) status / review date / review time / reviewer;
  * ROIs created (CREATE_NEW) or replaced (REPLACE_EXISTING) by rules are
    UNAPPROVED (a modified structure must be re-reviewed).

The new file's own file-level approval (300E,0002) is UNAPPROVED, since the
set as a whole now contains unreviewed content. The input file is never
modified.
"""

import logging
import os
from datetime import date, datetime
from typing import Dict, List

from spatial_overlap.models import RTStructureSetFile, RTStructureSetVOI

from .rtstruct_io import read_approval_info

logger = logging.getLogger(__name__)


def _new_output_path(input_path: str, job_id) -> str:
    """Deterministic, job-unique path in the same directory as the input."""
    directory = os.path.dirname(input_path) or "."
    stem = os.path.splitext(os.path.basename(input_path))[0]
    return os.path.join(directory, f"{stem}__rbs_{str(job_id)[:8]}.dcm")


def _set_file_approval_unapproved(ds) -> None:
    """Set the new file's file-level Approval Module to UNAPPROVED."""
    ds.ApprovalStatus = "UNAPPROVED"  # (300E,0002)
    for attr in ("ReviewDate", "ReviewTime", "ReviewerName"):  # (300E,0004/0005/0008)
        if hasattr(ds, attr):
            delattr(ds, attr)


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(str(value).strip(), "%Y%m%d").date()
    except (ValueError, TypeError):
        return None


def _parse_time(value):
    if not value:
        return None
    try:
        return datetime.strptime(str(value).strip(), "%H%M%S").time()
    except (ValueError, TypeError):
        return None


def _referenced_series_uid(ds) -> str:
    """Extract the referenced image series UID from an RTStruct dataset."""
    for ref_frame in getattr(ds, "ReferencedFrameOfReferenceSequence", []) or []:
        for ref_study in getattr(ref_frame, "RTReferencedStudySequence", []) or []:
            for ref_series in getattr(ref_study, "RTReferencedSeriesSequence", []) or []:
                uid = getattr(ref_series, "SeriesInstanceUID", None)
                if uid:
                    return str(uid)
    return ""


def build_output_structure_set(
    rtstruct_builder,
    input_path: str,
    job,
    created_rois: List[str],
    replaced_rois: List[str],
) -> Dict:
    """Save `rtstruct_builder` to a NEW file and register it as a new structure set.

    `rtstruct_builder` must already have new SOP/Series UIDs assigned (call
    `regenerate_instance_uids` first) and contain all ROIs (original + new).
    `input_path` is used only to locate the output directory and to read the
    input file's approval information.

    Returns a summary dict:
      {"new_path", "sop_instance_uid", "series_instance_uid",
       "record_id", "new_rois", "preserved_rois"}
    """
    ds = rtstruct_builder.ds
    sop_uid = str(ds.SOPInstanceUID)
    series_uid = str(ds.SeriesInstanceUID)
    study_uid = str(getattr(ds, "StudyInstanceUID", ""))
    patient_name = str(getattr(ds, "PatientName", ""))
    patient_id = str(getattr(ds, "PatientID", ""))
    original_label = str(getattr(ds, "StructureSetLabel", "") or "").strip()

    # Idempotent label: re-running finalize on an already-written output must
    # not stack another " (RBS)" suffix.
    if original_label.endswith(" (RBS)") or original_label == "RBS output":
        label = original_label
    elif original_label:
        label = f"{original_label} (RBS)"
    else:
        label = "RBS output"
    ds.StructureSetLabel = label

    # The new file as a whole is UNAPPROVED (it contains new/reviewed content).
    _set_file_approval_unapproved(ds)

    new_path = _new_output_path(input_path, job.id)
    os.makedirs(os.path.dirname(new_path) or ".", exist_ok=True)
    rtstruct_builder.save(new_path)

    # Per-ROI approval: untouched original ROIs inherit the input file's 300E
    # approval; created/replaced ROIs are UNAPPROVED.
    approval = read_approval_info(input_path)
    inherited_status = approval["status"] or "UNAPPROVED"
    inherited_date = _parse_date(approval["review_date"])
    inherited_time = _parse_time(approval["review_time"])
    inherited_reviewer = approval["reviewer_name"]

    # Idempotency: a redelivered finalize must not create a duplicate record.
    existing = RTStructureSetFile.objects.filter(sop_instance_uid=sop_uid).first()
    if existing is not None:
        record = existing
        record.vois.all().delete()
    else:
        record = RTStructureSetFile.objects.create(
            patient_name=patient_name,
            patient_id=patient_id,
            study_instance_uid=study_uid,
            series_instance_uid=series_uid,
            sop_instance_uid=sop_uid,
            structure_set_label=label,
            referenced_series_instance_uid=_referenced_series_uid(ds),
            structure_set_date=date.today(),
            rtstructure_file_path=new_path,
            working_directory=os.path.dirname(new_path) or None,
        )

    created = set(created_rois)
    replaced = set(replaced_rois)
    new_rois: List[str] = []
    preserved_rois: List[str] = []

    for roi in getattr(ds, "StructureSetROISequence", []) or []:
        name = str(getattr(roi, "ROIName", "") or "").strip()
        if not name:
            continue
        description = str(getattr(roi, "ROIDescription", "") or "")
        number = int(getattr(roi, "ROINumber", 0))
        if name in created or name in replaced:
            RTStructureSetVOI.objects.create(
                rtstructure_set_file=record,
                roi_name=name,
                roi_description=description,
                roi_number=number,
                approval_status="UNAPPROVED",
            )
            new_rois.append(name)
        else:
            RTStructureSetVOI.objects.create(
                rtstructure_set_file=record,
                roi_name=name,
                roi_description=description,
                roi_number=number,
                approval_status=inherited_status,
                review_date=inherited_date,
                review_time=inherited_time,
                reviewer_name=inherited_reviewer,
            )
            preserved_rois.append(name)

    logger.info(
        f"Output structure set {record.id}: {len(new_rois)} new, "
        f"{len(preserved_rois)} preserved -> {new_path}"
    )
    return {
        "new_path": new_path,
        "sop_instance_uid": sop_uid,
        "series_instance_uid": series_uid,
        "record_id": record.id,
        "new_rois": new_rois,
        "preserved_rois": preserved_rois,
    }
