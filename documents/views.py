import csv
from datetime import datetime, timedelta
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import Membership

from .ai import (
    MetadataExtractionError,
    extract_document_metadata,
    is_ai_extraction_enabled,
)
from .forms import (
    CsvImportForm,
    DocumentForm,
    DocumentRequestForm,
    MetadataReviewForm,
    PropertyForm,
    VendorForm,
    VendorUploadForm,
)
from .models import Document, DocumentRequest, Property, UploadToken, Vendor


def current_organization(request):
    membership = Membership.objects.filter(user=request.user).select_related("organization").first()
    return membership.organization if membership else None


def csv_safe_cell(value):
    text = "" if value is None else str(value)
    if text.lstrip().startswith(("=", "+", "-", "@")):
        return f"'{text}"
    return text


@login_required
def dashboard(request):
    org = current_organization(request)
    if not org:
        return redirect("accounts:signup")
    items = DocumentRequest.objects.filter(organization=org).select_related("vendor", "property")
    counts = {"active": 0, "expiring": 0, "expired": 0, "missing": 0}
    for item in items:
        counts[item.status] += 1
    upcoming = [r for r in items if r.status in {"expired", "expiring"}][:6]
    recent = Document.objects.filter(organization=org).select_related("request__vendor")[:5]
    return render(
        request,
        "documents/dashboard.html",
        {"organization": org, "counts": counts, "upcoming": upcoming, "recent": recent},
    )


@login_required
def request_list(request):
    org = current_organization(request)
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    items = DocumentRequest.objects.filter(organization=org).select_related("vendor", "property")
    if query:
        items = items.filter(
            Q(vendor__name__icontains=query)
            | Q(title__icontains=query)
            | Q(property__name__icontains=query)
        )
    if status:
        items = [item for item in items if item.status == status]
    vendors = Vendor.objects.filter(organization=org)
    properties = Property.objects.filter(organization=org)
    return render(
        request,
        "documents/list.html",
        {"items": items, "query": query, "status": status, "vendors": vendors, "properties": properties},
    )


@login_required
@require_POST
def create_property(request):
    org = current_organization(request)
    form = PropertyForm(request.POST, organization=org)
    if form.is_valid():
        obj = form.save(commit=False)
        obj.organization = org
        obj.save()
        messages.success(request, "Property added.")
    else:
        messages.error(request, "Check the property details and try again.")
    return redirect("documents:list")


@login_required
@require_POST
def create_vendor(request):
    org = current_organization(request)
    form = VendorForm(request.POST, organization=org)
    if form.is_valid():
        obj = form.save(commit=False)
        obj.organization = org
        obj.save()
        messages.success(request, "Vendor added.")
    else:
        messages.error(request, "Check the vendor details and try again.")
    return redirect("documents:list")


@login_required
@require_POST
def create_request(request):
    org = current_organization(request)
    if org.document_requests.count() >= org.document_limit:
        messages.error(request, f"Your {org.get_plan_display()} plan includes up to {org.document_limit} tracked documents. Upgrade to add more.")
        return redirect("documents:list")
    form = DocumentRequestForm(request.POST, organization=org)
    if form.is_valid():
        item = form.save(commit=False)
        item.organization = org
        item.save()
        messages.success(request, "Document request created.")
    else:
        messages.error(request, "Check the request details and try again.")
    return redirect("documents:list")


@login_required
@require_POST
def import_csv(request):
    org = current_organization(request)
    form = CsvImportForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, "Choose a CSV file smaller than 5 MB.")
        return redirect("documents:list")
    try:
        text = form.cleaned_data["file"].read().decode("utf-8-sig")
    except UnicodeDecodeError:
        messages.error(request, "The CSV must be encoded as UTF-8.")
        return redirect("documents:list")
    reader = csv.DictReader(text.splitlines())
    if reader.fieldnames:
        reader.fieldnames = [name.strip().lower() for name in reader.fieldnames]
    required = {"vendor", "vendor_email", "document_type"}
    if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
        messages.error(request, "CSV columns must include vendor, vendor_email, and document_type.")
        return redirect("documents:list")
    type_map = {
        "coi": DocumentRequest.TYPE_COI,
        "certificate of insurance": DocumentRequest.TYPE_COI,
        "license": DocumentRequest.TYPE_LICENSE,
        "license / registration": DocumentRequest.TYPE_LICENSE,
        "w-9": DocumentRequest.TYPE_W9,
        "w9": DocumentRequest.TYPE_W9,
        "other": DocumentRequest.TYPE_OTHER,
    }
    imported = 0
    errors = []
    remaining = max(org.document_limit - org.document_requests.count(), 0)
    for line_number, row in enumerate(reader, start=2):
        vendor_name = (row.get("vendor") or "").strip()
        vendor_email = (row.get("vendor_email") or "").strip()
        doc_type_raw = (row.get("document_type") or "").strip().lower()
        document_type = type_map.get(doc_type_raw)
        if not vendor_name or not vendor_email or not document_type:
            errors.append(f"line {line_number}: invalid vendor, email, or document type")
            continue
        try:
            validate_email(vendor_email)
        except ValidationError:
            errors.append(f"line {line_number}: vendor_email is invalid")
            continue
        if remaining == 0:
            errors.append(f"line {line_number}: plan document limit reached")
            continue
        property_name = (row.get("property") or "").strip()
        due_date = None
        due_raw = (row.get("due_date") or "").strip()
        if due_raw:
            try:
                due_date = datetime.strptime(due_raw, "%Y-%m-%d").date()
            except ValueError:
                errors.append(f"line {line_number}: due_date must use YYYY-MM-DD")
                continue
        vendor, _ = Vendor.objects.get_or_create(
            organization=org,
            name=vendor_name,
            defaults={"email": vendor_email},
        )
        if vendor.email != vendor_email:
            vendor.email = vendor_email
            vendor.save(update_fields=["email"])
        property_obj = None
        if property_name:
            property_obj, _ = Property.objects.get_or_create(
                organization=org, name=property_name
            )
        DocumentRequest.objects.create(
            organization=org,
            vendor=vendor,
            property=property_obj,
            document_type=document_type,
            due_date=due_date,
        )
        imported += 1
        remaining -= 1
    summary = f"Imported {imported} document request(s)."
    if errors:
        summary += f" Skipped {len(errors)} row(s): {errors[:3]}"
    messages.success(request, summary)
    return redirect("documents:list")


