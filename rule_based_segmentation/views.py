"""Views for rule-based segmentation."""

import json
import logging
import os
import shutil
import tempfile
from datetime import datetime
from uuid import UUID

import pydicom
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.files.uploadedfile import UploadedFile
from django.db import models
from django.http import FileResponse, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST
from rt_utils import RTStructBuilder

from dicom_handler.models import DICOMSeries, RTStructureFileImport
from dicom_handler.utils.log_masking import mask_sensitive_data
from spatial_overlap.models import RTStructureSetFile

from .models import (
    AvoidMarginRuleConfig,
    BooleanExpressionNode,
    CleanupRuleConfig,
    CropBoundary,
    CropRuleConfig,
    ExpandSubtractRuleConfig,
    IntensityRange,
    IntensityRuleConfig,
    MarginRuleConfig,
    OverlapOther,
    OverlapRuleConfig,
    PipelineRule,
    RingRuleConfig,
    SegmentationJob,
    SegmentationPipeline,
)
from .utils.dicom_image_importer import (
    import_uploaded_image_series,
    sanitize_filename_component,
)
from dicom_handler.utils.safe_paths import validate_stored_path
from .utils.job_service import MissingImageSeriesError, create_segmentation_job
from .utils.rtstruct_io import _backup_rtstruct
from .utils.pipeline_persistence import (
    parse_pipeline_data,
    pipeline_data_from_pipeline,
    save_pipeline_from_dict,
)

logger = logging.getLogger(__name__)


@login_required
def pipeline_list(request):
    """List reusable segmentation pipelines."""
    user = request.user
    pipelines = SegmentationPipeline.objects.filter(
        models.Q(created_by=user) | models.Q(is_public=True)
    ).order_by("-created_at")
    return render(request, "rule_based_segmentation/pipeline_list.html", {"pipelines": pipelines})


@login_required
def pipeline_create(request):
    """Create a new segmentation pipeline."""
    if request.method == "POST":
        data = parse_pipeline_data(request.POST)
        if data:
            try:
                pipeline = save_pipeline_from_dict(data, request.user)
                return redirect("rule_based_segmentation:pipeline_detail", pipeline_id=pipeline.id)
            except ValueError as e:
                return _render_pipeline_form(request, error=str(e))
    return _render_pipeline_form(request)


@login_required
def pipeline_edit(request, pipeline_id):
    """Edit an existing pipeline."""
    pipeline = get_object_or_404(SegmentationPipeline, id=pipeline_id)
    if request.method == "POST":
        data = parse_pipeline_data(request.POST)
        if data:
            try:
                pipeline = save_pipeline_from_dict(data, request.user, pipeline=pipeline)
                return redirect("rule_based_segmentation:pipeline_detail", pipeline_id=pipeline.id)
            except ValueError as e:
                return _render_pipeline_form(request, pipeline, error=str(e))
    return _render_pipeline_form(request, pipeline)


def _render_pipeline_form(request, pipeline=None, error=None):
    pipeline_data = pipeline_data_from_pipeline(pipeline)
    return render(
        request,
        "rule_based_segmentation/pipeline_form.html",
        {
            "pipeline": pipeline,
            "pipeline_data": pipeline_data,
            "error": error,
            "roi_name_max_length": PipelineRule._meta.get_field("name").max_length,
            # Single source of truth for the rule-type dropdown: read off the
            # model so the UI never drifts from what the backend accepts.
            "rule_type_choices": PipelineRule.RULE_TYPE_CHOICES,
            "js_cache_bust": _builder_js_cache_bust(),
        },
    )


