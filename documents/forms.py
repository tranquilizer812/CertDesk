import re
from pathlib import Path

from django import forms
from PIL import Image, UnidentifiedImageError

from .models import Document, DocumentRequest, Property, Vendor

ALLOWED_EXTENSIONS = ("pdf", "png", "jpg", "jpeg")
ALLOWED_IMAGE_FORMATS = {"png": "PNG", "jpg": "JPEG", "jpeg": "JPEG"}
ALLOWED_CSV_MIME_TYPES = {
    "text/csv",
    "application/csv",
    "application/vnd.ms-excel",
    "text/plain",
    "application/octet-stream",
}
ALLOWED_MIME_TYPES = {
    "pdf": {"application/pdf", "application/x-pdf"},
    "png": {"image/png"},
    "jpg": {"image/jpeg"},
    "jpeg": {"image/jpeg"},
}


def is_structurally_valid_pdf(content):
    if not re.match(rb"%PDF-\d\.\d\r?\n", content):
        return False
    if not re.search(rb"\d+\s+\d+\s+obj\b", content):
        return False
    if b"endobj" not in content:
        return False
    xref_match = list(re.finditer(rb"startxref\s+(\d+)", content))
    if not xref_match:
        return False
    try:
        xref_offset = int(xref_match[-1].group(1))
    except ValueError:
        return False
    if xref_offset >= len(content) or not content.rstrip().endswith(b"%%EOF"):
        return False

    xref_section = content[xref_offset:]
    if xref_section.startswith(b"xref"):
        entries = re.findall(rb"(?m)^(\d{10}) \d{5} ([nf])", xref_section)
        if not entries:
            return False
        for offset, entry_type in entries:
            if entry_type == b"n":
                object_offset = int(offset)
                if object_offset >= len(content) or not re.match(
                    rb"\d+\s+\d+\s+obj\b", content[object_offset:]
                ):
                    return False
        return b"/Root" in xref_section

    object_match = re.match(rb"\d+\s+\d+\s+obj\b", xref_section)
    if not object_match:
        return False
    object_end = xref_section.find(b"endobj", object_match.end())
    if object_end == -1:
        return False
    xref_object = xref_section[object_match.end():object_end]
    return (
        b"/Type" in xref_object
        and b"/XRef" in xref_object
        and b"/Root" in xref_object
    )


class CsvImportForm(forms.Form):
    file = forms.FileField(
        label="CSV file",
        help_text="Columns: vendor, vendor_email, property, document_type, due_date.",
    )

    def clean_file(self):
        uploaded = self.cleaned_data["file"]
        if Path(uploaded.name).suffix.lower() != ".csv":
            raise forms.ValidationError("Upload a CSV file.")
        if uploaded.size > 5 * 1024 * 1024:
            raise forms.ValidationError("The maximum CSV size is 5 MB.")
        content_type = (uploaded.content_type or "").split(";", 1)[0].strip().lower()
        if content_type not in ALLOWED_CSV_MIME_TYPES:
            raise forms.ValidationError("Upload a CSV file.")
        return uploaded


class PropertyForm(forms.ModelForm):
    class Meta:
        model = Property
        fields = ("name", "address")
        widgets = {"address": forms.TextInput(attrs={"placeholder": "Street, city, state"})}

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if self.organization and Property.objects.filter(
            organization=self.organization, name=name
        ).exists():
            raise forms.ValidationError("A property with this name already exists.")
        return name


class VendorForm(forms.ModelForm):
    class Meta:
        model = Vendor
        fields = ("name", "contact_name", "email", "trade")
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "Bright Roof Co."}),
            "contact_name": forms.TextInput(attrs={"placeholder": "Optional contact name"}),
            "email": forms.EmailInput(attrs={"placeholder": "vendor@example.com"}),
            "trade": forms.TextInput(attrs={"placeholder": "Roofing, cleaning, repairs…"}),
        }

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if self.organization and Vendor.objects.filter(
            organization=self.organization, name=name
        ).exists():
            raise forms.ValidationError("A vendor with this name already exists.")
        return name