@login_required
@require_POST
def delete_request(request, pk):
    org = current_organization(request)
    item = get_object_or_404(DocumentRequest, pk=pk, organization=org)
    for document in item.documents.all():
        document.file.delete(save=False)
    item.delete()
    messages.success(request, "Request removed.")
    return redirect("documents:list")


@login_required
@require_POST
def email_upload_link(request, pk):
    org = current_organization(request)
    item = get_object_or_404(DocumentRequest, pk=pk, organization=org)
    token = UploadToken.objects.create(request=item, expires_at=timezone.now() + timedelta(days=7))
    upload_url = request.build_absolute_uri(token.get_absolute_url())
    send_mail(
        subject=f"Document request: {item.get_document_type_display()}",
        message=(
            f"Hello {item.vendor.contact_name or item.vendor.name},\n\n"
            f"Please upload your {item.get_document_type_display()} using this secure link:\n"
            f"{upload_url}\n\n"
            "The link expires in 7 days and can be used once."
        ),
        from_email=None,
        recipient_list=[item.vendor.email],
        fail_silently=False,
    )
    messages.success(request, f"Upload link sent to {item.vendor.email}.")
    return redirect("documents:request_detail", pk=item.pk)


@login_required
@require_POST
def generate_upload_link(request, pk):
    org = current_organization(request)
    item = get_object_or_404(DocumentRequest, pk=pk, organization=org)
    token = UploadToken.objects.create(request=item, expires_at=timezone.now() + timedelta(days=7))
    copy_url = request.build_absolute_uri(token.get_absolute_url())
    request.session[f"last_upload_url:{item.pk}"] = copy_url
    messages.success(request, "7-day vendor upload link created. The link is shown below.")
    return redirect("documents:request_detail", pk=item.pk)


@login_required
def request_detail(request, pk):
    org = current_organization(request)
    item = get_object_or_404(DocumentRequest, pk=pk, organization=org)
    latest = item.documents.order_by("-uploaded_at").first()
    return render(
        request,
        "documents/detail.html",
        {
            "item": item,
            "latest": latest,
            "organization": org,
            "upload_form": DocumentForm(),
            "upload_url": request.session.get(f"last_upload_url:{item.pk}", ""),
            "ai_enabled": is_ai_extraction_enabled(org),
            "metadata_review_form": None,
        },
    )


@login_required
@require_POST
def upload_document(request, pk):
    org = current_organization(request)
    item = get_object_or_404(DocumentRequest, pk=pk, organization=org)
    form = DocumentForm(request.POST, request.FILES)
    if form.is_valid():
        document = form.save(commit=False)
        document.organization = org
        document.request = item
        document.uploaded_by = request.user
        document.original_filename = Path(request.FILES["file"].name).name
        document.save()
        messages.success(request, "Document uploaded and expiry tracking started.")
        return redirect("documents:request_detail", pk=item.pk)
    messages.error(request, "Check the document details and try again.")
    latest = item.documents.order_by("-uploaded_at").first()
    return render(
        request,
        "documents/detail.html",
        {
            "item": item,
            "latest": latest,
            "organization": org,
            "upload_form": form,
            "upload_url": "",
            "ai_enabled": is_ai_extraction_enabled(org),
            "metadata_review_form": None,
        },
    )


