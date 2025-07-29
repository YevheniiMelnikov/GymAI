import os

os.environ["TIME_ZONE"] = "Europe/Kyiv"
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.test_settings")

import django


env_defaults = {
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
    "AI_COACH_URL": "http://localhost/",
}
for key, value in env_defaults.items():
    os.environ.setdefault(key, value)


django.setup()
