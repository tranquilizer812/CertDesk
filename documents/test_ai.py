import json
from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Organization

from .ai import MetadataExtractionError, extract_document_metadata
from .models import Document, DocumentRequest, Property, UploadToken, Vendor


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size=-1):
        if size < 0:
            return self.payload
        return self.payload[:size]


class AiClientTests(TestCase):
    @override_settings(
        AI_BASE_URL="https://ai.example/v1",
        AI_API_KEY="secret-key",
        AI_MODEL="vision-model",
        AI_TIMEOUT_SECONDS=7,
    )
    @patch("documents.ai.urlopen")
    def test_extracts_validated_metadata_without_sending_tenant_context(self, urlopen):
        provider_payload = json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "carrier": "Travelers",
                                    "policy_number": "GL-1234",
                                    "coverage": "General Liability",
                                    "expires_on": "2027-01-15",
                                }
                            )
                        }
                    }
                ]
            }
        ).encode("utf-8")
        urlopen.return_value = FakeResponse(provider_payload)
        uploaded = SimpleUploadedFile(
            "sensitive-vendor-name.pdf",
            b"%PDF-1.4\n% synthetic test document\n%%EOF\n",
            content_type="application/pdf",
        )

        metadata = extract_document_metadata(uploaded)

        self.assertEqual(metadata["carrier"], "Travelers")
        self.assertEqual(metadata["expires_on"], "2027-01-15")
        request = urlopen.call_args.args[0]
        request_body = json.loads(request.data)
        self.assertEqual(request.full_url, "https://ai.example/v1/chat/completions")
        self.assertEqual(request.get_header("Authorization"), "Bearer secret-key")
        self.assertNotIn("sensitive-vendor-name.pdf", request.data.decode("utf-8"))
        self.assertNotIn("Bright Roof Co", request.data.decode("utf-8"))
        self.assertEqual(
            request_body["messages"][1]["content"][0]["file"]["filename"],
            "document.pdf",
        )

    @override_settings(
        AI_BASE_URL="https://ai.example/v1",
        AI_API_KEY="secret-key",
        AI_MODEL="vision-model",
    )
    @patch("documents.ai.urlopen")
    def test_rejects_malformed_provider_response(self, urlopen):
        urlopen.return_value = FakeResponse(
            json.dumps({"choices": [{"message": {"content": "not-json"}}]}).encode("utf-8")
        )
        uploaded = SimpleUploadedFile(
            "certificate.png",
            b"not really an image",
            content_type="image/png",
        )

        with self.assertRaises(MetadataExtractionError):
            extract_document_metadata(uploaded)

    @override_settings(AI_BASE_URL="", AI_API_KEY="", AI_MODEL="")
    def test_disabled_configuration_does_not_call_provider(self):
        uploaded = SimpleUploadedFile("certificate.pdf", b"%PDF-1.4\n")
        with self.assertRaises(MetadataExtractionError):
            extract_document_metadata(uploaded)


class AiWorkflowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="ai-owner@example.com",
            email="ai-owner@example.com",
            password="SafePass-123!",
        )
        self.other_user = get_user_model().objects.create_user(
            username="other-ai@example.com",
            email="other-ai@example.com",
            password="SafePass-123!",
        )
        self.org = Organization.objects.create(
            name="AI Workspace",
            plan=Organization.PLAN_GROWTH,
        )
        self.other_org = Organization.objects.create(
            name="Other AI Workspace",
            plan=Organization.PLAN_GROWTH,
        )
        Membership.objects.create(user=self.user, organization=self.org, role="owner")
        Membership.objects.create(
            user=self.other_user,
            organization=self.other_org,
            role="owner",
        )
        vendor = Vendor.objects.create(
            organization=self.org,
            name="Bright Roof Co",
            email="vendor@example.com",
        )
        prop = Property.objects.create(organization=self.org, name="Maple Court")
        self.item = DocumentRequest.objects.create(
            organization=self.org,
            vendor=vendor,
            property=prop,
            document_type=DocumentRequest.TYPE_COI,
        )
        self.document = Document.objects.create(
            organization=self.org,
            request=self.item,
            file=SimpleUploadedFile(
                "certificate.pdf",
                b"%PDF-1.4\n% synthetic test document\n%%EOF\n",
                content_type="application/pdf",
            ),
            original_filename="certificate.pdf",
            carrier="Manual Carrier",
        )

    @override_settings(
        AI_BASE_URL="https://ai.example/v1",
        AI_API_KEY="secret-key",
        AI_MODEL="vision-model",
    )
    @patch("documents.views.extract_document_metadata")
    def test_staff_can_review_and_apply_ai_suggestions(self, extract):
        extract.return_value = {
            "carrier": "AI Carrier",
            "policy_number": "AI-123",
            "coverage": "General Liability",
            "expires_on": "2027-03-01",
        }
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("documents:extract_ai_metadata", args=[self.item.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Review AI suggestions")
        self.assertContains(response, "AI-123")
        self.assertTrue(response.context["metadata_review_form"]["carrier"].field.disabled)
        self.assertFalse(response.context["metadata_review_form"]["policy_number"].field.disabled)
        extract.assert_called_once()

        response = self.client.post(
            reverse("documents:apply_ai_metadata", args=[self.item.pk]),
            {
                "document_id": self.document.pk,
                "carrier": "AI Carrier",
                "policy_number": "AI-123",
                "coverage": "General Liability",
                "expires_on": "2027-03-01",
            },
        )
        self.assertRedirects(response, reverse("documents:request_detail", args=[self.item.pk]))
        self.document.refresh_from_db()
        self.assertEqual(self.document.carrier, "Manual Carrier")
        self.assertEqual(self.document.policy_number, "AI-123")
        self.assertEqual(self.document.coverage, "General Liability")
        self.assertEqual(self.document.expires_on, date(2027, 3, 1))

    @override_settings(
        AI_BASE_URL="https://ai.example/v1",
        AI_API_KEY="secret-key",
        AI_MODEL="vision-model",
    )
    @patch("documents.views.extract_document_metadata")
    def test_provider_failure_does_not_change_document(self, extract):
        extract.side_effect = MetadataExtractionError("provider unavailable")
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("documents:extract_ai_metadata", args=[self.item.pk]),
            follow=True,
        )

        self.assertContains(response, "AI metadata extraction is unavailable")
        self.document.refresh_from_db()
        self.assertEqual(self.document.carrier, "Manual Carrier")
        self.assertEqual(self.document.policy_number, "")

    def test_extraction_is_not_available_without_configuration(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("documents:extract_ai_metadata", args=[self.item.pk]),
            follow=True,
        )
        self.assertContains(response, "AI metadata extraction is not available for this plan")

    def test_starter_plan_cannot_use_ai_extraction(self):
        self.org.plan = Organization.PLAN_STARTER
        self.org.save(update_fields=["plan"])
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("documents:extract_ai_metadata", args=[self.item.pk]),
            follow=True,
        )
        self.assertContains(response, "AI metadata extraction is not available for this plan")

    def test_extraction_isolates_workspaces(self):
        self.client.force_login(self.other_user)
        response = self.client.post(
            reverse("documents:extract_ai_metadata", args=[self.item.pk])
        )
        self.assertEqual(response.status_code, 404)

    @override_settings(
        AI_BASE_URL="https://ai.example/v1",
        AI_API_KEY="secret-key",
        AI_MODEL="vision-model",
    )
    @patch("documents.ai.urlopen")
    def test_public_upload_never_calls_ai_provider(self, urlopen):
        token = UploadToken.objects.create(
            request=self.item,
            expires_at=timezone.now() + timedelta(days=7),
        )
        response = self.client.post(
            reverse("documents:public_upload", args=[token.token]),
            {
                "file": SimpleUploadedFile(
                    "vendor-certificate.pdf",
                    (
                        b"%PDF-1.4\n"
                        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
                        b"2 0 obj\n<< /Type /Pages /Kids [] /Count 0 >>\nendobj\n"
                        b"xref\n0 3\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n"
                        b"trailer\n<< /Size 3 /Root 1 0 R >>\nstartxref\n110\n%%EOF\n"
                    ),
                    content_type="application/pdf",
                ),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Upload received")
        urlopen.assert_not_called()

    @override_settings(
        AI_BASE_URL="https://ai.example/v1",
        AI_API_KEY="secret-key",
        AI_MODEL="vision-model",
    )
    @override_settings(
        AI_BASE_URL="https://ai.example/v1",
        AI_API_KEY="secret-key",
        AI_MODEL="vision-model",
    )
    @patch("documents.views.extract_document_metadata")
    def test_provider_error_does_not_expose_secret_or_raw_error(self, extract):
        extract.side_effect = MetadataExtractionError("provider secret-key exploded")
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("documents:extract_ai_metadata", args=[self.item.pk]),
            follow=True,
        )

        self.assertContains(response, "AI metadata extraction is unavailable")
        self.assertNotContains(response, "secret-key")
        self.assertNotContains(response, "exploded")
        self.document.refresh_from_db()
        self.assertEqual(self.document.carrier, "Manual Carrier")

    def test_apply_cannot_target_another_request_in_same_workspace(self):
        other_vendor = Vendor.objects.create(
            organization=self.org,
            name="Another Vendor",
            email="another@example.com",
        )
        other_item = DocumentRequest.objects.create(
            organization=self.org,
            vendor=other_vendor,
            document_type=DocumentRequest.TYPE_COI,
        )
        other_document = Document.objects.create(
            organization=self.org,
            request=other_item,
            file=SimpleUploadedFile(
                "other.pdf",
                b"%PDF-1.4\n% synthetic test document\n%%EOF\n",
                content_type="application/pdf",
            ),
            original_filename="other.pdf",
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("documents:apply_ai_metadata", args=[self.item.pk]),
            {
                "document_id": other_document.pk,
                "carrier": "Must Not Apply",
                "policy_number": "MUST-NOT-APPLY",
                "coverage": "Must Not Apply",
                "expires_on": "2027-03-01",
            },
        )

        self.assertEqual(response.status_code, 404)
        other_document.refresh_from_db()
        self.assertEqual(other_document.carrier, "")
        self.assertEqual(other_document.policy_number, "")
