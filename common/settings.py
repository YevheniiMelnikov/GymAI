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
    SITE_NAME: str = "AchieveTogether"
    DEFAULT_BOT_LANGUAGE: str = "ua"
    OWNER_LANGUAGE = "ru"
    DEBUG_LEVEL: str = os.getenv("DEBUG_LEVEL", "INFO")

    GOOGLE_APPLICATION_CREDENTIALS: str = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    SPREADSHEET_ID: str = os.getenv("SPREADSHEET_ID")

    DOMAIN: str = os.getenv("DOMAIN")
    API_KEY: str = os.getenv("API_KEY")
    API_URL: str = os.getenv("API_URL")
    SECRET_KEY: str = os.getenv("SECRET_KEY")

    BOT_TOKEN: str = os.getenv("BOT_TOKEN")
    BOT_LINK = os.getenv("BOT_LINK")
    OWNER_ID: str = os.getenv("OWNER_ID")
    TG_SUPPORT_CONTACT: str = os.getenv("TG_SUPPORT_CONTACT")
    PUBLIC_OFFER: str = os.getenv("PUBLIC_OFFER")
    PRIVACY_POLICY: str = os.getenv("PRIVACY_POLICY")
    DEFAULT_FROM_EMAIL: str = os.getenv("DEFAULT_FROM_EMAIL")

    WEB_SERVER_HOST: str = "0.0.0.0"
    WEBHOOK_HOST: str = os.getenv("WEBHOOK_HOST")
    WEBHOOK_PORT: int = os.getenv("WEBHOOK_PORT")
    WEBHOOK_PATH: str = f"/gym_bot/{BOT_TOKEN}"  # REMOVE BOT_TOKEN
    WEBHOOK_URL: str = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

    PAYMENT_PRIVATE_KEY: str = os.getenv("PAYMENT_PRIVATE_KEY")
    PAYMENT_PUB_KEY: str = os.getenv("PAYMENT_PUB_KEY")
    CHECKOUT_URL: str = os.getenv("CHECKOUT_URL")
    PAYMENT_CALLBACK_URL: str = f"{WEBHOOK_HOST}/payment-webhook/"

    REDIS_URL: str = os.getenv("REDIS_URL")
    DB_PORT: str = os.getenv("DB_PORT")
    DB_NAME: str = os.getenv("DB_NAME")
    DB_USER: str = os.getenv("DB_USER")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD")
    DB_HOST: str = os.getenv("DB_HOST")
