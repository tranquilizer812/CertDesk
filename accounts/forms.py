from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User
from django.db import transaction

from .models import Membership as MembershipRole
from .models import Organization


class SignupForm(UserCreationForm):
    organization_name = forms.CharField(max_length=160, label="Company name")
    email = forms.EmailField(label="Work email")

    class Meta:
        model = User
        fields = ("email", "password1", "password2")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].widget.attrs["autocomplete"] = "email"
        self.fields["organization_name"].widget.attrs["placeholder"] = "Northstar Property Management"

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("A workspace already exists for this email.")
        return email

    def clean_organization_name(self):
        name = self.cleaned_data["organization_name"].strip()
        if len(name) > 160:
            raise forms.ValidationError("Company name must be 160 characters or fewer.")
        return name

    @transaction.atomic
    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        user.username = user.email
        if commit:
            user.save()
            org = Organization.objects.create(name=self.cleaned_data["organization_name"])
            org.memberships.create(user=user, role=MembershipRole.ROLE_OWNER)
        return user


class LoginForm(AuthenticationForm):
    username = forms.EmailField(label="Work email")
    remember_me = forms.BooleanField(required=False, label="Keep me signed in")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs["autocomplete"] = "email"
        self.fields["username"].widget.attrs["placeholder"] = "you@company.com"

    def clean_username(self):
        return self.cleaned_data["username"].strip().lower()