def _builder_js_cache_bust() -> str:
    """Short content hash of the pipeline builder JS, used as a cache-buster.

    Appended to the static <script> URL so that any change to the builder JS
    automatically invalidates the browser cache (no manual version bumps).
    Returns "" if the file is missing (dev / edge case).
    """
    import hashlib

    js_path = os.path.join(
        settings.STATICFILES_DIRS[0], "js", "rule_based_pipeline_builder.js"
    )
    try:
        with open(js_path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()[:16]
    except OSError:
        return ""


def _rtstruct_choice_label(rtstruct):
    """Build a human-readable label for an uploaded RTStruct selection option."""
    parts = [
        rtstruct.patient_name or "Unknown Patient",
        rtstruct.structure_set_label or "RTStruct",
    ]
    if rtstruct.structure_set_date:
        parts.append(str(rtstruct.structure_set_date))
    elif rtstruct.created_at:
        parts.append(rtstruct.created_at.strftime("%Y-%m-%d"))
    return " - ".join(parts)


def _import_rtstruct_choice_label(rt_import):
    """Build a human-readable label for an auto-segmented RTStruct from DB fields."""
    series = rt_import.deidentified_series_instance_uid
    patient = getattr(getattr(series, "study", None), "patient", None) if series else None
    patient_name = getattr(patient, "patient_name", None) or "Unknown Patient"
    patient_id = getattr(patient, "patient_id", None) or ""
    if series:
        description = series.series_description or "Auto-segmented"
    else:
        file_path = (
            rt_import.reidentified_rt_structure_file_path
            or rt_import.deidentified_rt_structure_file_path
            or ""
        )
        description = os.path.basename(file_path) if file_path else "Auto-segmented"

    parts = [f"{patient_name} ({patient_id})" if patient_id else patient_name, description]
    if rt_import.created_at:
        parts.append(rt_import.created_at.strftime("%Y-%m-%d"))
    return " - ".join(parts)


@login_required
def pipeline_detail(request, pipeline_id):
    """Show pipeline details."""
    pipeline = get_object_or_404(SegmentationPipeline, id=pipeline_id)
    return render(request, "rule_based_segmentation/pipeline_detail.html", {"pipeline": pipeline})


@login_required
def pipeline_delete(request, pipeline_id):
    """Delete a pipeline."""
    pipeline = get_object_or_404(SegmentationPipeline, id=pipeline_id)
    if request.method == "POST":
        pipeline.delete()
        return redirect("rule_based_segmentation:pipeline_list")
    return render(
        request,
        "rule_based_segmentation/pipeline_detail.html",
        {"pipeline": pipeline, "confirm_delete": True},
    )


@login_required
def pipeline_duplicate(request, pipeline_id):
    """Duplicate an existing pipeline."""
    pipeline = get_object_or_404(SegmentationPipeline, id=pipeline_id)
    pipeline.pk = None
    pipeline.name = f"{pipeline.name} (Copy)"
    pipeline.created_by = request.user
    pipeline.save()

    for rule in SegmentationPipeline.objects.get(id=pipeline_id).rules.all():
        _duplicate_rule(pipeline, rule)

    return redirect("rule_based_segmentation:pipeline_edit", pipeline_id=pipeline.id)


JOB_LIST_PAGE_SIZE = 15


@login_required
def job_list(request):
    """List segmentation jobs with filtering and pagination."""
    jobs = (
        SegmentationJob.objects.filter(created_by=request.user)
        .select_related(
            "pipeline",
            "input_upload",
            "input_import",
            "input_import__deidentified_series_instance_uid",
            "input_import__deidentified_series_instance_uid__study__patient",
        )
        .order_by("-created_at")
    )

    status = request.GET.get("status", "").strip()
    search = request.GET.get("search", "").strip()
    pipeline_id = request.GET.get("pipeline", "").strip()

    if status in dict(SegmentationJob.STATUS_CHOICES):
        jobs = jobs.filter(status=status)
    if pipeline_id:
        jobs = jobs.filter(pipeline_id=pipeline_id)
    if search:
        series_prefix = "input_import__deidentified_series_instance_uid__"
        jobs = jobs.filter(
            models.Q(pipeline__name__icontains=search)
            | models.Q(input_upload__patient_name__icontains=search)
            | models.Q(input_upload__patient_id__icontains=search)
            | models.Q(input_upload__structure_set_label__icontains=search)
            | models.Q(**{f"{series_prefix}study__patient__patient_name__icontains": search})
            | models.Q(**{f"{series_prefix}study__patient__patient_id__icontains": search})
            | models.Q(**{f"{series_prefix}series_description__icontains": search})
        ).distinct()

    from django.core.paginator import Paginator

    paginator = Paginator(jobs, JOB_LIST_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))

    rows = [
        {
            "job": job,
            "patient": _job_patient_label(job),
            "structure": _job_structure_label(job),
        }
        for job in page_obj.object_list
    ]

    pipelines = SegmentationPipeline.objects.filter(
        models.Q(created_by=request.user) | models.Q(is_public=True)
    ).order_by("name")

    return render(
        request,
        "rule_based_segmentation/job_list.html",
        {
            "page_obj": page_obj,
            "rows": rows,
            "pipelines": pipelines,
            "status_choices": SegmentationJob.STATUS_CHOICES,
            "filters": {
                "status": status,
                "search": search,
                "pipeline": pipeline_id,
            },
        },
    )


def _job_patient_label(job):
    """Human-readable patient label for a segmentation job."""
    if job.input_upload:
        up = job.input_upload
        name = up.patient_name or "Unknown Patient"
        return f"{name} ({up.patient_id})" if up.patient_id else name
    import_model = job.input_import
    if import_model and import_model.deidentified_series_instance_uid:
        patient = import_model.deidentified_series_instance_uid.study.patient
        name = patient.patient_name or "Unknown Patient"
        return f"{name} ({patient.patient_id})" if patient.patient_id else name
    return "Unknown Patient"


def _job_structure_label(job):
    """Human-readable structure set label for a segmentation job."""
    if job.input_upload:
        up = job.input_upload
        label = up.structure_set_label or "RTStruct"
        if up.structure_set_date:
            return f"{label} ({up.structure_set_date})"
        return label
    import_model = job.input_import
    if import_model and import_model.deidentified_series_instance_uid:
        series = import_model.deidentified_series_instance_uid
        return series.series_description or "Auto-segmented"
    return "—"


@login_required
def job_detail(request, job_id):
    """Show job details."""
    job = get_object_or_404(SegmentationJob, id=job_id)
    return render(request, "rule_based_segmentation/job_status.html", {"job": job})


@login_required
def job_status(request, job_id):
    """Return job status as JSON for polling (includes per-rule step progress)."""
    job = get_object_or_404(SegmentationJob, id=job_id)
    steps = job.steps.select_related("rule").all()
    running = next((s for s in steps if s.status == "RUNNING"), None)
    return JsonResponse(
        {
            "id": str(job.id),
            "status": job.status,
            "error": job.error_message,
            "summary": job.result_summary,
            "output_file_path": job.output_file_path,
            "backup_file_path": job.backup_file_path,
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            "current_step": running.order if running else None,
            "steps": [
                {
                    "order": s.order,
                    "rule_name": s.rule.name,
                    "status": s.status,
                    "error": s.error,
                    "output_roi_name": s.output_roi_name,
                }
                for s in steps
            ],
        }
    )


@login_required
@require_POST
def job_retry(request, job_id):
    """Re-enqueue the remaining chain steps of a failed (or stuck pending) job."""
    job = get_object_or_404(SegmentationJob, id=job_id)
    if job.status not in ("FAILED", "PENDING"):
        return JsonResponse(
            {"error": "Only failed or pending jobs can be retried."}, status=409
        )
    from .tasks import resume_job

    resume_job(job)
    return JsonResponse({"ok": True})


@login_required
def download_output(request, job_id):
    """Download the modified RTStruct output file."""
    job = get_object_or_404(SegmentationJob, id=job_id)
    if not job.output_file_path or not os.path.exists(job.output_file_path):
        return JsonResponse({"error": "Output file not available"}, status=404)
    return FileResponse(
        open(job.output_file_path, "rb"),
        as_attachment=True,
        filename=os.path.basename(job.output_file_path),
    )


@login_required
def download_rtstruct(request, rtstruct_id):
    """Download an RTStructureFileImport file (works for both auto-segmented and rule-based outputs)."""
    rtstruct = get_object_or_404(RTStructureFileImport, id=rtstruct_id)
    file_path = (
        rtstruct.reidentified_rt_structure_file_path
        or rtstruct.deidentified_rt_structure_file_path
    )
    if not file_path or not os.path.exists(file_path):
        return JsonResponse({"error": "File not found"}, status=404)
    return FileResponse(
        open(file_path, "rb"),
        as_attachment=True,
        filename=os.path.basename(file_path),
    )


