from django.conf import settings


def product_context(request):
    return {
        "PRODUCT_NAME": "CertDesk",
        "DEMO_MODE": settings.DEMO_MODE,
        "BASE_URL": settings.BASE_URL,
    }