def public_upload(request, token):
    upload_token = get_object_or_404(UploadToken, token=token)
    item = upload_token.request
    if not upload_token.is_usable:
        return render(
            request,
            "documents/public_upload.html",
            {"item": item, "token": upload_token, "expired": True, "form": None},
        )
    form = VendorUploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        document = form.save(commit=False)
        document.organization = item.organization
        document.request = item
        document.original_filename = Path(request.FILES["file"].name).name
        with transaction.atomic():
            claimed = UploadToken.objects.filter(
                pk=upload_token.pk,
                used_at__isnull=True,
                expires_at__gt=timezone.now(),
            ).update(used_at=timezone.now())
            if not claimed:
                transaction.set_rollback(True)
                return render(
                    request,
                    "documents/public_upload.html",
                    {"item": item, "token": upload_token, "expired": True, "form": None},
                )
            document.save()
        return render(request, "documents/public_upload_success.html", {"item": item})
    return render(
        request,
        "documents/public_upload.html",
        {"item": item, "token": upload_token, "expired": False, "form": form},
    )


@login_required
@require_POST
def extract_ai_metadata(request, pk):
    org = current_organization(request)
    item = get_object_or_404(DocumentRequest, pk=pk, organization=org)
    latest = item.documents.order_by("-uploaded_at").first()
    if not latest:
        messages.error(request, "Upload a document before requesting AI extraction.")
        return redirect("documents:request_detail", pk=item.pk)
    if not is_ai_extraction_enabled(org):
        messages.info(request, "AI metadata extraction is not available for this plan.")
        return redirect("documents:request_detail", pk=item.pk)

    try:
        with latest.file.open("rb") as uploaded_file:
            metadata = extract_document_metadata(uploaded_file)
    except (MetadataExtractionError, OSError):
        messages.error(
            request,
            "AI metadata extraction is unavailable. The document was not changed; enter the details manually.",
        )
        return redirect("documents:request_detail", pk=item.pk)

    initial = {
        "document_id": latest.pk,
        "carrier": latest.carrier or metadata["carrier"],
        "policy_number": latest.policy_number or metadata["policy_number"],
        "coverage": latest.coverage or metadata["coverage"],
        "expires_on": latest.expires_on or metadata["expires_on"],
    }
    locked_fields = [
        field_name
        for field_name in ("carrier", "policy_number", "coverage", "expires_on")
        if getattr(latest, field_name)
    ]
    messages.info(request, "Review the AI suggestions before applying them to this document.")
    return render(
        request,
        "documents/detail.html",
        {
            "item": item,
            "latest": latest,
            "organization": org,
            "upload_form": DocumentForm(),
            "upload_url": request.session.get(f"last_upload_url:{item.pk}", ""),
            "ai_enabled": is_ai_extraction_enabled(org),
            "metadata_review_form": MetadataReviewForm(
                initial=initial,
                locked_fields=locked_fields,
            ),
        },
    )


@login_required
@require_POST
def apply_ai_metadata(request, pk):
    org = current_organization(request)
    item = get_object_or_404(DocumentRequest, pk=pk, organization=org)
    form = MetadataReviewForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Check the suggested details and try again.")
        return redirect("documents:request_detail", pk=item.pk)

    document = get_object_or_404(
        Document,
        pk=form.cleaned_data["document_id"],
        organization=org,
        request=item,
    )
    if not is_ai_extraction_enabled(org):
        messages.info(request, "AI metadata extraction is not available for this plan.")
        return redirect("documents:request_detail", pk=item.pk)
    updates = []
    for field in ("carrier", "policy_number", "coverage"):
        value = form.cleaned_data.get(field, "").strip()
        if not getattr(document, field) and value:
            setattr(document, field, value)
            updates.append(field)
    expires_on = form.cleaned_data.get("expires_on")
    if not document.expires_on and expires_on:
        document.expires_on = expires_on
        updates.append("expires_on")
    if updates:
        document.save(update_fields=updates)
    messages.success(request, "Reviewed metadata applied to the document.")
    return redirect("documents:request_detail", pk=item.pk)


@login_required
def download_document(request, document_pk):
    org = current_organization(request)
    document = get_object_or_404(
        Document.objects.select_related("request"),
        pk=document_pk,
        organization=org,
    )
    response = FileResponse(
        document.file.open("rb"),
        as_attachment=True,
        filename=document.original_filename,
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; sandbox"
    return response


@login_required
def export_csv(request):
    org = current_organization(request)
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="certdesk-documents.csv"'
    writer = csv.writer(response)
    writer.writerow(
        [
            "Vendor", "Contact", "Email", "Property", "Document type", "Status",
            "Due date", "Expires on", "Latest file",
        ]
    )
    items = DocumentRequest.objects.filter(organization=org).select_related(
        "vendor", "property"
    ).prefetch_related("documents")
    for item in items:
        latest = item.documents.order_by("-uploaded_at").first()
        writer.writerow(
            [
                csv_safe_cell(item.vendor.name),
                csv_safe_cell(item.vendor.contact_name),
                csv_safe_cell(item.vendor.email),
                csv_safe_cell(item.property.name if item.property else ""),
                csv_safe_cell(item.get_document_type_display()),
                csv_safe_cell(item.status),
                csv_safe_cell(item.due_date or ""),
                csv_safe_cell(latest.expires_on if latest and latest.expires_on else ""),
                csv_safe_cell(latest.original_filename if latest else ""),
            ]
        )
    return response