@login_required
def bulk_download_rtstructs(request):
    """Download multiple RTStructureFileImport files as a zip archive."""
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    ids = request.POST.getlist("ids") or request.POST.get("ids", "").split(",")
    ids = [i.strip() for i in ids if i.strip()]
    if not ids:
        return JsonResponse({"error": "No structures selected"}, status=400)

    rtstructs = RTStructureFileImport.objects.filter(id__in=ids)
    if not rtstructs.exists():
        return JsonResponse({"error": "No valid structures found"}, status=404)

    import zipfile
    import io

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for rtstruct in rtstructs:
            file_path = (
                rtstruct.reidentified_rt_structure_file_path
                or rtstruct.deidentified_rt_structure_file_path
            )
            if file_path and os.path.exists(file_path):
                arcname = os.path.basename(file_path)
                zip_file.write(file_path, arcname)

    zip_buffer.seek(0)
    response = HttpResponse(zip_buffer.read(), content_type="application/zip")
    response["Content-Disposition"] = 'attachment; filename="rtstructures.zip"'
    return response


@login_required
def select_rtstruct(request):
    """Select an RTStruct source before running a pipeline."""
    uploaded_rtstructs = RTStructureSetFile.objects.all().order_by("-created_at")[:50]
    imported_rtstructs = RTStructureFileImport.objects.all().order_by("-created_at")[:50]
    return render(
        request,
        "rule_based_segmentation/select_rtstruct.html",
        {
            "uploaded_rtstructs": uploaded_rtstructs,
            "imported_rtstructs": imported_rtstructs,
        },
    )


@login_required
def job_create(request, pipeline_id):
    """Create and enqueue a segmentation job."""
    pipeline = get_object_or_404(SegmentationPipeline, id=pipeline_id)

    if request.method == "POST":
        input_type = request.POST.get("input_type")
        input_value = request.POST.get("input_id", "")

        try:
            if input_type == "UPLOAD_NEW":
                uploaded_file = request.FILES.get("rtstruct_file")
                if not uploaded_file:
                    return _render_job_create(request, pipeline, error="Please select an RTStruct file.")
                input_type, input_id = _save_uploaded_rtstruct(uploaded_file, request.user)
            elif input_type == "EXISTING":
                if not input_value or ":" not in input_value:
                    return _render_job_create(request, pipeline, error="Please select an existing RTStruct.")
                source, input_id = input_value.split(":", 1)
                input_type = source.upper()
            else:
                return _render_job_create(request, pipeline, error="Please select an input type.")

            # Pre-check that the referenced image series exists before creating the job.
            rtstruct_path, series_uid = _resolve_rtstruct_and_series(input_type, input_id)

            # Validate that all structures referenced by the pipeline exist in the input RTStruct.
            missing = _validate_pipeline_against_rtstruct(pipeline, rtstruct_path)
            if missing:
                raise ValueError(
                    f"The selected RTStruct is missing structures required by this pipeline: {', '.join(missing)}. "
                    "Please select an RTStruct that contains these structures or adjust the pipeline."
                )

            series_missing = not DICOMSeries.objects.filter(
                series_instance_uid=series_uid
            ).exists()
            files_missing = False
            if not series_missing:
                files_missing = _series_files_missing(series_uid)

            if series_missing or files_missing:
                request.session["pending_rtstruct_path"] = rtstruct_path
                request.session["pending_series_uid"] = series_uid
                request.session["pending_pipeline_id"] = str(pipeline.id)
                request.session["pending_input_type"] = input_type
                request.session["pending_input_id"] = input_id
                request.session["pending_files_missing"] = files_missing
                request.session["pending_destination_node_id"] = request.POST.get(
                    "destination_node_id", ""
                )
                return redirect("rule_based_segmentation:upload_image_series")

            destination_node = _resolve_destination_node(
                request.POST.get("destination_node_id")
            )
            job = create_segmentation_job(
                pipeline, input_type, input_id, request.user,
                destination_node=destination_node,
            )
            _clear_pending_session(request)
            return redirect("rule_based_segmentation:job_detail", job_id=job.id)
        except Exception as e:
            logger.error(f"Failed to create segmentation job: {e}", exc_info=True)
            return _render_job_create(request, pipeline, error=str(e))

    return _render_job_create(request, pipeline)


@login_required
def select_series_for_upload(request):
    """Upload missing CT/MR/PT image series for a pending job."""
    job_id = request.GET.get("job_id") or request.POST.get("job_id")
    expected_series_uid = request.GET.get("expected_series_uid")
    error = request.GET.get("error")

    if request.method == "POST":
        uploaded_files = request.FILES.getlist("dicom_files")
        if not uploaded_files:
            return render(
                request,
                "rule_based_segmentation/upload_image_series.html",
                {
                    "error": "Please select DICOM image files.",
                    "job_id": job_id,
                    "expected_series_uid": expected_series_uid,
                },
            )

        try:
            series = import_uploaded_image_series(uploaded_files, expected_series_uid)

            # If there is a pending pipeline run, create the job now.
            pending_pipeline_id = request.session.get("pending_pipeline_id")
            if pending_pipeline_id:
                pipeline = get_object_or_404(
                    SegmentationPipeline, id=pending_pipeline_id
                )
                input_type = request.session.get("pending_input_type")
                input_id = request.session.get("pending_input_id")
                destination_node = _resolve_destination_node(
                    request.session.get("pending_destination_node_id")
                )
                job = create_segmentation_job(
                    pipeline, input_type, input_id, request.user,
                    destination_node=destination_node,
                )
                _clear_pending_session(request)
                return redirect("rule_based_segmentation:job_detail", job_id=job.id)

            if job_id:
                job = get_object_or_404(SegmentationJob, id=job_id)
                job.dicom_series = series
                job.save(update_fields=["dicom_series"])
                from .tasks import resume_job

                resume_job(job)
                return redirect("rule_based_segmentation:job_detail", job_id=job.id)

            return redirect("rule_based_segmentation:pipeline_list")
        except Exception as e:
            logger.error(f"Failed to import image series: {e}", exc_info=True)
            return render(
                request,
                "rule_based_segmentation/upload_image_series.html",
                {
                    "error": str(e),
                    "job_id": job_id,
                    "expected_series_uid": expected_series_uid,
                },
            )

    files_missing = request.session.get("pending_files_missing", False)
    return render(
        request,
        "rule_based_segmentation/upload_image_series.html",
        {
            "job_id": job_id,
            "expected_series_uid": expected_series_uid,
            "error": error,
            "files_missing": files_missing,
        },
    )


