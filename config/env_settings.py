from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Annotated

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    BOT_PAYMENT_OPTIONS: str = str((Path(__file__).resolve().parents[1] / "bot" / "images"))
    PAYMENT_CHECK_INTERVAL: int = 60
    COACH_PAYOUT_RATE: Decimal = Decimal("0.7")
    PACKAGE_START_CREDITS: int = 500
    PACKAGE_START_PRICE: Decimal = Decimal("250")
    PACKAGE_OPTIMUM_CREDITS: int = 1200
    PACKAGE_OPTIMUM_PRICE: Decimal = Decimal("500")
    PACKAGE_MAX_CREDITS: int = 6200
    PACKAGE_MAX_PRICE: Decimal = Decimal("2300")
    SUBSCRIPTION_PERIOD_DAYS: int = 30
    MIN_BIRTH_YEAR: int = 1940
    MAX_BIRTH_YEAR: int = 2020

    SITE_NAME: str = "AchieveTogether"

    API_MAX_RETRIES: int = 3
    API_RETRY_INITIAL_DELAY: int = 1
    API_RETRY_BACKOFF_FACTOR: int = 2
    API_RETRY_MAX_DELAY: int = 10
    API_TIMEOUT: int = 10

    CACHE_TTL: int = 60 * 5

    TIME_ZONE: Annotated[str, Field(default="Europe/Kyiv")]
    DEFAULT_LANG: Annotated[str, Field(default="ua")]
    ADMIN_LANG: Annotated[str, Field(default="ru")]
    LOG_LEVEL: Annotated[str, Field(default="INFO")]
    REDIS_URL: Annotated[str, Field(default="redis://redis:6379")]

    BOT_INTERNAL_URL: Annotated[str, Field(default="http://localhost:8000/")]
    WEB_SERVER_HOST: Annotated[str, Field(default="0.0.0.0")]

    DB_PORT: Annotated[str, Field(default="5432")]
    DB_NAME: Annotated[str, Field(default="postgres")]
    DB_USER: Annotated[str, Field(default="postgres")]
    DB_PASSWORD: Annotated[str, Field(alias="POSTGRES_PASSWORD")]
    DB_HOST: Annotated[str, Field(default="db")]

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

    DJANGO_ADMIN: Annotated[str, Field(default="admin")]
    DJANGO_PASSWORD: Annotated[str, Field(default="admin")]

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
        "extra": "ignore",
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

    @property
    def CREDIT_RATE_MAX_PACK(self) -> Decimal:
        """Cost of one credit for the most profitable package."""
        return (self.PACKAGE_MAX_PRICE / Decimal(self.PACKAGE_MAX_CREDITS)).quantize(
            Decimal("0.0001"), ROUND_HALF_UP
        )


settings = Settings()  # noqa
