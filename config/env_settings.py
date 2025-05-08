import os
from dataclasses import dataclass
from typing import Optional


def must_getenv(key: str, default: Optional[str] = None) -> str:
    value = os.getenv(key, default)
    if value is None:
        raise ValueError(f"Missing required environment variable: {key}")
    return value


@dataclass
class Settings:
    BOT_PAYMENT_OPTIONS: str = "https://storage.googleapis.com/services_promo/"
    SUCCESS_PAYMENT_STATUS: str = "success"
    FAILURE_PAYMENT_STATUS: str = "failure"
    SUBSCRIBED_PAYMENT_STATUS: str = "subscribed"
    PAYMENT_STATUS_CLOSED: str = "CLOSED"
    PAYMENT_CHECK_INTERVAL: int = 60
    SITE_NAME: str = "AchieveTogether"
    TIME_ZONE: str = must_getenv("TIME_ZONE", "Europe/Kyiv")
    BOT_LANG: str = must_getenv("BOT_LANG")
    OWNER_LANG: str = must_getenv("OWNER_LANG")

    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    DOMAIN: str = must_getenv("DOMAIN")
    API_KEY: str = must_getenv("API_KEY")
    API_URL: str = must_getenv("API_URL")
    REDIS_URL: str = must_getenv("REDIS_URL")

    BOT_TOKEN: str = must_getenv("BOT_TOKEN")
    BOT_LINK: str = os.getenv("BOT_LINK")
    WEB_SERVER_HOST: str = "0.0.0.0"
    WEBHOOK_HOST: str = must_getenv("WEBHOOK_HOST")
    WEBHOOK_PORT: int = must_getenv("WEBHOOK_PORT")
    WEBHOOK_PATH: str = f"/gym_bot/{BOT_TOKEN}"
    WEBHOOK_URL: str = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

    GOOGLE_APPLICATION_CREDENTIALS: str = must_getenv("GOOGLE_APPLICATION_CREDENTIALS")
    SPREADSHEET_ID: str = must_getenv("SPREADSHEET_ID")
    TG_SUPPORT_CONTACT: str = os.getenv("TG_SUPPORT_CONTACT")
    PUBLIC_OFFER: str = os.getenv("PUBLIC_OFFER")
    PRIVACY_POLICY: str = os.getenv("PRIVACY_POLICY")
    EMAIL: str = must_getenv("EMAIL")
    OWNER_ID: str = must_getenv("OWNER_ID")

    PAYMENT_PRIVATE_KEY: str = must_getenv("PAYMENT_PRIVATE_KEY")
    PAYMENT_PUB_KEY: str = must_getenv("PAYMENT_PUB_KEY")
    CHECKOUT_URL: str = must_getenv("CHECKOUT_URL")
    PAYMENT_CALLBACK_URL: str = f"{WEBHOOK_HOST}/payment-webhook/"

    DB_PORT: str = must_getenv("DB_PORT")
    DB_NAME: str = must_getenv("DB_NAME")
    DB_USER: str = must_getenv("DB_USER")
    DB_PASSWORD: str = must_getenv("POSTGRES_PASSWORD")
    DB_HOST: str = must_getenv("DB_HOST")
