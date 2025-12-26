import os
from pathlib import Path

from config.app_settings import settings
from config.logger import *
from urllib.parse import urlparse

# Following module relates strictly to Django

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = settings.SECRET_KEY
DEBUG = os.environ.get("DEBUG_STATUS", "False").lower() == "true"


def _parse_url(u: str | None):
    if not u:
        return None
    if "://" not in u:
        u = f"https://{u}"
    return urlparse(u)


_raw_urls = [
    getattr(settings, "API_URL", ""),
    getattr(settings, "WEBHOOK_HOST", ""),
    getattr(settings, "WEBAPP_PUBLIC_URL", ""),
]
_parsed_urls = [p for p in map(_parse_url, _raw_urls) if p and p.hostname]

CSRF_TRUSTED_ORIGINS = [f"{p.scheme}://{p.netloc}" for p in _parsed_urls if p.scheme]
USE_X_FORWARDED_HOST = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
ASGI_APPLICATION = "config.asgi.application"
if DEBUG:
    STATICFILES_STORAGE = "django.contrib.staticfiles.storage.StaticFilesStorage"
else:
    STATICFILES_STORAGE = "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"

SECURE_SSL_REDIRECT = settings.SECURE_SSL_REDIRECT if not DEBUG else False
SESSION_COOKIE_SECURE = settings.SESSION_COOKIE_SECURE if not DEBUG else False
CSRF_COOKIE_SECURE = settings.CSRF_COOKIE_SECURE if not DEBUG else False
SECURE_HSTS_SECONDS = settings.SECURE_HSTS_SECONDS if not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = settings.SECURE_HSTS_INCLUDE_SUBDOMAINS if not DEBUG else False
SECURE_HSTS_PRELOAD = settings.SECURE_HSTS_PRELOAD if not DEBUG else False
SECURE_CONTENT_TYPE_NOSNIFF = settings.SECURE_CONTENT_TYPE_NOSNIFF
SECURE_REFERRER_POLICY = settings.SECURE_REFERRER_POLICY
SESSION_COOKIE_SAMESITE = settings.SESSION_COOKIE_SAMESITE
CSRF_COOKIE_SAMESITE = settings.CSRF_COOKIE_SAMESITE

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "unfold",
    "apps.profiles.apps.ProfilesConfig",
    "apps.payments.apps.PaymentsConfig",
    "apps.metrics.apps.MetricsConfig",
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

LANGUAGE_CODE = "en-us"
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
ALLOWED_HOSTS = settings.ALLOWED_HOSTS
CORS_ALLOW_ALL_ORIGINS = settings.CORS_ALLOW_ALL_ORIGINS

REDIS_URL = settings.REDIS_URL

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "SERIALIZER": "django_redis.serializers.json.JSONSerializer",
            "COMPRESSOR": "django_redis.compressors.zlib.ZlibCompressor",
        },
        "TIMEOUT": 60 * 60,
    }
}
