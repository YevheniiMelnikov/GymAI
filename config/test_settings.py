import os

env_defaults = {
    "API_KEY": "test_api_key",
    "API_URL": "http://localhost/",
    "BOT_TOKEN": "bot_token",
    "BOT_LINK": "http://bot",
    "WEBHOOK_HOST": "http://localhost",
    "GOOGLE_APPLICATION_CREDENTIALS": "/tmp/creds.json",
    "SPREADSHEET_ID": "sheet",
    "TG_SUPPORT_CONTACT": "@support",
    "PUBLIC_OFFER": "http://offer",
    "PRIVACY_POLICY": "http://privacy",
    "OWNER_EMAIL": "test@example.com",
    "OWNER_NAME": "Test Owner",
    "OWNER_ADDRESS": "Test Address",
    "PAYMENT_PRIVATE_KEY": "priv",
    "PAYMENT_PUB_KEY": "pub",
    "CHECKOUT_URL": "http://checkout",
    "POSTGRES_PASSWORD": "password",
    "DB_NAME": "postgres",
    "DB_USER": "postgres",
    "DB_HOST": "localhost",
    "DB_PORT": "5432",
    "AI_COACH_URL": "http://localhost/",
    "KNOWLEDGE_REFRESH_INTERVAL": "3600",
    "AI_COACH_REFRESH_USER": "admin",
    "AI_COACH_REFRESH_PASSWORD": "password",
    "AI_COACH_TIMEOUT": "60",
    "BACKUP_RETENTION_DAYS": "30",
    "WEBAPP_INIT_DATA_MAX_AGE_SEC": "0",
}

for key, value in env_defaults.items():
    os.environ[key] = value

os.environ["TIME_ZONE"] = "Europe/Kyiv"

from .settings import *  # noqa

TIME_ZONE = "Europe/Kyiv"
SECRET_KEY = "dummy-key-for-testing"
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_HSTS_SECONDS = 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql_psycopg2",
        "NAME": os.getenv("DB_NAME", "postgres"),
        "USER": os.getenv("DB_USER", "postgres"),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD", "password"),
        "HOST": os.getenv("DB_HOST", "localhost"),
        "PORT": os.getenv("DB_PORT", "5432"),
        "TEST": {"NAME": "test_db"},
    }
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "",
    }
}