class DocumentRequestForm(forms.ModelForm):
    class Meta:
        model = DocumentRequest
        fields = ("vendor", "property", "document_type", "title", "due_date")
        widgets = {"due_date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        if organization:
            self.fields["vendor"].queryset = Vendor.objects.filter(organization=organization)
            self.fields["property"].queryset = Property.objects.filter(organization=organization)
            self.instance.organization = organization
        else:
            self.fields["vendor"].queryset = Vendor.objects.none()
            self.fields["property"].queryset = Property.objects.none()
        self.fields["property"].required = False
        self.fields["title"].required = False
        self.fields["due_date"].required = False


class DocumentForm(forms.ModelForm):
    class Meta:
        model = Document
        fields = ("file", "carrier", "policy_number", "coverage", "expires_on", "notes")
        widgets = {
            "file": forms.ClearableFileInput(attrs={"accept": ".pdf,.png,.jpg,.jpeg"}),
            "expires_on": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3, "placeholder": "Internal note (visible only to your team)"}),
        }

    def clean_file(self):
        uploaded = self.cleaned_data["file"]
        extension = Path(uploaded.name).suffix.lower().lstrip(".")
        if extension not in ALLOWED_EXTENSIONS:
            raise forms.ValidationError("Upload a PDF, PNG, or JPG file.")
        if uploaded.size > 10 * 1024 * 1024:
            raise forms.ValidationError("The maximum file size is 10 MB.")

        content_type = (uploaded.content_type or "").split(";", 1)[0].strip().lower()
        if content_type not in ALLOWED_MIME_TYPES[extension]:
            raise forms.ValidationError("The file MIME type does not match its extension.")

        uploaded.file.seek(0)
        try:
            if extension == "pdf":
                content = uploaded.file.read()
                if not is_structurally_valid_pdf(content):
                    raise forms.ValidationError("The uploaded file is not a valid PDF document.")
            else:
                try:
                    with Image.open(uploaded.file) as image:
                        detected_format = image.format
                        image.verify()
                    with Image.open(uploaded.file) as image:
                        image.load()
                except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as exc:
                    raise forms.ValidationError("The uploaded file is not a valid image.") from exc
                if detected_format != ALLOWED_IMAGE_FORMATS[extension]:
                    raise forms.ValidationError("The file content does not match its extension.")
                if uploaded.content_type and detected_format == "PNG":
                    expected_type = "image/png"
                elif uploaded.content_type and detected_format == "JPEG":
                    expected_type = "image/jpeg"
                else:
                    expected_type = None
                if expected_type and content_type != expected_type:
                    raise forms.ValidationError("The file MIME type does not match its content.")
        finally:
            uploaded.file.seek(0)
        return uploaded

    def clean_expires_on(self):
        return self.cleaned_data.get("expires_on")


class VendorUploadForm(DocumentForm):
    class Meta(DocumentForm.Meta):
        fields = ("file", "carrier", "policy_number", "coverage", "expires_on")


class MetadataReviewForm(forms.Form):
    """Editable review of AI suggestions before they become authoritative."""

    document_id = forms.IntegerField(widget=forms.HiddenInput)
    carrier = forms.CharField(
        max_length=180,
        required=False,
        label="Carrier",
    )
    policy_number = forms.CharField(
        max_length=120,
        required=False,
        label="Policy number",
    )
    coverage = forms.CharField(
        max_length=180,
        required=False,
        label="Coverage",
    )
    expires_on = forms.DateField(
        required=False,
        label="Expires on",
        widget=forms.DateInput(attrs={"type": "date"}),
    )

    def __init__(self, *args, locked_fields=(), **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs["id"] = f"id_ai_review_{field_name}"
            if field_name in locked_fields:
                field.disabled = True
                field.widget.attrs["title"] = "Existing manual value will be preserved"

