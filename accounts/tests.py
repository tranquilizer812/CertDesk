from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse

from .forms import SignupForm
from .models import Membership, Organization


class RegistrationTests(TestCase):
    password = "A-very-strong-password-123!"

    def signup_data(self, email="owner@example.com", organization_name="Owner Workspace"):
        return {
            "organization_name": organization_name,
            "email": email,
            "password1": self.password,
            "password2": self.password,
        }

    def test_registration_normalizes_email_and_creates_owner_membership(self):
        response = self.client.post(
            reverse("accounts:signup"),
            self.signup_data(email="Owner@Example.com"),
        )

        self.assertRedirects(response, reverse("documents:dashboard"))
        user = get_user_model().objects.get()
        organization = Organization.objects.get()
        membership = Membership.objects.get(user=user)

        self.assertEqual(user.email, "owner@example.com")
        self.assertEqual(user.username, "owner@example.com")
        self.assertEqual(membership.organization, organization)
        self.assertEqual(membership.role, Membership.ROLE_OWNER)

    def test_case_insensitive_duplicate_leaves_existing_workspace_unchanged(self):
        user = get_user_model().objects.create_user(
            username="owner@example.com",
            email="Owner@Example.com",
            password=self.password,
        )
        organization = Organization.objects.create(name="Existing Workspace")
        Membership.objects.create(
            user=user,
            organization=organization,
            role=Membership.ROLE_OWNER,
        )

        response = self.client.post(
            reverse("accounts:signup"),
            self.signup_data(email="OWNER@example.com", organization_name="Duplicate Workspace"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("email", response.context["form"].errors)
        self.assertEqual(get_user_model().objects.count(), 1)
        self.assertEqual(Organization.objects.count(), 1)
        self.assertEqual(Membership.objects.count(), 1)

    def test_registration_failure_rolls_back_partial_workspace(self):
        create_organization = Organization.objects.create

        def create_then_fail(*args, **kwargs):
            create_organization(*args, **kwargs)
            raise IntegrityError("forced registration failure")

        with patch(
            "accounts.forms.Organization.objects.create",
            side_effect=create_then_fail,
        ):
            response = self.client.post(reverse("accounts:signup"), self.signup_data())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(get_user_model().objects.count(), 0)
        self.assertEqual(Organization.objects.count(), 0)
        self.assertEqual(Membership.objects.count(), 0)

    def test_racing_registrations_keep_only_one_complete_workspace(self):
        first_form = SignupForm(data=self.signup_data(email="owner@example.com"))
        second_form = SignupForm(data=self.signup_data(email="OWNER@example.com"))

        # Validate both forms before either saves to reproduce the check-then-create race.
        self.assertTrue(first_form.is_valid(), first_form.errors)
        self.assertTrue(second_form.is_valid(), second_form.errors)
        first_form.save()
        with self.assertRaises(IntegrityError):
            second_form.save()

        self.assertEqual(get_user_model().objects.count(), 1)
        self.assertEqual(Organization.objects.count(), 1)
        self.assertEqual(Membership.objects.count(), 1)


class AuthenticationRedirectTests(TestCase):
    password = "A-very-strong-password-123!"

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="owner@example.com",
            email="Owner@Example.com",
            password=self.password,
        )
        self.organization = Organization.objects.create(name="Owner Workspace")
        self.membership = Membership.objects.create(
            user=self.user,
            organization=self.organization,
            role=Membership.ROLE_OWNER,
        )

    def test_login_normalizes_email_and_redirects_to_member_workspace(self):
        other_user = get_user_model().objects.create_user(
            username="other@example.com",
            email="other@example.com",
            password=self.password,
        )
        other_organization = Organization.objects.create(name="Other Workspace")
        other_membership = Membership.objects.create(
            user=other_user,
            organization=other_organization,
            role=Membership.ROLE_OWNER,
        )

        login_response = self.client.post(
            reverse("accounts:login"),
            {"username": "OWNER@example.com", "password": self.password},
        )

        self.assertRedirects(login_response, reverse("documents:dashboard"))
        dashboard_response = self.client.get(reverse("documents:dashboard"))
        self.assertEqual(dashboard_response.wsgi_request.user, self.user)
        self.assertEqual(dashboard_response.wsgi_request.user.memberships.get(), self.membership)
        self.assertEqual(dashboard_response.context["organization"], self.organization)
        self.assertNotEqual(dashboard_response.context["organization"], other_organization)
        self.assertEqual(other_user.memberships.get(), other_membership)

    def test_authenticated_user_is_redirected_from_signup(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("accounts:signup"))

        self.assertRedirects(response, reverse("documents:dashboard"))

    def test_authenticated_user_without_membership_does_not_loop_dashboard_to_signup(self):
        self.membership.delete()
        self.client.force_login(self.user)

        dashboard_response = self.client.get(reverse("documents:dashboard"))
        signup_response = self.client.get(reverse("accounts:signup"))

        self.assertRedirects(
            dashboard_response,
            reverse("accounts:signup"),
            fetch_redirect_response=False,
        )
        self.assertEqual(signup_response.status_code, 200)
        self.assertContains(signup_response, "Create your workspace")

    def test_logout_redirects_to_landing(self):
        self.client.force_login(self.user)

        response = self.client.post(reverse("accounts:logout"))

        self.assertRedirects(response, reverse("core:landing"))
        self.assertNotIn("_auth_user_id", self.client.session)
