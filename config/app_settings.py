import json
import os
from decimal import Decimal, ROUND_HALF_UP
from typing import Annotated
from urllib.parse import SplitResult, urlsplit, urlunsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PAYMENT_CHECK_INTERVAL: int = 60
    MIN_BIRTH_YEAR: int = 1940
    MAX_BIRTH_YEAR: int = 2020
    MAX_FILE_SIZE_MB: int = 10

    API_MAX_RETRIES: int = 3
    API_RETRY_INITIAL_DELAY: int = 1
    API_RETRY_BACKOFF_FACTOR: int = 2
    API_RETRY_MAX_DELAY: int = 10
    API_TIMEOUT: int = 10
    API_MAX_CONNECTIONS: int = 100
    API_MAX_KEEPALIVE_CONNECTIONS: int = 20

    CACHE_TTL: int = 60 * 5  # Django cache TTL
    BACKUP_RETENTION_DAYS: int = 30  # Postgres/Redis backup retention

    KNOWLEDGE_BASE_FOLDER_ID: Annotated[str, Field(default="")]
    KNOWLEDGE_REFRESH_INTERVAL: int = 60 * 60
    KNOWLEDGE_REFRESH_START_DELAY: int = 180
    AI_COACH_TIMEOUT: int = 120
    LLM_COOLDOWN: int = 60
    COACH_AGENT_RETRIES: int = 3
    COACH_AGENT_TIMEOUT: int = 60
    CHAT_HISTORY_LIMIT: int = 20

    AI_COACH_REFRESH_USER: Annotated[str, Field(default="admin")]
    AI_COACH_REFRESH_PASSWORD: Annotated[str, Field(default="password")]

    OPENAI_BASE_URL: Annotated[str, Field(default="https://api.openai.com/v1")]
    EMBEDDING_API_KEY: Annotated[str, Field(default="")]
    LLM_API_URL: Annotated[str, Field(default="https://openrouter.ai/api/v1")]
    LLM_API_KEY: Annotated[str, Field(default="")]
    LLM_MODEL: Annotated[str, Field(default="gpt-5-mini")]  # for cognee
    LLM_PROVIDER: Annotated[str, Field(default="custom")]  # for cognee
    AGENT_MODEL: Annotated[str, Field(default="openai/gpt-5-mini")]
    AGENT_PROVIDER: Annotated[str, Field(default="openrouter")]

    EMBEDDING_MODEL: Annotated[str, Field(default="openai/text-embedding-3-large")]
    EMBEDDING_PROVIDER: Annotated[str, Field(default="openai")]
    EMBEDDING_ENDPOINT: Annotated[str, Field(default="https://api.openai.com/v1")]

    BOT_TOKEN: Annotated[str, Field(default="")]
    BOT_LINK: Annotated[str, Field(default="")]
    WEBHOOK_HOST: Annotated[str, Field(default="")]
    HOST_NGINX_PORT: Annotated[str, Field(default="8000")]
    WEBAPP_PUBLIC_URL: Annotated[str | None, Field(default=None)]
    WEB_SERVER_HOST: Annotated[str, Field(default="0.0.0.0")]
    BOT_PORT: Annotated[int, Field(default=8088)]

    TIME_ZONE: Annotated[str, Field(default="Europe/Kyiv")]
    DEFAULT_LANG: Annotated[str, Field(default="ua")]
    ADMIN_LANG: Annotated[str, Field(default="ru")]
    LOG_LEVEL: Annotated[str, Field(default="INFO")]

    REDIS_URL: Annotated[str, Field(default="redis://redis:6379")]
    HOST_REDIS_PORT: Annotated[str, Field(default="6379")]
    DOCKER_BOT_START: Annotated[bool, Field(default=False)]

    BOT_INTERNAL_URL: Annotated[str, Field(default="http://bot:8000/")]

    DB_PORT: Annotated[str, Field(default="5432")]
    DB_NAME: Annotated[str, Field(default="postgres")]
    DB_USER: Annotated[str, Field(default="postgres")]
    DB_PASSWORD: Annotated[str, Field(alias="POSTGRES_PASSWORD", default="password")]
    DB_HOST: Annotated[str, Field(default="db")]
    DB_PROVIDER: Annotated[str, Field(default="postgres")]
    VECTORDATABASE_PROVIDER: Annotated[str, Field(default="pgvector")]
    GRAPH_DATABASE_PROVIDER: Annotated[str, Field(default="networkx")]
    AI_COACH_URL: Annotated[str, Field(default="http://ai_coach:9000/")]

    API_KEY: Annotated[str, Field(default="")]
    SECRET_KEY: Annotated[str, Field(default="")]
    API_HOST: Annotated[str, Field(default="http://127.0.0.1")]
    HOST_API_PORT: Annotated[str, Field(default="8000")]
    API_INTERNAL_PORT: Annotated[str, Field(default="8000")]
    API_URL: Annotated[str | None, Field(default=None)]
    ALLOWED_HOSTS: Annotated[list[str], Field(default=["localhost", "127.0.0.1"])]
    SITE_NAME: Annotated[str, Field(default="AchieveTogether")]

    GOOGLE_APPLICATION_CREDENTIALS: Annotated[str, Field(default="google_creds.json")]
    SPREADSHEET_ID: Annotated[str, Field(default="")]
    TG_SUPPORT_CONTACT: Annotated[str, Field(default="")]
    PUBLIC_OFFER: Annotated[str, Field(default="")]
    PRIVACY_POLICY: Annotated[str, Field(default="")]
    EMAIL: Annotated[str, Field(default="")]
    ADMIN_ID: Annotated[str, Field(default="")]

    DJANGO_ADMIN: Annotated[str, Field(default="admin")]
    DJANGO_PASSWORD: Annotated[str, Field(default="admin")]

    PAYMENT_PRIVATE_KEY: Annotated[str, Field(default="")]
    PAYMENT_PUB_KEY: Annotated[str, Field(default="")]
    CHECKOUT_URL: Annotated[str, Field(default="")]
    BOT_PAYMENT_OPTIONS: Annotated[str, Field(default="bot/images")]

    WEBHOOK_PATH: Annotated[str, Field(default="/telegram/webhook")]
    WEBHOOK_URL: str | None = None
    PAYMENT_CALLBACK_URL: str | None = None

    PACKAGE_START_CREDITS: int = 500
    PACKAGE_START_PRICE: Decimal = Decimal("250")
    PACKAGE_OPTIMUM_CREDITS: int = 1200
    PACKAGE_OPTIMUM_PRICE: Decimal = Decimal("500")
    PACKAGE_MAX_CREDITS: int = 6200
    PACKAGE_MAX_PRICE: Decimal = Decimal("2300")

    AI_PROGRAM_PRICE: Decimal = Decimal("350")
    REGULAR_AI_SUBSCRIPTION_PRICE: Decimal = Decimal("450")
    LARGE_AI_SUBSCRIPTION_PRICE: Decimal = Decimal("2000")
    ASK_AI_PRICE: Decimal = Decimal("10")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
        "extra": "ignore",
    }

    @model_validator(mode="after")
    def _compute_derived_fields(self) -> "Settings":
        in_docker: bool = os.path.exists("/.dockerenv") or os.getenv("KUBERNETES_SERVICE_HOST") is not None

        # WEBHOOK_URL
        if not self.WEBHOOK_URL:
            self.WEBHOOK_URL = f"{self.WEBHOOK_HOST}{self.WEBHOOK_PATH}"

        # WEBAPP_PUBLIC_URL
        if not self.WEBAPP_PUBLIC_URL:
            self.WEBAPP_PUBLIC_URL = self.WEBHOOK_HOST

        # PAYMENT_CALLBACK_URL
        if not self.PAYMENT_CALLBACK_URL:
            self.PAYMENT_CALLBACK_URL = f"{self.WEBHOOK_HOST}/payment-webhook/"

        # API_URL
        if not self.API_URL:
            self.API_URL = self._derive_api_url(in_docker)

        # --- Redis URL selection ---
        if not in_docker:
            normalized = (self.REDIS_URL or "").strip().lower()
            if not normalized or normalized.startswith("redis://redis"):
                self.REDIS_URL = "redis://127.0.0.1:6379"

        return self

    def _derive_api_url(self, in_docker: bool) -> str:
        """Build API URL taking container networking into account."""
        api_host_raw: str = str(self.API_HOST).strip()
        has_scheme: bool = "://" in api_host_raw
        prepared_host: str = api_host_raw if has_scheme else f"http://{api_host_raw}"
        parsed: SplitResult = urlsplit(prepared_host)
        scheme: str = parsed.scheme or "http"
        netloc_source: str = parsed.netloc or parsed.path
        hostname: str
        existing_port: str | None
        if ":" in netloc_source:
            hostname, existing_port = netloc_source.split(":", 1)
        else:
            hostname, existing_port = netloc_source, None
        normalized_hostname: str = hostname or "api"
        if in_docker and normalized_hostname in {"127.0.0.1", "localhost"}:
            normalized_hostname = os.getenv("API_SERVICE_HOST", "api")
        port_env_raw: str | None = os.getenv("API_PORT")
        port_env: str | None = port_env_raw.strip() if port_env_raw else None
        existing_port_clean: str | None = existing_port.strip() if existing_port else None
        port_candidates: tuple[str | None, ...] = (
            port_env,
            existing_port_clean,
        )
        resolved_port: str | None = next((candidate for candidate in port_candidates if candidate), None)
        if not resolved_port:
            resolved_port = self.API_INTERNAL_PORT if in_docker else self.HOST_API_PORT
        netloc: str = f"{normalized_hostname}:{resolved_port}" if resolved_port else normalized_hostname
        return urlunsplit((scheme, netloc, "/", "", ""))

    @property
    def CREDIT_RATE_MAX_PACK(self) -> Decimal:
        """Cost of one credit for the most profitable package."""
        return (self.PACKAGE_MAX_PRICE / Decimal(self.PACKAGE_MAX_CREDITS)).quantize(Decimal("0.0001"), ROUND_HALF_UP)

    @property
    def VECTORDATABASE_URL(self) -> str:
        return f"postgresql+psycopg2://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    @field_validator("ALLOWED_HOSTS", mode="before")
    @classmethod
    def _parse_allowed_hosts(cls, v):
        if v is None or (isinstance(v, str) and v.strip() == ""):
            return ["localhost", "127.0.0.1"]
        if isinstance(v, str):
            s = v.strip()
            try:
                j = json.loads(s)
                if isinstance(j, list):
                    return [str(x).strip() for x in j if str(x).strip()]
            except Exception:
                pass
            return [p.strip() for p in s.split(",") if p.strip()]
        return v


settings = Settings()  # noqa  # pyrefly: ignore[missing-argument]
