import csv
from datetime import datetime, timedelta
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Q, OuterRef, Subquery
from django.http import FileResponse, Http404, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import Membership, Organization

from .ai import (
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


def requests_for_organization(organization):
    return DocumentRequest.objects.filter(
        organization=organization,
        vendor__organization=organization,
    ).filter(
        Q(property__isnull=True) | Q(property__organization=organization)
    )


def request_relationships_valid(item):
    return (
        item.vendor.organization_id == item.organization_id
        and (
            not item.property_id
            or item.property.organization_id == item.organization_id
        )
    )


def import_csv_rows(org, reader, type_map):
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
    return imported, errors


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
    today = timezone.localdate()
    latest_doc_subquery = Document.objects.filter(
        request=OuterRef("pk"),
        organization=OuterRef("organization"),
    ).order_by("-uploaded_at").values("expires_on")[:1]
    items = requests_for_organization(org).select_related(
        "vendor", "property"
    ).annotate(
        latest_expires_on=Subquery(latest_doc_subquery),
    )
    counts = {"active": 0, "expiring": 0, "expired": 0, "missing": 0}
    for item in items:
        expires_on = item.latest_expires_on
        if expires_on is None:
            counts["missing"] += 1
        elif expires_on < today:
            counts["expired"] += 1
        elif expires_on <= today + timedelta(days=30):
            counts["expiring"] += 1
        else:
            counts["active"] += 1
    upcoming = [
        r for r in items
        if r.latest_expires_on is not None
        and r.latest_expires_on <= today + timedelta(days=30)
    ][:6]
    recent = Document.objects.filter(
        organization=org,
        request__organization=org,
        request__vendor__organization=org,
    ).filter(
        Q(request__property__isnull=True) | Q(request__property__organization=org)
    ).select_related("request__vendor")[:5]
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
    today = timezone.localdate()
    latest_doc_subquery = Document.objects.filter(
        request=OuterRef("pk"),
        organization=OuterRef("organization"),
    ).order_by("-uploaded_at").values("expires_on")[:1]
    items = requests_for_organization(org).select_related(
        "vendor", "property"
    ).annotate(
        latest_expires_on=Subquery(latest_doc_subquery),
    )
    if query:
        items = items.filter(
            Q(vendor__name__icontains=query)
            | Q(title__icontains=query)
            | Q(property__name__icontains=query)
        )
    if status:
        if status == "missing":
            items = items.filter(latest_expires_on__isnull=True)
        elif status == "expired":
            items = items.filter(latest_expires_on__lt=today)
        elif status == "expiring":
            items = items.filter(
                latest_expires_on__gte=today,
                latest_expires_on__lte=today + timedelta(days=30),
            )
        elif status == "active":
            items = items.filter(latest_expires_on__gt=today + timedelta(days=30))
    vendors = Vendor.objects.filter(organization=org)
    properties = Property.objects.filter(organization=org)
    paginator = Paginator(items, 25)
    page_number = request.GET.get("page")
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)
    return render(
        request,
        "documents/list.html",
        {
            "items": page_obj,
            "page_obj": page_obj,
            "query": query,
            "status": status,
            "vendors": vendors,
            "properties": properties,
        },
    )


@login_required
@require_POST
def create_property(request):
    org = current_organization(request)
    if org is None:
        messages.warning(request, "Сначала создайте рабочее пространство, чтобы добавлять имущество.")
        return redirect("accounts:signup")
    if request.method == "POST":
        form = PropertyForm(request.POST, organization=org)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.organization = org
            obj.save()
            messages.success(request, "Имущество добавлено.")
        else:
            messages.error(request, "Проверьте детали имущества и попробуйте снова.")
    return redirect("documents:list")


@login_required
@require_POST
def create_vendor(request):
    org = current_organization(request)
    if org is None:
        messages.warning(request, "Сначала создайте рабочее пространство, чтобы добавлять поставщиков.")
        return redirect("accounts:signup")
    if request.method == "POST":
        form = VendorForm(request.POST, organization=org)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.organization = org
            obj.save()
            messages.success(request, "Поставщик добавлен.")
        else:
            messages.error(request, "Проверьте детали поставщика и попробуйте снова.")
    return redirect("documents:list")


@login_required
def vendor_list(request):
    org = current_organization(request)
    if not org:
        return redirect("accounts:signup")
    vendors = Vendor.objects.filter(organization=org).order_by("name")
    return render(request, "documents/vendor_list.html", {"vendors": vendors, "organization": org})


