"""Settings for the CertDesk SaaS."""
import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY or len(SECRET_KEY) < 50:
    raise ImproperlyConfigured(
        "SECRET_KEY must be set in .env to a unique value of at least 50 characters."
    )
DEBUG = env_bool("DEBUG", False)
ALLOWED_HOSTS = [h.strip() for h in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = [h.strip() for h in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",") if h.strip()]
CSRF_USE_SESSIONS = False
CSRF_HEADER_NAME = "HTTP_X_CSRFTOKEN"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "documents",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "certdesk.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.product_context",
            ],
        },
    },
]
WSGI_APPLICATION = "certdesk.wsgi.application"

database_url = os.getenv("DATABASE_URL", "").strip()
DATABASES = {
    "default": dj_database_url.parse(database_url, conn_max_age=600)
    if database_url
    else {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        "CONN_MAX_AGE": 600,
    }
}
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "en-us"
TIME_ZONE = os.getenv("TIME_ZONE", "America/New_York")
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "media/"
media_root = os.getenv("MEDIA_ROOT", "").strip()
MEDIA_ROOT = (
    Path(media_root).expanduser().resolve()
    if media_root
    else BASE_DIR / "media"
)
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "documents:dashboard"
LOGOUT_REDIRECT_URL = "core:landing"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", not DEBUG)
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", not DEBUG)
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", not DEBUG)
SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "31536000" if not DEBUG else "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024

EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = os.getenv("EMAIL_HOST", "")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "CertDesk <hello@example.com>")
DEFAULT_FROM_EMAIL = EMAIL_FROM

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_STARTER_PRICE_ID = os.getenv("STRIPE_STARTER_PRICE_ID", "")
STRIPE_GROWTH_PRICE_ID = os.getenv("STRIPE_GROWTH_PRICE_ID", "")
AI_BASE_URL = os.getenv("AI_BASE_URL", "")
AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "")
AI_TIMEOUT_SECONDS = int(os.getenv("AI_TIMEOUT_SECONDS", "30"))
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")
DEMO_MODE = env_bool("DEMO_MODE", True)

# SECRET_KEY validity already enforced above (must be set and ≥50 chars)
