from __future__ import annotations

from decimal import Decimal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    BOT_PAYMENT_OPTIONS: str = "https://storage.googleapis.com/services_promo/"
    PAYMENT_CHECK_INTERVAL: int = 60
    COACH_PAYOUT_RATE: Decimal = Decimal("0.7")

    SITE_NAME: str = "AchieveTogether"

    API_MAX_RETRIES: int = 3
    API_RETRY_INITIAL_DELAY: int = 1
    API_RETRY_BACKOFF_FACTOR: int = 2
    API_RETRY_MAX_DELAY: int = 10
    API_TIMEOUT: int = 10

    CACHE_TTL: int = 60 * 5

    TIME_ZONE: str = Field("Europe/Kyiv", env="TIME_ZONE")
    DEFAULT_LANG: str = Field("ua", env="DEFAULT_LANG")
    ADMIN_LANG: str = Field("ru", env="ADMIN_LANG")
    LOG_LEVEL: str = Field("INFO", env="LOG_LEVEL")
    REDIS_URL: str = Field("redis://redis:6379", env="REDIS_URL")

    BOT_INTERNAL_URL: str = Field("http://localhost:8000/", env="BOT_INTERNAL_URL")
    WEB_SERVER_HOST: str = Field("0.0.0.0", env="WEB_SERVER_HOST")

    DB_PORT: str = Field("5432", env="DB_PORT")
    DB_NAME: str = Field("postgres", env="DB_NAME")
    DB_USER: str = Field("postgres", env="DB_USER")
    DB_PASSWORD: str = Field("password", env="POSTGRES_PASSWORD")
    DB_HOST: str = Field("db", env="DB_HOST")

    API_KEY: str
    API_URL: str

    BOT_TOKEN: str
    BOT_LINK: str

    WEBHOOK_HOST: str
    WEBHOOK_PORT: int

    GOOGLE_APPLICATION_CREDENTIALS: str
    SPREADSHEET_ID: str
    TG_SUPPORT_CONTACT: str
    PUBLIC_OFFER: str
    PRIVACY_POLICY: str
    EMAIL: str
    ADMIN_ID: str

    PAYMENT_PRIVATE_KEY: str
    PAYMENT_PUB_KEY: str
    CHECKOUT_URL: str

    WEBHOOK_PATH: str | None = None
    WEBHOOK_URL: str | None = None
    PAYMENT_CALLBACK_URL: str | None = None

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
    }

    @model_validator(mode="after")
    def _compute_derived_fields(self) -> "Settings":
        # WEBHOOK_PATH
        if not self.WEBHOOK_PATH:
            self.WEBHOOK_PATH = f"/gym_bot/{self.BOT_TOKEN}"

        # WEBHOOK_URL
        if not self.WEBHOOK_URL:
            self.WEBHOOK_URL = f"{self.WEBHOOK_HOST}{self.WEBHOOK_PATH}"

        # PAYMENT_CALLBACK_URL
        if not self.PAYMENT_CALLBACK_URL:
            self.PAYMENT_CALLBACK_URL = f"{self.WEBHOOK_HOST}/payment-webhook/"

        return self


settings = Settings()  # noqa
