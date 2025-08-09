import os
from pathlib import Path

from config.app_settings import settings
from config.logger import *
from urllib.parse import urlparse

# Following module relates strictly to Django

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = settings.SECRET_KEY
DEBUG = os.environ.get("DEBUG_STATUS", "False").lower() == "true"
_api_raw = getattr(settings, "API_URL", "")
_webhook_raw = getattr(settings, "WEBHOOK_HOST", "")
_parsed_api = urlparse(_api_raw) if _api_raw else None
_parsed_webhook = urlparse(_webhook_raw) if _webhook_raw else None
_hosts = {
    "localhost",
    "127.0.0.1",
    "achieve-together.org.ua",
    "www.achieve-together.org.ua",
    "api",
}
if _parsed_api and _parsed_api.hostname:
    _hosts.add(_parsed_api.hostname)
if _parsed_webhook and _parsed_webhook.hostname:
    _hosts.add(_parsed_webhook.hostname)
ALLOWED_HOSTS = list(_hosts)
CSRF_TRUSTED_ORIGINS = [
    f"{p.scheme}://{p.hostname}"
    for p in (_parsed_api, _parsed_webhook)
    if p and p.scheme and p.hostname
]
USE_X_FORWARDED_HOST = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
ASGI_APPLICATION = "config.asgi.application"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "unfold",
    "apps.profiles.apps.ProfilesConfig",
    "apps.payments.apps.PaymentsConfig",
    "apps.home.apps.HomeConfig",
    "apps.webapp.apps.WebappConfig",
    "apps.workout_plans.apps.WorkoutPlansConfig",
    "rest_framework",
    "rest_framework_api_key",
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

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [os.path.join(BASE_DIR, "templates")],
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
        "NAME": settings.DB_NAME,
        "USER": settings.DB_USER,
        "PASSWORD": settings.DB_PASSWORD,
        "HOST": settings.DB_HOST,
        "PORT": settings.DB_PORT,
        "TEST": {
            "NAME": "test_db",
        },
    }
}

LANGUAGE_CODE = "EN"
TIME_ZONE = settings.TIME_ZONE
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
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework_api_key.permissions.HasAPIKey",
    ],
}

DOMAIN = settings.API_URL
SITE_NAME = settings.SITE_NAME
CORS_ALLOWED_ORIGINS = ["*"]  # move to settings

REDIS_URL = settings.REDIS_URL

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "SERIALIZER": "django_redis.serializers.pickle.PickleSerializer",
            "COMPRESSOR": "django_redis.compressors.zlib.ZlibCompressor",
        },
        "TIMEOUT": 60 * 60,
    }
}
