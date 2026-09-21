"""
Settings for Drug POS.

Everything that differs between a developer machine and the shop's server
comes from environment variables, so the same code runs on both:

    DRUGPOS_DEBUG=0          production mode (default: 1)
    DRUGPOS_DATA_DIR=...     where the database and secret key live (default: backend/data)
    DRUGPOS_ALLOWED_HOSTS=.. comma separated (default: *) — the server only lives on the shop LAN
"""

import os
import secrets
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BASE_DIR.parent
DATA_DIR = Path(os.environ.get("DRUGPOS_DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
FRONTEND_DIST = PROJECT_DIR / "frontend" / "dist"


def _load_secret_key() -> str:
    """Each shop gets its own key, generated on first run and kept next to the database."""
    if key := os.environ.get("DRUGPOS_SECRET_KEY"):
        return key
    key_file = DATA_DIR / "secret_key.txt"
    if not key_file.exists():
        key_file.write_text(secrets.token_urlsafe(50), encoding="utf-8")
    return key_file.read_text(encoding="utf-8").strip()


SECRET_KEY = _load_secret_key()
DEBUG = os.environ.get("DRUGPOS_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("DRUGPOS_ALLOWED_HOSTS", "*").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
    "accounts",
    "inventory",
    "sales",
    "reports",
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

# Receipts and labels are printed from a hidden same-origin iframe.
X_FRAME_OPTIONS = "SAMEORIGIN"

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# SQLite is plenty for one shop with 3–5 counters.
# IMMEDIATE: every transaction takes the write lock up front, so two counters
# can never sell the same last box at the same time.
# WAL + synchronous=FULL: readers don't block the writer, and a committed sale
# survives a power cut.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DATA_DIR / "drugpos.sqlite3",
        "OPTIONS": {
            "transaction_mode": "IMMEDIATE",
            "timeout": 20,
            "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL;",
        },
    }
}

AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "/admin/login/"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

if "test" in sys.argv:
    # PIN and password checks are deliberately slow; tests don't need that.
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

LANGUAGE_CODE = "th"
TIME_ZONE = "Asia/Bangkok"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATIC_ROOT.mkdir(exist_ok=True)
# The React build (frontend/dist) is served as static files; index.html by core.views.spa.
STATICFILES_DIRS = [FRONTEND_DIST] if FRONTEND_DIST.exists() else []
WHITENOISE_USE_FINDERS = DEBUG

MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.console.EmailBackend",
    },
}

# How long a pharmacist's confirmation stays valid before payment (seconds).
DISPENSE_APPROVAL_MAX_AGE = 30 * 60
PIN_MAX_ATTEMPTS = 5
PIN_LOCK_MINUTES = 5
