"""Optional AI-assisted extraction of document metadata.

The provider is configured by the operator. This module deliberately sends no
workspace, vendor, property, or original filename context to the provider.
"""

import base64
import json
import mimetypes
from datetime import date
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from django.conf import settings

from accounts.models import Organization


class MetadataExtractionError(Exception):
    """Raised when a provider response cannot safely be used."""


MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024
FIELD_LIMITS = {
    "carrier": 180,
    "policy_number": 120,
    "coverage": 180,
}
EXTRACTION_PROMPT = """Extract only metadata that is explicitly visible in this document.
Return one JSON object with exactly these optional keys:
- carrier: insurance carrier or issuing organization
- policy_number: policy, certificate, or license number
- coverage: coverage type or license category
- expires_on: expiration date as YYYY-MM-DD

Use an empty string for a value that is not present. Do not guess. Do not include
vendor names, property addresses, policyholders, or any commentary. Return JSON
only."""


def is_ai_configured():
    return bool(
        settings.AI_BASE_URL.strip()
        and settings.AI_API_KEY.strip()
        and settings.AI_MODEL.strip()
    )


def is_ai_extraction_enabled(organization):
    return is_ai_configured() and organization.plan == Organization.PLAN_GROWTH


def _chat_completions_url(base_url):
    try:
        parsed = urlsplit(base_url.strip())
    except ValueError as exc:
        raise MetadataExtractionError("Invalid AI endpoint configuration.") from exc

    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise MetadataExtractionError("Invalid AI endpoint configuration.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise MetadataExtractionError("Invalid AI endpoint configuration.")

    local_host = parsed.hostname.lower() in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not local_host:
        raise MetadataExtractionError("AI endpoint must use HTTPS.")

    path = parsed.path.rstrip("/")
    if not path.endswith("/chat/completions"):
        path = f"{path}/chat/completions"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _file_content_part(uploaded_file):
    try:
        uploaded_file.seek(0)
    except (AttributeError, OSError, ValueError):
        pass

    name = Path(getattr(uploaded_file, "name", "document")).name
    extension = Path(name).suffix.lower()
    mime_type = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
    }.get(extension)
    if mime_type is None:
        mime_type = mimetypes.guess_type(name)[0]
    if mime_type not in {
        "application/pdf",
        "image/png",
        "image/jpeg",
    }:
        raise MetadataExtractionError("Unsupported document type for metadata extraction.")

    try:
        content = uploaded_file.read(MAX_FILE_BYTES + 1)
    except (AttributeError, OSError, ValueError) as exc:
        raise MetadataExtractionError("The document could not be read.") from exc
    if len(content) > MAX_FILE_BYTES:
        raise MetadataExtractionError("The document is too large for metadata extraction.")

    encoded = base64.b64encode(content).decode("ascii")
    data_url = f"data:{mime_type};base64,{encoded}"
    if mime_type == "application/pdf":
        return {
            "type": "file",
            "file": {
                "filename": "document.pdf",
                "file_data": data_url,
            },
        }
    return {
        "type": "image_url",
        "image_url": {"url": data_url},
    }


def _decode_content(content):
    if not isinstance(content, str):
        raise MetadataExtractionError("The AI provider returned an invalid response.")
    value = content.strip()
    if value.startswith("```"):
        lines = value.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        value = "\n".join(lines).strip()
    try:
        payload = json.loads(value)
    except (json.JSONDecodeError, TypeError) as exc:
        raise MetadataExtractionError("The AI provider returned invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise MetadataExtractionError("The AI provider returned invalid metadata.")
    return payload


def _validated_metadata(payload):
    result = {}
    for field, limit in FIELD_LIMITS.items():
        value = payload.get(field, "")
        if value is None:
            value = ""
        if not isinstance(value, str):
            raise MetadataExtractionError("The AI provider returned invalid metadata.")
        value = value.strip()
        if len(value) > limit:
            raise MetadataExtractionError("The AI provider returned invalid metadata.")
        result[field] = value

    expires_on = payload.get("expires_on", "")
    if expires_on is None:
        expires_on = ""
    if not isinstance(expires_on, str):
        raise MetadataExtractionError("The AI provider returned an invalid expiration date.")
    expires_on = expires_on.strip()
    if expires_on:
        try:
            expires_on = date.fromisoformat(expires_on).isoformat()
        except ValueError as exc:
            raise MetadataExtractionError(
                "The AI provider returned an invalid expiration date."
            ) from exc
    result["expires_on"] = expires_on
    return result


def extract_document_metadata(uploaded_file):
    """Return validated metadata or raise MetadataExtractionError.

    Provider errors are intentionally converted to a generic exception so they
    cannot expose API keys, raw responses, or extracted sensitive values.
    """
    if not is_ai_configured():
        raise MetadataExtractionError("AI metadata extraction is not configured.")

    endpoint = _chat_completions_url(settings.AI_BASE_URL)
    file_part = _file_content_part(uploaded_file)
    request_body = {
        "model": settings.AI_MODEL.strip(),
        "messages": [
            {
                "role": "system",
                "content": EXTRACTION_PROMPT,
            },
            {
                "role": "user",
                "content": [file_part],
            },
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0,
    }
    request = Request(
        endpoint,
        data=json.dumps(request_body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.AI_API_KEY.strip()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=settings.AI_TIMEOUT_SECONDS) as response:
            raw_response = response.read(MAX_RESPONSE_BYTES + 1)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise MetadataExtractionError("The AI provider could not be reached.") from exc
    if len(raw_response) > MAX_RESPONSE_BYTES:
        raise MetadataExtractionError("The AI provider response was too large.")

    try:
        provider_payload = json.loads(raw_response)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise MetadataExtractionError("The AI provider returned invalid JSON.") from exc
    try:
        message = provider_payload["choices"][0]["message"]
        if message.get("refusal"):
            raise MetadataExtractionError("The AI provider declined to analyze the document.")
        content = message["content"]
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        raise MetadataExtractionError("The AI provider returned an invalid response.") from exc
    return _validated_metadata(_decode_content(content))
