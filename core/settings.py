import os
from dataclasses import dataclass


@dataclass
class Settings:
    BOT_PAYMENT_OPTIONS: str = "https://storage.googleapis.com/services_promo/"
    SUCCESS_PAYMENT_STATUS: str = "success"
    FAILURE_PAYMENT_STATUS: str = "failure"
    SUBSCRIBED_PAYMENT_STATUS: str = "subscribed"
    PAYMENT_STATUS_CLOSED: str = "CLOSED"
    PAYMENT_CHECK_INTERVAL: int = 60
    SITE_NAME = "AchieveTogether"

    PAYMENT_PRIVATE_KEY: str = os.getenv("PAYMENT_PRIVATE_KEY")
    PAYMENT_PUB_KEY: str = os.getenv("PAYMENT_PUB_KEY")
    CHECKOUT_URL: str = os.getenv("CHECKOUT_URL")
    PAYMENT_CALLBACK_URL: str = os.getenv("PAYMENT_CALLBACK_URL")
    API_KEY: str = os.getenv("API_KEY")
    API_URL: str = os.getenv("API_URL")
    SECRET_KEY: str = os.getenv("SECRET_KEY")
    CRYPTO_KEY: str = os.getenv("CRYPTO_KEY")
    OWNER_ID: str = os.getenv("OWNER_ID")
    EMAIL_HOST_USER: str = os.getenv("EMAIL_HOST_USER")
    DEFAULT_FROM_EMAIL: str = os.getenv("DEFAULT_FROM_EMAIL")
    EMAIL_HOST_PASSWORD: str = os.getenv("EMAIL_HOST_PASSWORD")
    BOT_TOKEN: str = os.getenv("BOT_TOKEN")
    DEBUG_LEVEL: str = os.getenv("DEBUG_LEVEL", "INFO")
    BOT_LINK = os.getenv("BOT_LINK")
    REDIS_URL: str = os.getenv("REDIS_URL")
    DB_PORT: str = os.getenv("DB_PORT")
    DB_NAME: str = os.getenv("DB_NAME")
    DB_USER: str = os.getenv("DB_USER")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD")
    DB_HOST: str = os.getenv("DB_HOST")
    PUBLIC_OFFER: str = os.getenv("PUBLIC_OFFER")
    PRIVACY_POLICY: str = os.getenv("PRIVACY_POLICY")
    TG_SUPPORT_CONTACT: str = os.getenv("TG_SUPPORT_CONTACT")
    GOOGLE_APPLICATION_CREDENTIALS: str = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    SPREADSHEET_ID: str = os.getenv("SPREADSHEET_ID")


settings = Settings()