RTSTRUCT_SEARCH_PAGE_SIZE = 20


def _paginate_list(queryset, page, page_size=RTSTRUCT_SEARCH_PAGE_SIZE):
    """Return (items, has_more) for a 1-based page without a separate count query."""
    start = (page - 1) * page_size
    items = list(queryset[start : start + page_size + 1])
    return items[:page_size], len(items) > page_size


@login_required
def api_search_rtstructs(request):
    """Paginated Select2-compatible search across uploaded and auto-segmented RTStructs."""
    try:
        page = max(1, int(request.GET.get("page", 1)))
    except (TypeError, ValueError):
        page = 1
    query = (request.GET.get("q") or "").strip()

    uploads = RTStructureSetFile.objects.all().order_by("-created_at")
    if query:
        uploads = uploads.filter(
            models.Q(patient_name__icontains=query)
            | models.Q(patient_id__icontains=query)
            | models.Q(structure_set_label__icontains=query)
        )
    uploads_page, uploads_more = _paginate_list(uploads, page)

    series_prefix = "deidentified_series_instance_uid__"
    imports = (
        RTStructureFileImport.objects.select_related(
            f"{series_prefix}study__patient"
        )
        .all()
        .order_by("-created_at")
    )
    if query:
        imports = imports.filter(
            models.Q(**{f"{series_prefix}study__patient__patient_name__icontains": query})
            | models.Q(**{f"{series_prefix}study__patient__patient_id__icontains": query})
            | models.Q(**{f"{series_prefix}study__patient__deidentified_patient_id__icontains": query})
            | models.Q(**{f"{series_prefix}series_description__icontains": query})
            | models.Q(**{f"{series_prefix}study__study_description__icontains": query})
            | models.Q(reidentified_rt_structure_file_path__icontains=query)
            | models.Q(deidentified_rt_structure_file_path__icontains=query)
        )
    imports_page, imports_more = _paginate_list(imports, page)

    results = []
    upload_children = [
        {"id": f"upload:{r.id}", "text": _rtstruct_choice_label(r)}
        for r in uploads_page
    ]
    if upload_children:
        results.append({"text": "Uploaded", "children": upload_children})
    import_children = [
        {"id": f"import:{r.id}", "text": _import_rtstruct_choice_label(r)}
        for r in imports_page
    ]
    if import_children:
        results.append({"text": "Auto-segmented", "children": import_children})

    return JsonResponse(
        {"results": results, "pagination": {"more": uploads_more or imports_more}}
    )


@login_required
def api_get_structures(request):
    """Return ROI names from a selected RTStruct file."""
    rtstruct_id = request.GET.get("rtstruct_id")
    import_id = request.GET.get("import_id")

    rtstruct_path = None
    if rtstruct_id:
        rtstruct = get_object_or_404(RTStructureSetFile, id=rtstruct_id)
        rtstruct_path = rtstruct.rtstructure_file_path
    elif import_id:
        rtstruct = get_object_or_404(RTStructureFileImport, id=import_id)
        rtstruct_path = rtstruct.reidentified_rt_structure_file_path

    if not rtstruct_path or not os.path.exists(rtstruct_path):
        return JsonResponse({"structures": []})

    structures = _read_structures_from_rtstruct(rtstruct_path)
    return JsonResponse({"structures": structures})


def _read_structures_from_rtstruct(rtstruct_path: str):
    """Read ROI names, interpreted types and colors directly from an RTStruct DICOM file."""
    try:
        ds = pydicom.dcmread(rtstruct_path, stop_before_pixels=True, force=True)
    except Exception as e:
        logger.warning(f"Could not read structures from {mask_sensitive_data(rtstruct_path, 'file_path')}: {e}")
        return []

    # Build maps of observation interpreted type and display color by ROINumber.
    interpreted_types = {}
    if hasattr(ds, "RTROIObservationsSequence"):
        for obs in ds.RTROIObservationsSequence:
            roi_number = getattr(obs, "ReferencedROINumber", None)
            roi_type = getattr(obs, "RTROIInterpretedType", None)
            if roi_number is not None and roi_type:
                interpreted_types[int(roi_number)] = str(roi_type)

    roi_colors = {}
    if hasattr(ds, "ROIContourSequence"):
        for contour in ds.ROIContourSequence:
            roi_number = getattr(contour, "ReferencedROINumber", None)
            color = getattr(contour, "ROIDisplayColor", None)
            if roi_number is not None and color and len(color) >= 3:
                try:
                    roi_colors[int(roi_number)] = [int(c) for c in color[:3]]
                except (TypeError, ValueError):
                    pass

    structures = []
    if hasattr(ds, "StructureSetROISequence"):
        for roi in ds.StructureSetROISequence:
            roi_number = getattr(roi, "ROINumber", None)
            name = getattr(roi, "ROIName", None)
            if not name:
                continue
            roi_type = interpreted_types.get(int(roi_number), "") if roi_number else ""
            color = roi_colors.get(int(roi_number)) if roi_number else None
            structures.append({
                "value": str(name),
                "label": str(name),
                "roi_type": roi_type,
                "color": _rgb_list_to_hex(color) if color else None,
            })
    return structures


def _rgb_list_to_hex(rgb):
    """Convert a 3-element RGB list to a #RRGGBB hex string."""
    return "#" + "".join(f"{max(0, min(255, int(c))):02x}" for c in rgb)


RTSTRUCT_SOP_CLASS_UID = "1.2.840.10008.5.1.4.1.1.481.3"