@login_required
def property_list(request):
    org = current_organization(request)
    if not org:
        return redirect("accounts:signup")
    properties = Property.objects.filter(organization=org).order_by("name")
    return render(request, "documents/property_list.html", {"properties": properties, "organization": org})


@login_required
@require_POST
def create_request(request):
    org = current_organization(request)
    if org is None:
        return HttpResponseForbidden("A workspace membership is required.")
    form = DocumentRequestForm(request.POST, organization=org)
    if form.is_valid():
        with transaction.atomic():
            locked_org = Organization.objects.select_for_update().get(pk=org.pk)
            if locked_org.document_requests.count() >= locked_org.document_limit:
                messages.error(
                    request,
                    f"Your {locked_org.get_plan_display()} plan includes up to "
                    f"{locked_org.document_limit} tracked documents. Upgrade to add more.",
                )
            else:
                item = form.save(commit=False)
                item.organization = locked_org
                item.save()
                messages.success(request, "Document request created.")
    else:
        messages.error(request, "Check the request details and try again.")
    return redirect("documents:list")


@login_required
@require_POST
def import_csv(request):
    org = current_organization(request)
    if org is None:
        return HttpResponseForbidden("A workspace membership is required.")
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
    with transaction.atomic():
        locked_org = Organization.objects.select_for_update().get(pk=org.pk)
        imported, errors = import_csv_rows(locked_org, reader, type_map)
    summary = f"Imported {imported} document request(s)."
    if errors:
        summary += f" Skipped {len(errors)} row(s): {errors[:3]}"
        messages.warning(request, summary)
    else:
        messages.success(request, summary)
    return redirect("documents:list")


@login_required
@require_POST
def delete_request(request, pk):
    org = current_organization(request)
    item = get_object_or_404(requests_for_organization(org), pk=pk)
    documents = item.documents.all()
    if documents.exclude(organization=org).exists():
        messages.error(request, "This request contains inconsistent workspace data and was not removed.")
        return redirect("documents:list")
    for document in documents:
        document.file.delete(save=False)
    item.delete()
    messages.success(request, "Request removed.")
    return redirect("documents:list")


