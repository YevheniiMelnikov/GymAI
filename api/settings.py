import os
from pathlib import Path

from common.settings import settings

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = settings.SECRET_KEY

DEBUG = os.environ.get("DEBUG_STATUS", "False").lower() == "true"

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "achieve-together.org.ua", "www.achieve-together.org.ua", "api"]

ASGI_APPLICATION = "api.asgi.application"

INSTALLED_APPS = [
    "jazzmin",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts.apps.AccountsConfig",
    "payments.apps.PaymentsConfig",
    "home.apps.HomeConfig",
    "rest_framework",
    "rest_framework.authtoken",
    "rest_framework_api_key",
    "djoser",
    "drf_yasg",
]

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "loguru": {
            "level": "DEBUG",
            "class": "common.logger.InterceptHandler",
        },
    },
    "root": {
        "handlers": ["loguru"],
        "level": "DEBUG",
    },
    "loggers": {
        "django": {
            "handlers": ["loguru"],
            "level": "INFO",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["loguru"],
            "level": "ERROR",
            "propagate": False,
        },
    },
}

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

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {
            "min_length": 8,
        },
    },
    {
        "NAME": "accounts.validators.CustomPasswordValidator",
    },
]

LANGUAGE_CODE = "ru"

TIME_ZONE = "Europe/Kyiv"

USE_I18N = True

USE_TZ = False

STATIC_URL = "/static/"
STATICFILES_DIRS = [
    BASE_DIR / "api/static",
]
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.LimitOffsetPagination",
    "PAGE_SIZE": 10,
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework.authentication.BasicAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticatedOrReadOnly"],
}

DOMAIN = settings.DOMAIN
SITE_NAME = settings.SITE_NAME
CORS_ALLOWED_ORIGINS = ["*"]

DJOSER = {
    "PASSWORD_RESET_CONFIRM_URL": "/password-reset/{uid}/{token}",
    "PASSWORD_RESET_CONFIRM_RETYPE": True,
    "PASSWORD_RESET_SHOW_EMAIL_NOT_FOUND": True,
    "SEND_ACTIVATION_EMAIL": True,
    "EMAIL": {"password_reset": "accounts.emails.CustomPasswordResetEmail"},
    "USER_AUTHENTICATION_FIELD": "username",
    "USER_CREATE_PASSWORD_RETYPE": True,
    "SERIALIZERS": {
        "user_create": "djoser.serializers.UserCreateSerializer",
        "user": "accounts.serializers.UserSerializer",
    },
}

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = "smtp.gmail.com"
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = settings.EMAIL_HOST_USER
EMAIL_HOST_PASSWORD = settings.EMAIL_HOST_PASSWORD
DEFAULT_FROM_EMAIL = settings.DEFAULT_FROM_EMAIL
SERVER_EMAIL = EMAIL_HOST_USER
EMAIL_ADMIN = EMAIL_HOST_USER