@login_required
@require_POST
def api_upload_sample_rtstruct(request):
    """Upload an RTStruct file for structure discovery and return its structures."""
    uploaded_file = request.FILES.get("rtstruct_file")
    if not uploaded_file:
        return JsonResponse({"error": "No file provided"}, status=400)

    try:
        # Validate basic DICOM structure and SOP class before saving.
        _validate_uploaded_rtstruct(uploaded_file)
        input_type, input_id = _save_uploaded_rtstruct(uploaded_file, request.user)
        rtstruct = get_object_or_404(RTStructureSetFile, id=input_id)
        structures = _read_structures_from_rtstruct(rtstruct.rtstructure_file_path)
    except ValueError as e:
        logger.warning(f"Invalid uploaded RTStruct: {e}")
        return JsonResponse({"error": "Uploaded file is not a valid RT Structure Set."}, status=400)
    except Exception:
        logger.error("Failed to upload sample RTStruct", exc_info=True)
        return JsonResponse({"error": "Failed to upload the RT Structure file."}, status=400)

    return JsonResponse({
        "input_type": input_type,
        "input_id": input_id,
        "label": rtstruct.structure_set_label or str(rtstruct.id),
        "structures": structures,
    })


def _validate_uploaded_rtstruct(uploaded_file):
    """Validate that the uploaded file is a valid DICOM RT Structure Set."""
    try:
        ds = pydicom.dcmread(uploaded_file, stop_before_pixels=True, force=True)
    except Exception as e:
        raise ValueError(f"File is not a valid DICOM file: {e}")

    sop_class = getattr(
        ds, "SOPClassUID", getattr(ds.file_meta, "MediaStorageSOPClassUID", None)
    )
    if not sop_class or str(sop_class) != RTSTRUCT_SOP_CLASS_UID:
        raise ValueError("Uploaded file is not a DICOM RT Structure Set.")

    if not hasattr(ds, "StructureSetROISequence") or not ds.StructureSetROISequence:
        raise ValueError("RT Structure Set contains no ROIs.")

    # Reset file pointer so the file can be read again when saving.
    uploaded_file.seek(0)


@login_required
@require_POST
def api_validate_pipeline(request):
    """Validate that a pipeline's referenced structures exist in a target RTStruct."""
    pipeline_id = request.POST.get("pipeline_id")
    rtstruct_id = request.POST.get("rtstruct_id")
    import_id = request.POST.get("import_id")

    pipeline = get_object_or_404(SegmentationPipeline, id=pipeline_id)

    rtstruct_path = None
    if rtstruct_id:
        rtstruct = get_object_or_404(RTStructureSetFile, id=rtstruct_id)
        rtstruct_path = rtstruct.rtstructure_file_path
    elif import_id:
        rtstruct = get_object_or_404(RTStructureFileImport, id=import_id)
        rtstruct_path = rtstruct.reidentified_rt_structure_file_path

    if not rtstruct_path or not os.path.exists(rtstruct_path):
        return JsonResponse(
            {"valid": False, "missing_structures": [], "error": "RTStruct file not found"}
        )

    try:
        rtstruct = RTStructBuilder.create_from(
            dicom_series_path=os.path.dirname(rtstruct_path),
            rt_struct_path=rtstruct_path,
        )
        available = set(rtstruct.get_roi_names())
        missing = []

        for rule in pipeline.rules.all().order_by("order"):
            required = _collect_rule_structure_names(rule)
            missing.extend(sorted(required - available))
            # Every rule produces a named result that later rules may reference:
            # CREATE_NEW / REPLACE_EXISTING live in the RTStruct; INTERMEDIATE
            # lives in memory. Add the name to the running available set either way.
            available.add(rule.name)

        return JsonResponse({"valid": not missing, "missing_structures": missing})
    except Exception:
        logger.error("Failed to validate pipeline structures", exc_info=True)
        return JsonResponse({"valid": False, "missing_structures": [], "error": "Validation failed"})


def _describe_rule_source(rule) -> str:
    """Best-effort primary source/operand name for a rule (for preview display)."""
    rt = rule.rule_type
    try:
        if rt == "BOOLEAN":
            from .utils.expression_evaluator import collect_boolean_roi_names, get_boolean_root
            root = get_boolean_root(rule)
            names = sorted(collect_boolean_roi_names(root))
            return ", ".join(names)
        if rt == "INTENSITY":
            cfg = getattr(rule, "intensity_config", None)
            if cfg:
                return cfg.seed_roi or cfg.boundary_roi or "(image)"
            return "(image)"
        accessor = {
            "MARGIN": "margin_config", "CLEANUP": "cleanup_config",
            "CROP": "crop_config", "RING": "ring_config", "OVERLAP": "overlap_config",
            "EXPAND_SUBTRACT": "expand_subtract_config",
            "AVOID_MARGIN": "avoid_margin_config",
        }.get(rt)
        if accessor:
            cfg = getattr(rule, accessor, None)
            if cfg:
                return getattr(cfg, "source", "") or ""
    except Exception:
        pass
    return ""


@login_required
def api_template_preview(request):
    """Read-only preview of the RBS rules task2 would synthesize for a template.

    GET ?template_id=<uuid>. Synthesizes each AdditionalStructure's
    roi_generation_logic chain into RBS rules (in a transient, deleted pipeline)
    and returns them as JSON, so a clinician can see what will be generated
    before importing the series.
    """
    from uuid import uuid4 as _uuid4
    from dicom_handler.models import AdditionalStructures, AutosegmentationTemplate
    from .utils.legacy_synthesis import synthesize_rules

    template_id = request.GET.get("template_id") or request.POST.get("template_id")
    if not template_id:
        return JsonResponse({"error": "template_id is required"}, status=400)
    try:
        template = AutosegmentationTemplate.objects.get(pk=template_id)
    except (AutosegmentationTemplate.DoesNotExist, ValueError):
        return JsonResponse({"error": "template not found"}, status=404)

    pipeline = SegmentationPipeline.objects.create(
        name=f"preview-{_uuid4().hex[:8]}", is_public=False, is_active=False
    )
    try:
        structures = []
        extras = AdditionalStructures.objects.filter(
            autosegmentation_template=template
        ).order_by("roi_label")
        for extra in extras:
            rules, _ = synthesize_rules(extra, pipeline=pipeline)
            structures.append({
                "roi_label": extra.roi_label,
                "rt_roi_interpreted_type": extra.rt_roi_interpreted_type,
                "roi_display_color": extra.roi_display_color,
                "rules": [
                    {
                        "order": r.order,
                        "name": r.name,
                        "rule_type": r.rule_type,
                        "output_action": r.output_action,
                        "source": _describe_rule_source(r),
                    }
                    for r in rules
                ],
            })
        return JsonResponse({
            "template_id": str(template.pk),
            "structures": structures,
        })
    finally:
        pipeline.delete()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _render_job_create(request, pipeline, error=None):
    from dicom_server.models import RemoteDicomNode

    context = {
        "pipeline": pipeline,
        "error": error,
        "destination_nodes": RemoteDicomNode.objects.filter(
            is_export_destination=True, is_active=True
        ),
        "retrievable_nodes": RemoteDicomNode.objects.filter(
            is_active=True
        ).filter(
            models.Q(supports_c_move=True) | models.Q(supports_c_get=True)
        ),
    }

    # On POST-error re-render, restore the submitted RTStruct selection.
    selected = request.POST.get("input_id", "") if request.method == "POST" else ""
    if selected and ":" in selected:
        source, input_id = selected.split(":", 1)
        label = None
        if source == "upload":
            r = RTStructureSetFile.objects.filter(id=input_id).first()
            label = _rtstruct_choice_label(r) if r else None
        elif source == "import":
            r = (
                RTStructureFileImport.objects.select_related(
                    "deidentified_series_instance_uid__study__patient"
                )
                .filter(id=input_id)
                .first()
            )
            label = _import_rtstruct_choice_label(r) if r else None
        if label:
            context["selected_rtstruct"] = {"value": selected, "label": label}

    return render(request, "rule_based_segmentation/job_create.html", context)


