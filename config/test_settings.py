import os

env_defaults = {
    "SECRET_KEY": "test_secret_key",
    "API_KEY": "test_api_key",
    "API_URL": "http://localhost/",
    "BOT_TOKEN": "bot_token",
    "BOT_LINK": "http://bot",
    "WEBHOOK_HOST": "http://localhost",
    "WEBHOOK_PORT": "8000",
    "GOOGLE_APPLICATION_CREDENTIALS": "/tmp/creds.json",
    "SPREADSHEET_ID": "sheet",
    "TG_SUPPORT_CONTACT": "@support",
    "PUBLIC_OFFER": "http://offer",
    "PRIVACY_POLICY": "http://privacy",
    "EMAIL": "test@example.com",
    "ADMIN_ID": "1",
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
}

for key, value in env_defaults.items():
    os.environ[key] = value

os.environ["TIME_ZONE"] = "Europe/Kyiv"

TIME_ZONE = "Europe/Kyiv"

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "rest_framework",
]

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}

MIDDLEWARE = []

REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "",
    }
}
