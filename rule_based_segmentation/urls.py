from django.urls import path

from . import views

app_name = "rule_based_segmentation"

urlpatterns = [
    # Pipeline CRUD
    path("pipelines/", views.pipeline_list, name="pipeline_list"),
    path("pipelines/new/", views.pipeline_create, name="pipeline_create"),
    path("pipelines/<uuid:pipeline_id>/", views.pipeline_detail, name="pipeline_detail"),
    path(
        "pipelines/<uuid:pipeline_id>/edit/",
        views.pipeline_edit,
        name="pipeline_edit",
    ),
    path(
        "pipelines/<uuid:pipeline_id>/delete/",
        views.pipeline_delete,
        name="pipeline_delete",
    ),
    path(
        "pipelines/<uuid:pipeline_id>/duplicate/",
        views.pipeline_duplicate,
        name="pipeline_duplicate",
    ),
    path(
        "pipelines/<uuid:pipeline_id>/run/",
        views.job_create,
        name="job_create",
    ),

    # Jobs
    path("jobs/", views.job_list, name="job_list"),
    path("jobs/<uuid:job_id>/", views.job_detail, name="job_detail"),
    path("jobs/<uuid:job_id>/status/", views.job_status, name="job_status"),
    path(
        "jobs/<uuid:job_id>/download/",
        views.download_output,
        name="download_output",
    ),

    # RTStruct downloads
    path("rtstructs/<uuid:rtstruct_id>/download/", views.download_rtstruct, name="download_rtstruct"),
    path("rtstructs/bulk-download/", views.bulk_download_rtstructs, name="bulk_download_rtstructs"),

    # RTStruct and image upload workflow
    path("select-rtstruct/", views.select_rtstruct, name="select_rtstruct"),
    path(
        "upload-image-series/",
        views.select_series_for_upload,
        name="upload_image_series",
    ),

    # APIs
    path("api/structures/", views.api_get_structures, name="api_get_structures"),
    path(
        "api/rtstructs/search/",
        views.api_search_rtstructs,
        name="api_search_rtstructs",
    ),
    path(
        "api/upload-sample-rtstruct/",
        views.api_upload_sample_rtstruct,
        name="api_upload_sample_rtstruct",
    ),
    path(
        "api/validate-pipeline/",
        views.api_validate_pipeline,
        name="api_validate_pipeline",
    ),
]