@login_required
@require_POST
def email_upload_link(request, pk):
    org = current_organization(request)
    item = get_object_or_404(requests_for_organization(org), pk=pk)
    token = UploadToken.objects.create(request=item, expires_at=timezone.now() + timedelta(days=7))
    upload_url = request.build_absolute_uri(token.get_absolute_url())
    try:
        sent = send_mail(
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
    except Exception:
        # Удаляем токен только если он не был использован другим процессом
        UploadToken.objects.filter(
            pk=token.pk, used_at__isnull=True,
        ).delete()
        messages.error(
            request,
            "The upload link could not be emailed. No link was issued; please try again.",
        )
        return redirect("documents:request_detail", pk=item.pk)
    if sent != 1:
        UploadToken.objects.filter(
            pk=token.pk, used_at__isnull=True,
        ).delete()
        messages.error(
            request,
            "The upload link could not be emailed. No link was issued; please try again.",
        )
        return redirect("documents:request_detail", pk=item.pk)
    messages.success(request, f"Upload link sent to {item.vendor.email}.")
    return redirect("documents:request_detail", pk=item.pk)


@login_required
@require_POST
def generate_upload_link(request, pk):
    org = current_organization(request)
    item = get_object_or_404(requests_for_organization(org), pk=pk)
    token = UploadToken.objects.create(request=item, expires_at=timezone.now() + timedelta(days=7))
    copy_url = request.build_absolute_uri(token.get_absolute_url())
    request.session[f"last_upload_url:{item.pk}"] = copy_url
    messages.success(request, "7-day vendor upload link created. The link is shown below.")
    return redirect("documents:request_detail", pk=item.pk)


@login_required
def request_detail(request, pk):
    org = current_organization(request)
    item = get_object_or_404(requests_for_organization(org), pk=pk)
    latest = item.latest_document
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
    item = get_object_or_404(requests_for_organization(org), pk=pk)
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
    latest = item.latest_document
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


def claim_upload_token(upload_token):
    return bool(
        UploadToken.objects.filter(
            pk=upload_token.pk,
            used_at__isnull=True,
            expires_at__gt=timezone.now(),
        ).update(used_at=timezone.now())
    )


def public_upload(request, token):
    upload_token = get_object_or_404(
        UploadToken.objects.select_related("request__vendor", "request__property"),
        token=token,
    )
    item = upload_token.request
    if not request_relationships_valid(item):
        raise Http404
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
        try:
            with transaction.atomic():
                if not claim_upload_token(upload_token):
                    transaction.set_rollback(True)
                    return render(
                        request,
                        "documents/public_upload.html",
                        {"item": item, "token": upload_token, "expired": True, "form": None},
                    )
                document.save()
        except Exception:
            if document.file and document.file.name:
                document.file.delete(save=False)
            raise
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
    item = get_object_or_404(requests_for_organization(org), pk=pk)
    latest = item.latest_document
    if not latest:
        messages.error(request, "Upload a document before requesting AI extraction.")
        return redirect("documents:request_detail", pk=item.pk)
    if not is_ai_extraction_enabled(org):
        messages.info(request, "AI metadata extraction is not available for this plan.")
        return redirect("documents:request_detail", pk=item.pk)

    try:
        with latest.file.open("rb") as uploaded_file:
            metadata = extract_document_metadata(uploaded_file)
    except Exception:
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
    item = get_object_or_404(requests_for_organization(org), pk=pk)
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
def request_list_json(request):
    """AJAX endpoint: returns filtered document requests as JSON."""
    org = current_organization(request)
    if not org:
        return JsonResponse({"error": "No workspace membership"}, status=403)
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    today = timezone.localdate()
    latest_doc_subquery = Document.objects.filter(
        request=OuterRef("pk"),
        organization=OuterRef("organization"),
    ).order_by("-uploaded_at").values("expires_on")[:1]
    items = requests_for_organization(org).select_related(
        "vendor", "property"
    ).annotate(
        latest_expires_on=Subquery(latest_doc_subquery),
    )
    if query:
        items = items.filter(
            Q(vendor__name__icontains=query)
            | Q(title__icontains=query)
            | Q(property__name__icontains=query)
        )
    if status:
        if status == "missing":
            items = items.filter(latest_expires_on__isnull=True)
        elif status == "expired":
            items = items.filter(latest_expires_on__lt=today)
        elif status == "expiring":
            items = items.filter(
                latest_expires_on__gte=today,
                latest_expires_on__lte=today + timedelta(days=30),
            )
        elif status == "active":
            items = items.filter(latest_expires_on__gt=today + timedelta(days=30))
    results = []
    for item in items[:50]:
        expires_on = item.latest_expires_on
        if expires_on is None:
            item_status = "missing"
        elif expires_on < today:
            item_status = "expired"
        elif expires_on <= today + timedelta(days=30):
            item_status = "expiring"
        else:
            item_status = "active"
        results.append({
            "id": item.pk,
            "vendor": item.vendor.name,
            "contact": item.vendor.contact_name or "",
            "email": item.vendor.email,
            "property": item.property.name if item.property else "",
            "document_type": item.get_document_type_display(),
            "status": item_status,
            "due_date": item.due_date.isoformat() if item.due_date else "",
            "expires_on": expires_on.isoformat() if expires_on else "",
            "url": reverse("documents:request_detail", kwargs={"pk": item.pk}),
        })
    return JsonResponse({"results": results, "count": len(results)})


@login_required
def download_document(request, document_pk):
    org = current_organization(request)
    document = get_object_or_404(
        Document.objects.select_related("request")
        .filter(
            organization=org,
            request__organization=org,
            request__vendor__organization=org,
        )
        .filter(
            Q(request__property__isnull=True) | Q(request__property__organization=org)
        ),
        pk=document_pk,
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
    today = timezone.localdate()
    latest_doc_subquery = Document.objects.filter(
        request=OuterRef("pk"),
        organization=OuterRef("organization"),
    ).order_by("-uploaded_at").values("expires_on", "original_filename")[:1]
    items = requests_for_organization(org).select_related(
        "vendor", "property"
    ).annotate(
        latest_expires_on=Subquery(latest_doc_subquery.values("expires_on")),
        latest_original_filename=Subquery(latest_doc_subquery.values("original_filename")),
    )
    for item in items:
        expires_on = item.latest_expires_on
        if expires_on is None:
            status = "missing"
        elif expires_on < today:
            status = "expired"
        elif expires_on <= today + timedelta(days=30):
            status = "expiring"
        else:
            status = "active"
        writer.writerow(
            [
                csv_safe_cell(item.vendor.name),
                csv_safe_cell(item.vendor.contact_name),
                csv_safe_cell(item.vendor.email),
                csv_safe_cell(item.property.name if item.property else ""),
                csv_safe_cell(item.get_document_type_display()),
                csv_safe_cell(status),
                csv_safe_cell(item.due_date or ""),
                csv_safe_cell(expires_on if expires_on else ""),
                csv_safe_cell(item.latest_original_filename or ""),
            ]
        )
    return response
