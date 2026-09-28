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
from .utils.dicom_image_importer import (
    import_uploaded_image_series,
    sanitize_filename_component,
)
from .utils.job_service import MissingImageSeriesError, create_segmentation_job
from .utils.rtstruct_io import _backup_rtstruct

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
        data = _parse_pipeline_data(request.POST)
        if data:
            try:
                pipeline = _create_or_update_pipeline(data, request.user)
                return redirect("rule_based_segmentation:pipeline_detail", pipeline_id=pipeline.id)
            except ValueError as e:
                return _render_pipeline_form(request, error=str(e))
    return _render_pipeline_form(request)


@login_required
def pipeline_edit(request, pipeline_id):
    """Edit an existing pipeline."""
    pipeline = get_object_or_404(SegmentationPipeline, id=pipeline_id)
    if request.method == "POST":
        data = _parse_pipeline_data(request.POST)
        if data:
            try:
                pipeline = _create_or_update_pipeline(data, request.user, pipeline=pipeline)
                return redirect("rule_based_segmentation:pipeline_detail", pipeline_id=pipeline.id)
            except ValueError as e:
                return _render_pipeline_form(request, pipeline, error=str(e))
    return _render_pipeline_form(request, pipeline)


def _render_pipeline_form(request, pipeline=None, error=None):
    pipeline_data = (
        {"rules": [_rule_to_json(r) for r in pipeline.rules.all().order_by("order")]}
        if pipeline
        else {"rules": []}
    )
    return render(
        request,
        "rule_based_segmentation/pipeline_form.html",
        {
            "pipeline": pipeline,
            "pipeline_data": pipeline_data,
            "error": error,
        },
    )


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


def _rule_to_json(rule):
    """Convert a saved PipelineRule to the frontend rule format."""
    data = {
        "rule_type": rule.rule_type,
        "name": rule.name,
        "output_action": rule.output_action,
        "output_color": _rgb_dicom_to_hex(rule.output_color),
        "output_roi_type": rule.output_roi_type,
        "config": {},
    }

    if rule.rule_type == "BOOLEAN":
        root = rule.boolean_nodes.filter(parent=None).first()
        data["config"] = _boolean_node_to_json(root) if root else {}
    elif rule.rule_type == "INTENSITY":
        cfg = rule.intensity_config
        data["config"] = {
            "seed_type": cfg.seed_type,
            "seed_roi": cfg.seed_roi or "",
            "boundary_roi": cfg.boundary_roi or "",
            "modality_hint": cfg.modality_hint or "",
            "ranges": [
                {"min": r.min_value, "max": r.max_value} for r in cfg.ranges.all()
            ],
        }
    elif rule.rule_type == "MARGIN":
        cfg = rule.margin_config
        data["config"] = {
            "variant": cfg.variant,
            "source": cfg.source,
            "margin_mm": cfg.margin_mm,
            "margin_x_mm": cfg.margin_x_mm,
            "margin_y_mm": cfg.margin_y_mm,
            "margin_z_mm": cfg.margin_z_mm,
            "kernel_type": cfg.kernel_type,
        }
    elif rule.rule_type == "CROP":
        cfg = rule.crop_config
        data["config"] = {
            "source": cfg.source,
            "boundaries": [b.boundary_roi for b in cfg.boundaries.all()],
        }
    elif rule.rule_type == "CLEANUP":
        cfg = rule.cleanup_config
        data["config"] = {
            "operation": cfg.operation,
            "source": cfg.source,
            "smoothing_mm": cfg.smoothing_mm,
            "iterations": cfg.iterations,
            "min_size_mm3": cfg.min_size_mm3,
            "fully_connected": cfg.fully_connected,
            "sigma_mm": cfg.sigma_mm,
            "threshold": cfg.threshold,
        }

    return data


def _boolean_node_to_json(node):
    if node.node_type == "ROI":
        return {"name": node.roi_name}
    return {
        "operation": node.operation_type,
        "operands": [
            _boolean_node_to_json(child)
            for child in node.children.all().order_by("order")
        ],
    }


def _rgb_dicom_to_hex(color_string):
    if not color_string:
        return "#FFFF00"
    parts = [p.strip() for p in color_string.split("\\")]
    if len(parts) != 3:
        return "#FFFF00"
    try:
        return "#" + "".join(f"{int(p):02X}" for p in parts)
    except ValueError:
        return "#FFFF00"


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


@login_required
def job_list(request):
    """List segmentation jobs."""
    jobs = SegmentationJob.objects.filter(created_by=request.user).order_by("-created_at")
    return render(request, "rule_based_segmentation/job_list.html", {"jobs": jobs})


