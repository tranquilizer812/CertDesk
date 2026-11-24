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
]
