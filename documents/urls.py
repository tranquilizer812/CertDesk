from django.urls import path

from . import views

app_name = "documents"

urlpatterns = [
    path("dashboard/", views.dashboard, name="dashboard"),
    path("documents/", views.request_list, name="list"),
    path("documents/new/", views.create_request, name="create_request"),
    path("documents/import/", views.import_csv, name="import_csv"),
    path("documents/<int:pk>/", views.request_detail, name="request_detail"),
    path("documents/<int:pk>/delete/", views.delete_request, name="delete_request"),
    path("documents/<int:pk>/upload/", views.upload_document, name="upload_document"),
    path("documents/<int:pk>/ai/extract/", views.extract_ai_metadata, name="extract_ai_metadata"),
    path("documents/<int:pk>/ai/apply/", views.apply_ai_metadata, name="apply_ai_metadata"),
    path("documents/files/<int:document_pk>/download/", views.download_document, name="download_document"),
    path("documents/<int:pk>/link/", views.generate_upload_link, name="generate_upload_link"),
    path("documents/<int:pk>/email-link/", views.email_upload_link, name="email_upload_link"),
    path("upload/<uuid:token>/", views.public_upload, name="public_upload"),
    path("properties/", views.property_list, name="property_list"),
    path("properties/new/", views.create_property, name="create_property"),
    path("vendors/", views.vendor_list, name="vendor_list"),
    path("vendors/new/", views.create_vendor, name="create_vendor"),
    path("export.csv", views.export_csv, name="export_csv"),
    path("documents/filter/", views.request_list_json, name="list_json"),
]
