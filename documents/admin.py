from django.contrib import admin

from .models import Document, DocumentRequest, Property, ReminderLog, UploadToken, Vendor


@admin.register(Property)
class PropertyAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "address")
    list_filter = ("organization",)
    search_fields = ("name", "address")


@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "email", "trade")
    list_filter = ("organization",)
    search_fields = ("name", "email", "contact_name")


@admin.register(DocumentRequest)
class DocumentRequestAdmin(admin.ModelAdmin):
    list_display = ("vendor", "document_type", "property", "due_date", "status")
    list_filter = ("organization", "document_type")
    search_fields = ("vendor__name", "title")


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("original_filename", "request", "carrier", "expires_on", "uploaded_at")
    list_filter = ("organization",)
    search_fields = ("original_filename", "carrier", "policy_number")


@admin.register(ReminderLog)
class ReminderLogAdmin(admin.ModelAdmin):
    list_display = ("request", "kind", "sent_on", "sent_at")
    list_filter = ("kind", "sent_on")


@admin.register(UploadToken)
class UploadTokenAdmin(admin.ModelAdmin):
    list_display = ("request", "created_at", "expires_at", "used_at")
    list_filter = ("created_at", "used_at")
