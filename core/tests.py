from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Membership, Organization


class StripeCheckoutTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="checkout@example.com",
            email="checkout@example.com",
            password="SafePass-123!",
        )
        self.org = Organization.objects.create(name="Checkout Workspace")
        Membership.objects.create(
            user=self.user,
            organization=self.org,
            role=Membership.ROLE_OWNER,
        )

    @override_settings(
        STRIPE_SECRET_KEY="sk_test_checkout",
        STRIPE_STARTER_PRICE_ID="price_starter",
        STRIPE_GROWTH_PRICE_ID="price_growth",
    )
    @patch("stripe.checkout.Session.create")
    def test_valid_starter_plan_creates_checkout(self, create_session):
        create_session.return_value = SimpleNamespace(
            url="https://checkout.stripe.com/test-session"
        )
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("core:stripe_checkout"),
            {"plan": Organization.PLAN_STARTER},
        )
        self.assertRedirects(
            response,
            "https://checkout.stripe.com/test-session",
            fetch_redirect_response=False,
        )
        create_session.assert_called_once()
        self.assertEqual(
            create_session.call_args.kwargs["line_items"],
            [{"price": "price_starter", "quantity": 1}],
        )


class StripeWebhookTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="billing@example.com",
            email="billing@example.com",
            password="SafePass-123!",
        )
        self.org = Organization.objects.create(name="Billing Workspace")
        Membership.objects.create(
            user=self.user,
            organization=self.org,
            role=Membership.ROLE_OWNER,
        )

    @override_settings(
        STRIPE_SECRET_KEY="sk_test_webhook",
        STRIPE_WEBHOOK_SECRET="whsec_test",
        STRIPE_STARTER_PRICE_ID="price_starter",
        STRIPE_GROWTH_PRICE_ID="price_growth",
    )
    @patch("stripe.Webhook.construct_event")
    def test_subscription_update_changes_plan_and_status(self, construct_event):
        construct_event.return_value = {
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "id": "sub_123",
                    "customer": "cus_123",
                    "status": "active",
                    "metadata": {"organization_id": str(self.org.pk)},
                    "items": {
                        "data": [{"price": {"id": "price_growth"}}]
                    },
                }
            },
        }
        response = self.client.post(
            reverse("core:stripe_webhook"),
            data="{}",
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="test-signature",
        )
        self.assertEqual(response.status_code, 200)
        self.org.refresh_from_db()
        self.assertEqual(self.org.plan, Organization.PLAN_GROWTH)
        self.assertEqual(self.org.subscription_status, "active")
        self.assertEqual(self.org.stripe_customer_id, "cus_123")
        self.assertEqual(self.org.stripe_subscription_id, "sub_123")

    @override_settings(
        STRIPE_SECRET_KEY="sk_test_webhook",
        STRIPE_WEBHOOK_SECRET="whsec_test",
    )
    @patch("stripe.Webhook.construct_event")
    def test_failed_invoice_marks_subscription_past_due(self, construct_event):
        self.org.stripe_customer_id = "cus_123"
        self.org.stripe_subscription_id = "sub_123"
        self.org.save(update_fields=["stripe_customer_id", "stripe_subscription_id"])
        construct_event.return_value = {
            "type": "invoice.payment_failed",
            "data": {
                "object": {
                    "customer": "cus_123",
                    "subscription": "sub_123",
                }
            },
        }
        response = self.client.post(
            reverse("core:stripe_webhook"),
            data="{}",
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="test-signature",
        )
        self.assertEqual(response.status_code, 200)
        self.org.refresh_from_db()
        self.assertEqual(self.org.subscription_status, "past_due")

    @override_settings(
        STRIPE_SECRET_KEY="sk_test_webhook",
        STRIPE_WEBHOOK_SECRET="whsec_test",
    )
    def test_webhook_rejects_non_post_requests(self):
        response = self.client.get(reverse("core:stripe_webhook"))
        self.assertEqual(response.status_code, 405)

    @override_settings(
        STRIPE_SECRET_KEY="",
        STRIPE_WEBHOOK_SECRET="",
    )
    def test_unconfigured_webhook_returns_service_unavailable(self):
        response = self.client.post(
            reverse("core:stripe_webhook"),
            data="{}",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 503)

    @override_settings(
        STRIPE_SECRET_KEY="sk_test_webhook",
        STRIPE_WEBHOOK_SECRET="whsec_test",
    )
    @patch("stripe.Webhook.construct_event")
    def test_invalid_signature_returns_bad_request(self, construct_event):
        construct_event.side_effect = ValueError("invalid signature")
        response = self.client.post(
            reverse("core:stripe_webhook"),
            data="{}",
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="bad-signature",
        )
        self.assertEqual(response.status_code, 400)
