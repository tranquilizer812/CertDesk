from datetime import timedelta
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Organization
from documents.models import Document, DocumentRequest, Property, UploadToken, Vendor


class CertDeskSmokeWorkflowTests(TestCase):
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
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="smoke@example.com",
            email="smoke@example.com",
            password="SafePass-123!",
        )
        self.other_user = user_model.objects.create_user(
            username="other-smoke@example.com",
            email="other-smoke@example.com",
            password="SafePass-123!",
        )
        self.org = Organization.objects.create(name="Smoke Property Co")
        self.other_org = Organization.objects.create(name="Other Smoke Property Co")
        Membership.objects.create(user=self.user, organization=self.org, role="owner")
        Membership.objects.create(
            user=self.other_user,
            organization=self.other_org,
            role="owner"
        )

    def csrf_token(self, client, url):
        response = client.get(url)
        self.assertEqual(response.status_code, 200)
        return client.cookies["csrftoken"].value

    def pdf_upload(self, name="certificate.pdf"):
        objects = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            (
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                b"/Contents 4 0 R /Resources << >> >>"
            ),
            (
                b"<< /Length 42 >>\nstream\n"
                b"BT\n/F1 12 Tf\n72 720 Td\n(CertDesk test) Tj\nET\n"
                b"endstream"
            ),
        ]
        pdf = bytearray(b"%PDF-1.4\n")
        offsets = []
        for number, body in enumerate(objects, start=1):
            offsets.append(len(pdf))
            pdf.extend(f"{number} 0 obj\n".encode("ascii"))
            pdf.extend(body)
            pdf.extend(b"\nendobj\n")
        xref_offset = len(pdf)
        pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
        pdf.extend(b"0000000000 65535 f \n")
        for offset in offsets:
            pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
        pdf.extend(
            (
                f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
                f"startxref\n{xref_offset}\n%%EOF\n"
            ).encode("ascii")
        )
        return SimpleUploadedFile(
            name,
            bytes(pdf),
            content_type="application/pdf",
        )

    def test_demo_path_reaches_landing_dashboard_list_and_detail(self):
        client = Client(enforce_csrf_checks=True)
        landing = client.get(reverse("core:landing"))
        self.assertEqual(landing.status_code, 200)
        self.assertContains(landing, "Explore the live demo")

        response = client.post(
            reverse("core:demo_login"),
            {"csrfmiddlewaretoken": self.csrf_token(client, reverse("core:landing"))},
        )
        self.assertRedirects(response, reverse("documents:dashboard"))

        dashboard = client.get(reverse("documents:dashboard"))
        self.assertEqual(dashboard.status_code, 200)
        self.assertContains(dashboard, "Northstar Property Demo")

        listing = client.get(reverse("documents:list"))
        self.assertEqual(listing.status_code, 200)
        self.assertContains(listing, "Bright Roof Co.")

        item = DocumentRequest.objects.filter(
            organization__name="Northstar Property Demo"
        ).first()
        self.assertIsNotNone(item)
        detail = client.get(
            reverse("documents:request_detail", args=[item.pk])
        )
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "Bright Roof Co.")

    def test_signup_path_manages_vendor_property_request_and_upload(self):
        client = Client(enforce_csrf_checks=True)
        signup_url = reverse("accounts:signup")
        response = client.post(
            signup_url,
            {
                "organization_name": "Integration Workspace",
                "email": "integration@example.com",
                "password1": "A-very-strong-password-123!",
                "password2": "A-very-strong-password-123!",
                "csrfmiddlewaretoken": self.csrf_token(client, signup_url),
            },
        )
        self.assertRedirects(response, reverse("documents:dashboard"))

        list_url = reverse("documents:list")
        response = client.post(
            reverse("documents:create_vendor"),
            {
                "name": "Integration Vendor",
                "email": "vendor@integration.example",
                "contact_name": "Casey Smith",
                "trade": "Roofing",
                "csrfmiddlewaretoken": self.csrf_token(client, list_url),
            },
        )
        self.assertRedirects(response, list_url)

        response = client.post(
            reverse("documents:create_property"),
            {
                "name": "Integration Property",
                "address": "10 Test Street",
                "csrfmiddlewaretoken": self.csrf_token(client, list_url),
            },
        )
        self.assertRedirects(response, list_url)

        vendor = Vendor.objects.get(
            organization__name="Integration Workspace",
            name="Integration Vendor",
        )
        prop = Property.objects.get(
            organization__name="Integration Workspace",
            name="Integration Property",
        )
        response = client.post(
            reverse("documents:create_request"),
            {
                "vendor": vendor.pk,
                "property": prop.pk,
                "document_type": "coi",
                "due_date": (timezone.localdate() + timedelta(days=45)).isoformat(),
                "csrfmiddlewaretoken": self.csrf_token(client, list_url),
            },
        )
        self.assertRedirects(response, list_url)

        item = DocumentRequest.objects.get(
            organization__name="Integration Workspace",
            vendor=vendor,
        )
        detail_url = reverse("documents:request_detail", args=[item.pk])
        response = client.post(
            reverse("documents:upload_document", args=[item.pk]),
            {
                "file": self.pdf_upload(),
                "carrier": "Example Carrier",
                "policy_number": "POL-100",
                "coverage": "General Liability",
                "expires_on": (
                    timezone.localdate() + timedelta(days=60)
                ).isoformat(),
                "csrfmiddlewaretoken": self.csrf_token(client, detail_url),
            },
        )
        self.assertRedirects(response, detail_url)
        self.assertEqual(item.documents.count(), 1)
        self.assertEqual(item.status, "active")

        listing = client.get(list_url)
        self.assertContains(listing, "Integration Vendor")
        self.assertContains(listing, "Integration Property")


    def test_workspace_data_is_isolated_across_dashboard_list_and_detail(self):
        vendor = Vendor.objects.create(
            organization=self.org,
            name="Private Vendor",
            email="private@example.com",
        )
        prop = Property.objects.create(
            organization=self.org,
            name="Private Property",
        )
        private_item = DocumentRequest.objects.create(
            organization=self.org,
            vendor=vendor,
            property=prop,
        )
        other_vendor = Vendor.objects.create(
            organization=self.other_org,
            name="Visible Vendor",
            email="visible@example.com",
        )
        DocumentRequest.objects.create(
            organization=self.other_org,
            vendor=other_vendor,
        )

        self.client.force_login(self.other_user)
        dashboard = self.client.get(reverse("documents:dashboard"))
        self.assertEqual(dashboard.context["organization"], self.other_org)
        self.assertNotContains(dashboard, "Private Vendor")

        listing = self.client.get(reverse("documents:list"))
        self.assertContains(listing, "Visible Vendor")
        self.assertNotContains(listing, "Private Vendor")

        response = self.client.get(
            reverse("documents:request_detail", args=[private_item.pk])
        )
        self.assertEqual(response.status_code, 404)

        response = self.client.post(
            reverse("documents:create_request"),
            {"vendor": vendor.pk, "document_type": "coi"},
        )
        self.assertRedirects(response, reverse("documents:list"))
        self.assertFalse(
            DocumentRequest.objects.filter(
                organization=self.other_org,
                vendor=vendor,
            ).exists()
        )

    def test_dashboard_counts_all_document_statuses(self):
        vendor = Vendor.objects.create(
            organization=self.org,
            name="Status Vendor",
            email="status@example.com",
        )
        today = timezone.localdate()
        status_dates = {
            "active": today + timedelta(days=60),
            "expiring": today + timedelta(days=10),
            "expired": today - timedelta(days=1),
        }
        for status, expires_on in status_dates.items():
            item = DocumentRequest.objects.create(
                organization=self.org,
                vendor=vendor,
            )
            Document.objects.create(
                organization=self.org,
                request=item,
                file=self.pdf_upload(f"{status}.pdf"),
                original_filename=f"{status}.pdf",
                expires_on=expires_on,
            )
        DocumentRequest.objects.create(
            organization=self.org,
            vendor=vendor,
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("documents:dashboard"))
        self.assertEqual(
            response.context["counts"],
            {"active": 1, "expiring": 1, "expired": 1, "missing": 1},
        )


    def test_login_logout_redirects_and_csrf_enforcement(self):
        client = Client(enforce_csrf_checks=True)
        login_url = reverse("accounts:login")
        token = self.csrf_token(client, login_url)

        rejected = client.post(
            login_url,
            {"username": self.user.email, "password": "SafePass-123!"},
        )
        self.assertEqual(rejected.status_code, 403)

        logged_in = client.post(
            login_url,
            {
                "username": self.user.email,
                "password": "SafePass-123!",
                "csrfmiddlewaretoken": token,
            },
        )
        self.assertRedirects(logged_in, reverse("documents:dashboard"))

        dashboard_url = reverse("documents:dashboard")
        logout_url = reverse("accounts:logout")
        token = self.csrf_token(client, dashboard_url)
        rejected_logout = client.post(logout_url)
        self.assertEqual(rejected_logout.status_code, 403)

        logged_out = client.post(
            logout_url,
            {"csrfmiddlewaretoken": token},
        )
        self.assertRedirects(logged_out, reverse("core:landing"))
        self.assertNotIn("_auth_user_id", client.session)

    def test_expired_public_upload_link_rejects_file(self):
        vendor = Vendor.objects.create(
            organization=self.org,
            name="Public Vendor",
            email="public@example.com",
        )
        item = DocumentRequest.objects.create(
            organization=self.org,
            vendor=vendor,
        )
        token = UploadToken.objects.create(
            request=item,
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        upload_url = reverse("documents:public_upload", args=[token.token])

        page = self.client.get(upload_url)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "expired")

        response = self.client.post(
            upload_url,
            {"file": self.pdf_upload("expired-link.pdf")},
        )
        self.assertContains(response, "expired")
        token.refresh_from_db()
        self.assertIsNone(token.used_at)
        self.assertEqual(item.documents.count(), 0)
