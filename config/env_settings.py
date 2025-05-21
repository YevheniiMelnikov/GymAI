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
    COACH_PAYOUT_RATE: float = 0.7
    SITE_NAME: str = "AchieveTogether"
    API_MAX_RETRIES: int = 3
    API_RETRY_INITIAL_DELAY: int = 1
    API_RETRY_BACKOFF_FACTOR: int = 2
    API_RETRY_MAX_DELAY: int = 10
    API_TIMEOUT: int = 10

    TIME_ZONE: str = must_getenv("TIME_ZONE", "Europe/Kyiv")
    BOT_LANG: str = must_getenv("BOT_LANG", "ua")
    ADMIN_LANG: str = must_getenv("ADMIN_LANG", "ru")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    API_KEY: str = must_getenv("API_KEY")
    API_URL: str = must_getenv("API_URL")
    REDIS_URL: str = must_getenv("REDIS_URL", "redis://redis:6379")

    BOT_TOKEN: str = must_getenv("BOT_TOKEN")
    BOT_LINK: str = must_getenv("BOT_LINK")
    BOT_INTERNAL_URL: str = must_getenv("BOT_INTERNAL_URL", "http://localhost:8000/")
    WEB_SERVER_HOST: str = "0.0.0.0"
    WEBHOOK_HOST: str = must_getenv("WEBHOOK_HOST")
    WEBHOOK_PORT: int = int(must_getenv("WEBHOOK_PORT"))
    WEBHOOK_PATH: str = f"/gym_bot/{BOT_TOKEN}"
    WEBHOOK_URL: str = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

    GOOGLE_APPLICATION_CREDENTIALS: str = must_getenv("GOOGLE_APPLICATION_CREDENTIALS")
    SPREADSHEET_ID: str = must_getenv("SPREADSHEET_ID")
    TG_SUPPORT_CONTACT: str = must_getenv("TG_SUPPORT_CONTACT")
    PUBLIC_OFFER: str = must_getenv("PUBLIC_OFFER")
    PRIVACY_POLICY: str = must_getenv("PRIVACY_POLICY")
    EMAIL: str = must_getenv("EMAIL")
    ADMIN_ID: str = must_getenv("ADMIN_ID")

    PAYMENT_PRIVATE_KEY: str = must_getenv("PAYMENT_PRIVATE_KEY")
    PAYMENT_PUB_KEY: str = must_getenv("PAYMENT_PUB_KEY")
    CHECKOUT_URL: str = must_getenv("CHECKOUT_URL")
    PAYMENT_CALLBACK_URL: str = f"{WEBHOOK_HOST}/payment-webhook/"

    DB_PORT: str = must_getenv("DB_PORT", "5432")
    DB_NAME: str = must_getenv("DB_NAME", "postgres")
    DB_USER: str = must_getenv("DB_USER", "postgres")
    DB_PASSWORD: str = must_getenv("POSTGRES_PASSWORD", "password")
    DB_HOST: str = must_getenv("DB_HOST", "db")