def _duplicate_rule(pipeline, rule):
    """Duplicate a rule and its related configuration."""
    rule.pk = None
    rule.pipeline = pipeline
    rule.save()

    if rule.rule_type == "BOOLEAN":
        for root in rule.boolean_nodes.filter(parent=None):
            _duplicate_boolean_tree(rule, root, parent=None)
    elif rule.rule_type == "INTENSITY":
        old_config = rule.intensity_config
        ranges = list(old_config.ranges.all())
        rule.intensity_config = None
        new_config = IntensityRuleConfig.objects.create(
            pipeline_rule=rule,
            seed_type=old_config.seed_type,
            seed_roi=old_config.seed_roi,
            boundary_roi=old_config.boundary_roi,
            modality_hint=old_config.modality_hint,
        )
        for r in ranges:
            IntensityRange.objects.create(
                intensity_rule=new_config,
                min_value=r.min_value,
                max_value=r.max_value,
                order=r.order,
            )
    elif rule.rule_type == "MARGIN":
        old_config = rule.margin_config
        MarginRuleConfig.objects.create(
            pipeline_rule=rule,
            variant=old_config.variant,
            source=old_config.source,
            margin_mm=old_config.margin_mm,
            margin_x_mm=old_config.margin_x_mm,
            margin_y_mm=old_config.margin_y_mm,
            margin_z_mm=old_config.margin_z_mm,
            kernel_type=old_config.kernel_type,
            margin_l_mm=old_config.margin_l_mm,
            margin_r_mm=old_config.margin_r_mm,
            margin_a_mm=old_config.margin_a_mm,
            margin_p_mm=old_config.margin_p_mm,
            margin_h_mm=old_config.margin_h_mm,
            margin_f_mm=old_config.margin_f_mm,
        )
    elif rule.rule_type == "CROP":
        old_config = rule.crop_config
        new_config = CropRuleConfig.objects.create(
            pipeline_rule=rule,
            source=old_config.source,
        )
        for boundary in old_config.boundaries.all():
            CropBoundary.objects.create(
                crop_rule=new_config,
                boundary_roi=boundary.boundary_roi,
                order=boundary.order,
            )
    elif rule.rule_type == "CLEANUP":
        old_config = rule.cleanup_config
        CleanupRuleConfig.objects.create(
            pipeline_rule=rule,
            operation=old_config.operation,
            source=old_config.source,
            smoothing_mm=old_config.smoothing_mm,
            iterations=old_config.iterations,
            min_size_mm3=old_config.min_size_mm3,
            fully_connected=old_config.fully_connected,
            sigma_mm=old_config.sigma_mm,
            threshold=old_config.threshold,
        )
    elif rule.rule_type == "RING":
        old_config = rule.ring_config
        RingRuleConfig.objects.create(
            pipeline_rule=rule,
            variant=old_config.variant,
            source=old_config.source,
            thickness_mm=old_config.thickness_mm,
            thickness_x_mm=old_config.thickness_x_mm,
            thickness_y_mm=old_config.thickness_y_mm,
            thickness_z_mm=old_config.thickness_z_mm,
            kernel_type=old_config.kernel_type,
            thickness_l_mm=old_config.thickness_l_mm,
            thickness_r_mm=old_config.thickness_r_mm,
            thickness_a_mm=old_config.thickness_a_mm,
            thickness_p_mm=old_config.thickness_p_mm,
            thickness_h_mm=old_config.thickness_h_mm,
            thickness_f_mm=old_config.thickness_f_mm,
        )
    elif rule.rule_type == "OVERLAP":
        old_config = rule.overlap_config
        new_config = OverlapRuleConfig.objects.create(
            pipeline_rule=rule,
            source=old_config.source,
        )
        for other in old_config.others.all():
            OverlapOther.objects.create(
                overlap_rule=new_config,
                other_roi=other.other_roi,
                order=other.order,
            )
    elif rule.rule_type == "EXPAND_SUBTRACT":
        old_config = rule.expand_subtract_config
        ExpandSubtractRuleConfig.objects.create(
            pipeline_rule=rule,
            variant=old_config.variant,
            source=old_config.source,
            subtract=old_config.subtract,
            distance_mm=old_config.distance_mm,
            distance_x_mm=old_config.distance_x_mm,
            distance_y_mm=old_config.distance_y_mm,
            distance_z_mm=old_config.distance_z_mm,
            kernel_type=old_config.kernel_type,
            distance_l_mm=old_config.distance_l_mm,
            distance_r_mm=old_config.distance_r_mm,
            distance_a_mm=old_config.distance_a_mm,
            distance_p_mm=old_config.distance_p_mm,
            distance_h_mm=old_config.distance_h_mm,
            distance_f_mm=old_config.distance_f_mm,
        )
    elif rule.rule_type == "AVOID_MARGIN":
        old_config = rule.avoid_margin_config
        AvoidMarginRuleConfig.objects.create(
            pipeline_rule=rule,
            variant=old_config.variant,
            source=old_config.source,
            avoid=old_config.avoid,
            margin_mm=old_config.margin_mm,
            margin_x_mm=old_config.margin_x_mm,
            margin_y_mm=old_config.margin_y_mm,
            margin_z_mm=old_config.margin_z_mm,
            kernel_type=old_config.kernel_type,
            margin_l_mm=old_config.margin_l_mm,
            margin_r_mm=old_config.margin_r_mm,
            margin_a_mm=old_config.margin_a_mm,
            margin_p_mm=old_config.margin_p_mm,
            margin_h_mm=old_config.margin_h_mm,
            margin_f_mm=old_config.margin_f_mm,
        )


