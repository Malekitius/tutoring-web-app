"""Settings for the local application and the optional accounts pilot."""

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("TUTOR_DATA_DIR", BASE_DIR / "data")).expanduser().resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)

TUTOR_ACCOUNTS = os.environ.get("TUTOR_ACCOUNTS") == "1"
TUTOR_POSTGRES_DB = os.environ.get("TUTOR_POSTGRES_DB")
if TUTOR_POSTGRES_DB and not TUTOR_ACCOUNTS:
    raise RuntimeError("Для PostgreSQL включите TUTOR_ACCOUNTS=1.")

SECRET_KEY = os.environ.get("TUTOR_SECRET_KEY", "local-development-only-change-before-hosting")
if TUTOR_ACCOUNTS and (len(SECRET_KEY) < 50 or not os.environ.get("TUTOR_SECRET_KEY")):
    raise RuntimeError("Для режима личных кабинетов задайте случайный TUTOR_SECRET_KEY длиной от 50 символов.")
DEBUG = not TUTOR_ACCOUNTS
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "students",
    "school",
    "materials",
    "schedule",
    "finances",
    "assignments",
    "assistant",
]
if TUTOR_ACCOUNTS:
    INSTALLED_APPS.append("config")

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "config.cabinet_middleware.CabinetMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "static"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": DATA_DIR / ("accounts.sqlite3" if TUTOR_ACCOUNTS else "db.sqlite3")}}
if TUTOR_POSTGRES_DB:
    DATABASES["default"] = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": TUTOR_POSTGRES_DB,
        "HOST": os.environ.get("PGHOST", "127.0.0.1"),
        "PORT": os.environ.get("PGPORT", ""),
        "USER": os.environ.get("PGUSER", ""),
        "PASSWORD": os.environ.get("PGPASSWORD", ""),
        "OPTIONS": {"options": "-c search_path=public"},
    }
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "Europe/Moscow"
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_ROOT = DATA_DIR / "uploads"
DATA_UPLOAD_MAX_MEMORY_SIZE = 22 * 1024 * 1024

DATABASE_ROUTERS = ["config.cabinets.CabinetRouter"]
STORAGES = {
    "default": {"BACKEND": "config.cabinets.CabinetStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/login/"
if TUTOR_ACCOUNTS:
    SESSION_COOKIE_NAME = "tutor_postgres_session" if TUTOR_POSTGRES_DB else "tutor_cabinet_session"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
]
