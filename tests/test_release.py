from django.conf import settings
from django.test import SimpleTestCase, override_settings
from django.urls import reverse


class ReleaseReadinessTests(SimpleTestCase):
    def test_health_endpoint_returns_minimal_json_status(self):
        response = self.client.get(reverse("core:health"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(response.json(), {"status": "ok"})

    @override_settings(
        SECURE_SSL_REDIRECT=False,
        SECURE_HSTS_SECONDS=31536000,
        SECURE_HSTS_INCLUDE_SUBDOMAINS=True,
        SECURE_HSTS_PRELOAD=True,
        SECURE_CONTENT_TYPE_NOSNIFF=True,
        X_FRAME_OPTIONS="DENY",
    )
    def test_security_headers_are_enabled(self):
        response = self.client.get(reverse("core:health"), secure=True)

        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertIn("max-age=31536000", response["Strict-Transport-Security"])
        self.assertIn("includeSubDomains", response["Strict-Transport-Security"])
        self.assertIn("preload", response["Strict-Transport-Security"])

    def test_upload_limits_and_base_url_are_explicit(self):
        self.assertEqual(settings.FILE_UPLOAD_MAX_MEMORY_SIZE, 10 * 1024 * 1024)
        self.assertEqual(settings.DATA_UPLOAD_MAX_MEMORY_SIZE, 12 * 1024 * 1024)
        self.assertTrue(settings.BASE_URL.startswith(("http://", "https://")))
        self.assertFalse(settings.BASE_URL.endswith("/"))