def _duplicate_boolean_tree(rule, node, parent=None):
    new_node = BooleanExpressionNode.objects.create(
        pipeline_rule=rule,
        parent=parent,
        node_type=node.node_type,
        operation_type=node.operation_type,
        roi_name=node.roi_name,
        order=node.order,
    )
    for child in node.children.all().order_by("order"):
        _duplicate_boolean_tree(rule, child, parent=new_node)
    return new_node


def _get_rtstruct_upload_directory(user):
    """Return the directory where uploaded RTStruct files should be stored."""
    from dicom_handler.models import SystemConfiguration

    config = SystemConfiguration.load()
    base_dir = config.folder_configuration or os.getcwd()
    target_dir = os.path.join(
        base_dir, "rule_based_segmentation", "uploads", "rtstructs", str(user.id)
    )
    os.makedirs(target_dir, exist_ok=True)
    return target_dir


def _save_uploaded_rtstruct(uploaded_file: UploadedFile, user):
    """Save an uploaded RTStruct file and create a database record."""
    target_dir = _get_rtstruct_upload_directory(user)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = sanitize_filename_component(uploaded_file.name) or "rtstruct.dcm"
    filename = f"{timestamp}_{safe_name}"
    target_path = validate_stored_path(os.path.join(target_dir, filename))
    if not target_path or os.path.basename(target_path) != filename:
        raise ValueError("Unsafe RTStruct upload target path")

    with open(target_path, "wb+") as dest:
        for chunk in uploaded_file.chunks():
            dest.write(chunk)

    ds = pydicom.dcmread(target_path, stop_before_pixels=True, force=True)

    referenced_series_uid = ""
    if hasattr(ds, "ReferencedFrameOfReferenceSequence"):
        for ref_frame in ds.ReferencedFrameOfReferenceSequence:
            if not hasattr(ref_frame, "RTReferencedStudySequence"):
                continue
            for ref_study in ref_frame.RTReferencedStudySequence:
                if not hasattr(ref_study, "RTReferencedSeriesSequence"):
                    continue
                for ref_series in ref_study.RTReferencedSeriesSequence:
                    if hasattr(ref_series, "SeriesInstanceUID"):
                        referenced_series_uid = str(ref_series.SeriesInstanceUID)
                        break

    rtstruct_file = RTStructureSetFile.objects.create(
        patient_name=str(getattr(ds, "PatientName", "")),
        patient_id=str(getattr(ds, "PatientID", "")),
        study_instance_uid=str(getattr(ds, "StudyInstanceUID", "")),
        series_instance_uid=str(getattr(ds, "SeriesInstanceUID", "")),
        sop_instance_uid=str(getattr(ds, "SOPInstanceUID", "")),
        structure_set_label=str(getattr(ds, "StructureSetLabel", "")),
        referenced_series_instance_uid=referenced_series_uid,
        rtstructure_file_path=target_path,
        working_directory=target_dir,
    )

    return "UPLOAD", str(rtstruct_file.id)


def _resolve_destination_node(node_id):
    """Return the RemoteDicomNode for a POSTed node id, or None."""
    if not node_id:
        return None
    from dicom_server.models import RemoteDicomNode

    return RemoteDicomNode.objects.filter(pk=node_id, is_export_destination=True).first()


def _series_files_missing(series_uid: str) -> bool:
    """Return True if any DICOMInstance file for the series is missing on disk."""
    try:
        series = DICOMSeries.objects.get(series_instance_uid=series_uid)
    except DICOMSeries.DoesNotExist:
        return True

    for instance in series.dicominstance_set.all():
        if not instance.instance_path or not os.path.exists(instance.instance_path):
            logger.warning(
                f"Missing DICOM instance file for series {series_uid}: {instance.instance_path}"
            )
            return True
    return False


def _validate_pipeline_against_rtstruct(pipeline, rtstruct_path):
    """Return a list of structure names referenced by the pipeline but missing from the RTStruct."""
    structures = _read_structures_from_rtstruct(rtstruct_path)
    available = {s["value"] for s in structures}
    missing = set()

    for rule in pipeline.rules.all().order_by("order"):
        required = _collect_rule_structure_names(rule)
        missing.update(required - available)
        # Rule outputs become available to later rules.
        available.add(rule.name)

    return sorted(missing)


def _collect_rule_structure_names(rule):
    """Collect all structure names referenced by a rule."""
    names = set()
    if rule.rule_type == "BOOLEAN":
        for root in rule.boolean_nodes.filter(parent=None):
            _collect_boolean_names(root, names)
    elif rule.rule_type == "INTENSITY":
        config = getattr(rule, "intensity_config", None)
        if config:
            if config.seed_type == "STRUCTURE" and config.seed_roi:
                names.add(config.seed_roi)
            if config.boundary_roi:
                names.add(config.boundary_roi)
    elif rule.rule_type in ("MARGIN", "CLEANUP"):
        config = getattr(rule, f"{rule.rule_type.lower()}_config", None)
        if config and config.source:
            names.add(config.source)
    elif rule.rule_type == "CROP":
        config = getattr(rule, "crop_config", None)
        if config:
            if config.source:
                names.add(config.source)
            for boundary in config.boundaries.all():
                names.add(boundary.boundary_roi)
    elif rule.rule_type == "RING":
        config = getattr(rule, "ring_config", None)
        if config and config.source:
            names.add(config.source)
    elif rule.rule_type == "OVERLAP":
        config = getattr(rule, "overlap_config", None)
        if config:
            if config.source:
                names.add(config.source)
            for other in config.others.all():
                names.add(other.other_roi)
    elif rule.rule_type == "EXPAND_SUBTRACT":
        config = getattr(rule, "expand_subtract_config", None)
        if config:
            if config.source:
                names.add(config.source)
            if config.subtract:
                names.add(config.subtract)
    elif rule.rule_type == "AVOID_MARGIN":
        config = getattr(rule, "avoid_margin_config", None)
        if config:
            if config.source:
                names.add(config.source)
            if config.avoid:
                names.add(config.avoid)
    return names


