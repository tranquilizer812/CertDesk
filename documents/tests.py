from datetime import timedelta
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Organization

from .models import Document, DocumentRequest, Property, Vendor


class CertDeskWorkflowTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.media_directory = tempfile.TemporaryDirectory()
        cls.media_settings = override_settings(MEDIA_ROOT=cls.media_directory.name)
        cls.media_settings.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls.media_settings.disable()
        cls.media_directory.cleanup()

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="owner@example.com", email="owner@example.com", password="SafePass-123!"
        )
        self.other_user = get_user_model().objects.create_user(
            username="other@example.com", email="other@example.com", password="SafePass-123!"
        )
        self.org = Organization.objects.create(name="Test Property Co")
        self.other_org = Organization.objects.create(name="Other Property Co")
        Membership.objects.create(user=self.user, organization=self.org, role="owner")
        Membership.objects.create(user=self.other_user, organization=self.other_org, role="owner")
        self.property = Property.objects.create(organization=self.org, name="Maple Court")
        self.vendor = Vendor.objects.create(
            organization=self.org, name="Bright Roof Co", email="vendor@example.com"
        )
        self.item = DocumentRequest.objects.create(
            organization=self.org,
            vendor=self.vendor,
            property=self.property,
            document_type=DocumentRequest.TYPE_COI,
        )

    def test_signup_creates_workspace_and_owner_membership(self):
        response = self.client.post(
            reverse("accounts:signup"),
            {
                "organization_name": "New Workspace",
                "email": "new@example.com",
                "password1": "A-very-strong-password-123!",
                "password2": "A-very-strong-password-123!",
            },
        )
        self.assertRedirects(response, reverse("documents:dashboard"))
        self.assertTrue(Organization.objects.filter(name="New Workspace").exists())
        self.assertTrue(Membership.objects.filter(user__email="new@example.com", role="owner").exists())

    def test_document_status_tracks_expiration(self):
        self.assertEqual(self.item.status, "missing")
        today = timezone.localdate()
        for expires, expected in [
            (today - timedelta(days=1), "expired"),
            (today + timedelta(days=10), "expiring"),
            (today + timedelta(days=60), "active"),
        ]:
            Document.objects.create(
                organization=self.org,
                request=self.item,
                file=SimpleUploadedFile("certificate.pdf", b"demo"),
                original_filename="certificate.pdf",
                expires_on=expires,
            )
            self.assertEqual(self.item.status, expected)

    def test_workspace_data_is_isolated(self):
        response = self.client.force_login(self.other_user)
        response = self.client.get(reverse("documents:request_detail", args=[self.item.pk]))
        self.assertEqual(response.status_code, 404)

    def test_public_upload_link_is_single_use(self):
        from .models import UploadToken

        token = UploadToken.objects.create(
            request=self.item, expires_at=timezone.now() + timedelta(days=7)
        )
        upload = SimpleUploadedFile(
            "certificate.pdf",
            b"%PDF-1.4\n% synthetic test document\n%%EOF\n",
            content_type="application/pdf",
        )
        response = self.client.post(
            reverse("documents:public_upload", args=[token.token]),
            {"file": upload, "expires_on": (timezone.localdate() + timedelta(days=90)).isoformat()},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Upload received")
        token.refresh_from_db()
        self.assertIsNotNone(token.used_at)
        self.assertEqual(self.item.documents.count(), 1)

        second = self.client.post(
            reverse("documents:public_upload", args=[token.token]),
            {
                "file": SimpleUploadedFile(
                    "second.pdf",
                    b"%PDF-1.4\n% synthetic test document\n%%EOF\n",
                    content_type="application/pdf",
                )
            },
        )
        self.assertContains(second, "expired")

    def test_csv_export_requires_login_and_contains_workspace_rows(self):
        response = self.client.get(reverse("documents:export_csv"))
        self.assertEqual(response.status_code, 302)
        self.client.force_login(self.user)
        response = self.client.get(reverse("documents:export_csv"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response["Content-Type"])
        self.assertContains(response, "Bright Roof Co")

    def test_csv_import_creates_vendors_properties_and_requests(self):
        self.client.force_login(self.user)
        csv_data = (
            "vendor,vendor_email,property,document_type,due_date\n"
            "Imported Co,imported@example.com,Oak House,coi,2027-01-15\n"
        )
        upload = SimpleUploadedFile(
            "requests.csv", csv_data.encode("utf-8"), content_type="text/csv"
        )
        response = self.client.post(reverse("documents:import_csv"), {"file": upload})
        self.assertRedirects(response, reverse("documents:list"))
        vendor = Vendor.objects.get(organization=self.org, name="Imported Co")
        prop = Property.objects.get(organization=self.org, name="Oak House")
        item = DocumentRequest.objects.get(organization=self.org, vendor=vendor)
        self.assertEqual(item.property, prop)
        self.assertEqual(item.due_date.isoformat(), "2027-01-15")

    def test_reminder_command_emails_missing_and_expired_documents(self):
        from django.core import mail

        self.item.due_date = timezone.localdate() - timedelta(days=1)
        self.item.save(update_fields=["due_date"])
        call_command("send_expiration_reminders", days=30)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Document still needed", mail.outbox[0].subject)
        call_command("send_expiration_reminders", days=30)
        self.assertEqual(len(mail.outbox), 1)

    def test_plan_limit_blocks_new_requests(self):
        self.org.plan = Organization.PLAN_STARTER
        self.org.save()
        DocumentRequest.objects.bulk_create([
            DocumentRequest(
                organization=self.org,
                vendor=self.vendor,
                property=self.property,
                document_type=DocumentRequest.TYPE_COI,
            )
            for _ in range(75 - 1)
        ])
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("documents:create_request"),
            {"vendor": self.vendor.pk, "document_type": "coi"},
        )
        self.assertRedirects(response, reverse("documents:list"))
        self.assertEqual(DocumentRequest.objects.filter(organization=self.org).count(), 75)

    def test_demo_login_seeds_sample_workspace(self):
        response = self.client.get(reverse("core:landing"))
        self.assertContains(response, "csrfmiddlewaretoken")
        response = self.client.post(reverse("core:demo_login"))
        self.assertRedirects(response, reverse("documents:dashboard"))
        response = self.client.get(reverse("documents:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Northstar Property Demo")
        self.assertContains(response, "Bright Roof Co")

    def test_signup_rejects_duplicate_email_case_insensitively(self):
        organization_count = Organization.objects.count()
        response = self.client.post(
            reverse("accounts:signup"),
            {
                "organization_name": "Duplicate Workspace",
                "email": "OWNER@EXAMPLE.COM",
                "password1": "A-very-strong-password-123!",
                "password2": "A-very-strong-password-123!",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "A workspace already exists for this email.")
        self.assertEqual(Organization.objects.count(), organization_count)

    def test_public_upload_form_excludes_internal_notes(self):
        from .models import UploadToken

        token = UploadToken.objects.create(
            request=self.item, expires_at=timezone.now() + timedelta(days=7)
        )
        response = self.client.get(
            reverse("documents:public_upload", args=[token.token])
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="notes"')

    def test_public_upload_rejects_spoofed_pdf(self):
        from .models import UploadToken

        token = UploadToken.objects.create(
            request=self.item, expires_at=timezone.now() + timedelta(days=7)
        )
        upload = SimpleUploadedFile(
            "certificate.pdf",
            b"not actually a pdf",
            content_type="application/pdf",
        )
        response = self.client.post(
            reverse("documents:public_upload", args=[token.token]),
            {"file": upload},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "not a valid PDF document")
        token.refresh_from_db()
        self.assertIsNone(token.used_at)
        self.assertEqual(self.item.documents.count(), 0)

    def test_document_download_requires_login_and_isolates_workspaces(self):
        document = Document.objects.create(
            organization=self.org,
            request=self.item,
            file=SimpleUploadedFile(
                "certificate.pdf",
                b"%PDF-1.4\n% synthetic test document\n%%EOF\n",
                content_type="application/pdf",
            ),
            original_filename="certificate.pdf",
        )
        url = reverse("documents:download_document", args=[document.pk])
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.other_user)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response["Content-Disposition"])
        response.close()

    def test_csv_export_neutralizes_spreadsheet_formulas(self):
        self.vendor.name = "  =HYPERLINK(\"https://example.invalid\")"
        self.vendor.save(update_fields=["name"])
        self.client.force_login(self.user)
        response = self.client.get(reverse("documents:export_csv"))
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"'  =HYPERLINK", response.content)

    def test_csv_import_respects_plan_limit(self):
        self.org.plan = Organization.PLAN_STARTER
        self.org.save()
        DocumentRequest.objects.bulk_create([
            DocumentRequest(
                organization=self.org,
                vendor=self.vendor,
                property=self.property,
                document_type=DocumentRequest.TYPE_COI,
            )
            for _ in range(75 - 1)
        ])
        self.client.force_login(self.user)
        csv_data = (
            "vendor,vendor_email,document_type\n"
            "First Co,first@example.com,coi\n"
            "Second Co,second@example.com,coi\n"
        )
        response = self.client.post(
            reverse("documents:import_csv"),
            {
                "file": SimpleUploadedFile(
                    "requests.csv",
                    csv_data.encode("utf-8"),
                    content_type="text/csv",
                )
            },
        )
        self.assertRedirects(response, reverse("documents:list"))
        self.assertEqual(DocumentRequest.objects.filter(organization=self.org).count(), 75)

    def test_reminder_dry_run_does_not_create_upload_token(self):
        from .models import UploadToken

        self.item.due_date = timezone.localdate() - timedelta(days=1)
        self.item.save(update_fields=["due_date"])
        call_command("send_expiration_reminders", days=30, dry_run=True)
        self.assertEqual(UploadToken.objects.count(), 0)
