from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.landing, name="landing"),
    path("pricing/", views.pricing, name="pricing"),
    path("demo/login/", views.demo_login, name="demo_login"),
    path("health/", views.health, name="health"),
    path("legal/", views.legal, name="legal"),
    path("billing/checkout/", views.stripe_checkout, name="stripe_checkout"),
    path("billing/webhook/", views.stripe_webhook, name="stripe_webhook"),
    path("api/", views.api_root, name="api_root"),
    path("api/documents/", views.api_documents, name="api_documents"),
    path("api/certificates/", views.api_certificates, name="api_certificates"),
    path("api/export/", views.api_export, name="api_export"),
    path("api/vendors/", views.api_vendors, name="api_vendors"),
    path("api/properties/", views.api_properties, name="api_properties"),
]
