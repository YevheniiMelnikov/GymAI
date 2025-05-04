import os
from pathlib import Path

from env_settings import Settings
from logger import *

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = Settings.API_KEY
DEBUG = os.environ.get("DEBUG_STATUS", "False").lower() == "true"

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "achieve-together.org.ua", "www.achieve-together.org.ua", "api"]

ASGI_APPLICATION = "config.asgi.application"

INSTALLED_APPS = [
    "jazzmin",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "profiles.apps.ProfilesConfig",
    "payments.apps.PaymentsConfig",
    "home.apps.HomeConfig",
    "rest_framework",
    "rest_framework.authtoken",
    "rest_framework_api_key",
    "drf_yasg",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "api.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "api/templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql_psycopg2",
        "NAME": Settings.DB_NAME,
        "USER": Settings.DB_USER,
        "PASSWORD": Settings.DB_PASSWORD,
        "HOST": Settings.DB_HOST,
        "PORT": Settings.DB_PORT,
        "TEST": {
            "NAME": "test_db",
        },
    }
}

LANGUAGE_CODE = "EN"
TIME_ZONE = "Europe/Kyiv"
USE_I18N = True
USE_TZ = False

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.LimitOffsetPagination",
    "PAGE_SIZE": 10,
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_api_key.authentication.APIKeyAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework_api_key.permissions.HasAPIKey",
    ],
}

DOMAIN = Settings.DOMAIN
SITE_NAME = Settings.SITE_NAME
CORS_ALLOWED_ORIGINS = ["*"]
