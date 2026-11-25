import builtins
import uuid
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils import timezone

from accounts.models import Organization


class Property(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="properties")
    name = models.CharField(max_length=160)
    address = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(fields=["organization", "name"], name="unique_property_per_org")
        ]

    def __str__(self):
        return self.name


class Vendor(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="vendors")
    name = models.CharField(max_length=160)
    contact_name = models.CharField(max_length=160, blank=True)
    email = models.EmailField()
    trade = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(fields=["organization", "name"], name="unique_vendor_per_org")
        ]

    def __str__(self):
        return self.name


class DocumentRequest(models.Model):
    TYPE_COI = "coi"
    TYPE_LICENSE = "license"
    TYPE_W9 = "w9"
    TYPE_OTHER = "other"
    TYPE_CHOICES = [
        (TYPE_COI, "Certificate of Insurance"),
        (TYPE_LICENSE, "License / Registration"),
        (TYPE_W9, "W-9"),
        (TYPE_OTHER, "Other document"),
    ]

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="document_requests")
    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name="document_requests")
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="document_requests", null=True, blank=True)
    document_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=TYPE_COI)
    title = models.CharField(max_length=160, blank=True)
    due_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("due_date", "created_at")
        verbose_name_plural = "document requests"

    def __str__(self):
        return f"{self.vendor.name} · {self.get_document_type_display()}"

    def clean(self):
        super().clean()
        if self.vendor_id and self.vendor.organization_id != self.organization_id:
            raise ValidationError("The vendor must belong to the same organization.")
        if self.property_id and self.property.organization_id != self.organization_id:
            raise ValidationError("The property must belong to the same organization.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    @builtins.property
    def status(self):
        document = self.latest_document
        if not document:
            return "missing"
        if document.expires_on and document.expires_on < timezone.localdate():
            return "expired"
        if document.expires_on and document.expires_on <= timezone.localdate() + timedelta(days=30):
            return "expiring"
        return "active"

    @builtins.property
    def latest_document(self):
        return self.documents.filter(organization=self.organization).order_by("-uploaded_at").first()


class Document(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="documents")
    request = models.ForeignKey(DocumentRequest, on_delete=models.CASCADE, related_name="documents")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_documents",
    )
    file = models.FileField(upload_to="documents/%Y/%m/")
    original_filename = models.CharField(max_length=255)
    carrier = models.CharField(max_length=180, blank=True)
    policy_number = models.CharField(max_length=120, blank=True)
    coverage = models.CharField(max_length=180, blank=True)
    expires_on = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-uploaded_at",)

    def __str__(self):
        return self.original_filename

    def clean(self):
        super().clean()
        if self.request_id and self.request.organization_id != self.organization_id:
            raise ValidationError("The request must belong to the same organization.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    @property
    def status(self):
        today = timezone.localdate()
        if self.expires_on and self.expires_on < today:
            return "expired"
        if self.expires_on and self.expires_on <= today + timedelta(days=30):
            return "expiring"
        return "active"


class ReminderLog(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="reminder_logs")
    request = models.ForeignKey(DocumentRequest, on_delete=models.CASCADE, related_name="reminder_logs")
    kind = models.CharField(max_length=20)
    sent_on = models.DateField()
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["request", "sent_on"], name="unique_daily_reminder")
        ]
        ordering = ("-sent_at",)


class UploadToken(models.Model):
    request = models.ForeignKey(DocumentRequest, on_delete=models.CASCADE, related_name="upload_tokens")
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return str(self.token)

    @property
    def is_usable(self):
        return self.used_at is None and self.expires_at > timezone.now()

    def get_absolute_url(self):
        return reverse("documents:public_upload", kwargs={"token": self.token})