@login_required
def job_detail(request, job_id):
    """Show job details."""
    job = get_object_or_404(SegmentationJob, id=job_id)
    return render(request, "rule_based_segmentation/job_status.html", {"job": job})


@login_required
def job_status(request, job_id):
    """Return job status as JSON for polling."""
    job = get_object_or_404(SegmentationJob, id=job_id)
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
        }
    )


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

            if not DICOMSeries.objects.filter(series_instance_uid=series_uid).exists():
                request.session["pending_rtstruct_path"] = rtstruct_path
                request.session["pending_series_uid"] = series_uid
                request.session["pending_pipeline_id"] = str(pipeline.id)
                request.session["pending_input_type"] = input_type
                request.session["pending_input_id"] = input_id
                return redirect("rule_based_segmentation:upload_image_series")

            job = create_segmentation_job(pipeline, input_type, input_id, request.user)
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
                job = create_segmentation_job(
                    pipeline, input_type, input_id, request.user
                )
                _clear_pending_session(request)
                return redirect("rule_based_segmentation:job_status", job_id=job.id)

            if job_id:
                job = get_object_or_404(SegmentationJob, id=job_id)
                job.dicom_series = series
                job.save(update_fields=["dicom_series"])
                from .tasks import run_segmentation_job

                run_segmentation_job.delay(str(job.id))
                return redirect("rule_based_segmentation:job_status", job_id=job.id)

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

    return render(
        request,
        "rule_based_segmentation/upload_image_series.html",
        {
            "job_id": job_id,
            "expected_series_uid": expected_series_uid,
            "error": error,
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
        return JsonResponse({"error": str(e)}, status=400)
    except Exception as e:
        logger.error(f"Failed to upload sample RTStruct: {e}", exc_info=True)
        return JsonResponse({"error": str(e)}, status=400)

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
            if rule.output_action == "CREATE_NEW" or rule.name in available:
                available.add(rule.name)

        return JsonResponse({"valid": not missing, "missing_structures": missing})
    except Exception as e:
        return JsonResponse({"valid": False, "missing_structures": [], "error": str(e)})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _render_job_create(request, pipeline, error=None):
    context = {"pipeline": pipeline, "error": error}

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


def _parse_pipeline_data(post_data):
    """Parse pipeline JSON from form data."""
    json_data = post_data.get("pipeline_data")
    if not json_data:
        return None
    try:
        return json.loads(json_data)
    except json.JSONDecodeError:
        return None


def _create_or_update_pipeline(data, user, pipeline=None):
    """Create or update a pipeline and all its rules from parsed JSON."""
    from django.db import transaction

    rules = data.get("rules", [])
    _validate_pipeline_rules(rules)

    with transaction.atomic():
        if pipeline is None:
            pipeline = SegmentationPipeline.objects.create(
                name=data.get("name", "Unnamed Pipeline"),
                description=data.get("description", ""),
                is_public=data.get("is_public", False),
                created_by=user,
            )
        else:
            pipeline.name = data.get("name", pipeline.name)
            pipeline.description = data.get("description", pipeline.description)
            pipeline.is_public = data.get("is_public", pipeline.is_public)
            pipeline.save()
            pipeline.rules.all().delete()

        for idx, rule_data in enumerate(rules, start=1):
            _save_rule(pipeline, idx, rule_data)

    return pipeline


def _validate_pipeline_rules(rules):
    """Validate pipeline rule ordering and output name uniqueness."""
    output_names = set()
    for idx, rule in enumerate(rules, start=1):
        name = rule.get("name", "").strip()
        if not name:
            raise ValueError(f"Rule {idx} has no output ROI name.")
        if name in output_names:
            raise ValueError(
                f"Rule '{name}' is used more than once. Output ROI names must be unique."
            )
        output_names.add(name)

    # Ensure no rule references a structure that is produced by the same or a later rule.
    produced_by_index = {}
    for idx, rule in enumerate(rules, start=1):
        produced_by_index[rule.get("name", "").strip()] = idx

    for idx, rule in enumerate(rules, start=1):
        for required in _collect_required_structure_names(rule):
            required_source = produced_by_index.get(required)
            if required_source is not None and required_source >= idx:
                raise ValueError(
                    f"Rule '{rule.get('name')}' references '{required}', which is produced by "
                    f"rule {required_source}. Move the source rule before this rule."
                )


def _collect_required_structure_names(rule):
    """Collect structure names referenced by a rule from frontend JSON."""
    names = set()
    rule_type = rule.get("rule_type")
    config = rule.get("config", {})

    if rule_type == "BOOLEAN":
        _collect_boolean_operand_names(config, names)
    elif rule_type == "INTENSITY":
        if config.get("seed_type") == "STRUCTURE" and config.get("seed_roi"):
            names.add(config["seed_roi"])
        if config.get("boundary_roi"):
            names.add(config["boundary_roi"])
    elif rule_type in ("MARGIN", "CLEANUP"):
        if config.get("source"):
            names.add(config["source"])
    elif rule_type == "CROP":
        if config.get("source"):
            names.add(config["source"])
        for boundary in config.get("boundaries", []):
            if boundary:
                names.add(boundary)

    return names


def _collect_boolean_operand_names(config, names):
    """Recursively collect ROI names from a boolean expression config."""
    if config.get("operation"):
        for operand in config.get("operands", []):
            _collect_boolean_operand_names(operand, names)
    elif config.get("name"):
        names.add(config["name"])


def _save_rule(pipeline, order, rule_data):
    """Create a PipelineRule and its related configuration."""
    rule = PipelineRule.objects.create(
        pipeline=pipeline,
        order=order,
        rule_type=rule_data.get("rule_type"),
        name=rule_data.get("name"),
        output_action=rule_data.get("output_action", "CREATE_NEW"),
        output_color=rule_data.get("output_color") or "255\\255\\0",
        output_roi_type=rule_data.get("output_roi_type", "ORGAN"),
    )

    config = rule_data.get("config", {})
    if rule.rule_type == "BOOLEAN":
        _save_boolean_tree(rule, config)
    elif rule.rule_type == "INTENSITY":
        _save_intensity_config(rule, config)
    elif rule.rule_type == "MARGIN":
        _save_margin_config(rule, config)
    elif rule.rule_type == "CROP":
        _save_crop_config(rule, config)
    elif rule.rule_type == "CLEANUP":
        _save_cleanup_config(rule, config)

    return rule


def _save_boolean_tree(rule, config, parent=None):
    """Recursively save a boolean expression tree."""
    node_type = "OPERATION" if config.get("operation") else "ROI"
    node = BooleanExpressionNode.objects.create(
        pipeline_rule=rule,
        parent=parent,
        node_type=node_type,
        operation_type=config.get("operation") if node_type == "OPERATION" else None,
        roi_name=config.get("name") if node_type == "ROI" else None,
        order=parent.children.count() + 1 if parent else 1,
    )

    if node_type == "OPERATION":
        for child_data in config.get("operands", []):
            _save_boolean_tree(rule, child_data, parent=node)

    return node


def _save_intensity_config(rule, config):
    """Save intensity-range rule configuration."""
    intensity_config = IntensityRuleConfig.objects.create(
        pipeline_rule=rule,
        seed_type=config.get("seed_type", "IMAGE"),
        seed_roi=config.get("seed_roi", ""),
        boundary_roi=config.get("boundary_roi", ""),
        modality_hint=config.get("modality_hint", ""),
    )
    for idx, r in enumerate(config.get("ranges", []), start=1):
        IntensityRange.objects.create(
            intensity_rule=intensity_config,
            min_value=r.get("min"),
            max_value=r.get("max"),
            order=idx,
        )


def _save_margin_config(rule, config):
    """Save margin rule configuration."""
    MarginRuleConfig.objects.create(
        pipeline_rule=rule,
        variant=config.get("variant", "UNIFORM"),
        source=config.get("source", ""),
        margin_mm=config.get("margin_mm"),
        margin_x_mm=config.get("margin_x_mm"),
        margin_y_mm=config.get("margin_y_mm"),
        margin_z_mm=config.get("margin_z_mm"),
        kernel_type=config.get("kernel_type", "ball"),
    )


def _save_crop_config(rule, config):
    """Save crop-to-boundary rule configuration."""
    crop_config = CropRuleConfig.objects.create(
        pipeline_rule=rule,
        source=config.get("source", ""),
    )
    for idx, boundary in enumerate(config.get("boundaries", []), start=1):
        CropBoundary.objects.create(
            crop_rule=crop_config,
            boundary_roi=boundary,
            order=idx,
        )


def _save_cleanup_config(rule, config):
    """Save cleanup rule configuration."""
    CleanupRuleConfig.objects.create(
        pipeline_rule=rule,
        operation=config.get("operation", ""),
        source=config.get("source", ""),
        smoothing_mm=config.get("smoothing_mm"),
        iterations=config.get("iterations"),
        min_size_mm3=config.get("min_size_mm3"),
        fully_connected=config.get("fully_connected"),
        sigma_mm=config.get("sigma_mm"),
        threshold=config.get("threshold"),
    )


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
    target_path = os.path.join(target_dir, filename)

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
    ]
    for key in keys:
        request.session.pop(key, None)