def _collect_boolean_names(node, names):
    if node.node_type == "ROI":
        names.add(node.roi_name)
    else:
        for child in node.children.all().order_by("order"):
            _collect_boolean_names(child, names)


def _resolve_rtstruct_and_series(input_type, input_id):
    """Resolve RTStruct path and referenced series UID without creating a job."""
    if input_type == "UPLOAD":
        rtstruct = get_object_or_404(RTStructureSetFile, id=input_id)
        return rtstruct.rtstructure_file_path, rtstruct.referenced_series_instance_uid
    elif input_type == "IMPORT":
        rtstruct = get_object_or_404(RTStructureFileImport, id=input_id)
        rtstruct_path = rtstruct.reidentified_rt_structure_file_path
        ds = pydicom.dcmread(rtstruct_path, stop_before_pixels=True, force=True)
        series_uid = ""
        if hasattr(ds, "ReferencedFrameOfReferenceSequence"):
            for ref_frame in ds.ReferencedFrameOfReferenceSequence:
                if not hasattr(ref_frame, "RTReferencedStudySequence"):
                    continue
                for ref_study in ref_frame.RTReferencedStudySequence:
                    if not hasattr(ref_study, "RTReferencedSeriesSequence"):
                        continue
                    for ref_series in ref_study.RTReferencedSeriesSequence:
                        if hasattr(ref_series, "SeriesInstanceUID"):
                            series_uid = str(ref_series.SeriesInstanceUID)
                            break
        return rtstruct_path, series_uid
    raise ValueError(f"Invalid input_type: {input_type}")


def _clear_pending_session(request):
    keys = [
        "pending_rtstruct_path",
        "pending_series_uid",
        "pending_pipeline_id",
        "pending_input_type",
        "pending_input_id",
        "pending_files_missing",
        "pending_destination_node_id",
    ]
    for key in keys:
        request.session.pop(key, None)


@login_required
def remote_retrieve(request, pipeline_id):
    """Retrieve an RTStruct (+ referenced image series) from a remote DICOM node."""
    from dicom_server.models import DicomQueryResult, RemoteDicomNode

    pipeline = get_object_or_404(SegmentationPipeline, id=pipeline_id)
    nodes = RemoteDicomNode.objects.filter(is_active=True).filter(
        models.Q(supports_c_move=True) | models.Q(supports_c_get=True)
    )
    context = {"pipeline": pipeline, "nodes": nodes}

    if request.method != "POST":
        return render(request, "rule_based_segmentation/remote_retrieve.html", context)

    node = get_object_or_404(RemoteDicomNode, pk=request.POST.get("node_id"))
    action = request.POST.get("action", "find")

    if action == "find":
        study_uid = request.POST.get("study_uid", "").strip()
        if not study_uid:
            context["error"] = "Study Instance UID is required."
            return render(request, "rule_based_segmentation/remote_retrieve.html", context)
        try:
            from dicom_server.query_retrieve_service import get_qr_service_instance

            qr_service = get_qr_service_instance()
            query_obj = qr_service.query(
                node,
                "SERIES",
                {"StudyInstanceUID": study_uid, "Modality": "RTSTRUCT"},
                user=request.user,
            )
            context["results"] = DicomQueryResult.objects.filter(query=query_obj)
            context["study_uid"] = study_uid
            context["selected_node_id"] = node.pk
        except Exception as e:
            logger.error(f"C-FIND failed: {e}", exc_info=True)
            context["error"] = f"Query failed: {e}"
        return render(request, "rule_based_segmentation/remote_retrieve.html", context)

    # action == 'retrieve'
    study_uid = request.POST.get("study_uid", "").strip()
    rtstruct_series_uid = request.POST.get("rtstruct_series_uid", "").strip()
    image_series_uid = request.POST.get("image_series_uid", "").strip()

    if not study_uid or not rtstruct_series_uid:
        context["error"] = "Study UID and RTStruct Series UID are required."
        return render(request, "rule_based_segmentation/remote_retrieve.html", context)

    from .tasks import retrieve_rtstruct_for_pipeline

    task = retrieve_rtstruct_for_pipeline.delay(
        node.pk,
        study_uid,
        rtstruct_series_uid,
        str(pipeline.id),
        request.user.pk,
        image_series_uid,
    )
    return redirect(
        "rule_based_segmentation:remote_retrieve_status", task_id=task.id
    )


@login_required
def remote_retrieve_status(request, task_id):
    """Status page for an in-progress remote retrieve + job creation."""
    return render(
        request,
        "rule_based_segmentation/remote_retrieve_status.html",
        {"task_id": task_id},
    )


@login_required
def remote_retrieve_status_json(request, task_id):
    """JSON status of the retrieve_rtstruct_for_pipeline celery task."""
    from celery.result import AsyncResult
    from draw_client import celery_app

    result = AsyncResult(task_id, app=celery_app)
    payload = {"state": result.state}
    if result.state == "PROGRESS":
        payload["meta"] = result.info if isinstance(result.info, dict) else {}
    elif result.state == "SUCCESS":
        info = result.result if isinstance(result.result, dict) else {}
        payload["meta"] = info
        if info.get("job_id"):
            payload["job_url"] = reverse(
                "rule_based_segmentation:job_detail", args=[info["job_id"]]
            )
        elif info.get("status") == "FAILED":
            payload["state"] = "FAILURE"
            payload["meta"] = {"error": info.get("error", "Retrieve failed")}
    elif result.state == "FAILURE":
        payload["meta"] = {"error": str(result.info)}
    return JsonResponse(payload)
