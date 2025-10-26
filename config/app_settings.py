import json
import os
from decimal import Decimal, ROUND_HALF_UP
from typing import Annotated, Any
from urllib.parse import SplitResult, quote, quote_plus, urlsplit, urlunsplit
from uuid import NAMESPACE_DNS, uuid5

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings


def normalize_service_host(
    url: str,
    new_host: str,
    *,
    default_scheme: str = "http",
    force: bool = False,
) -> str:
    """Replace localhost-like hosts with the provided service host."""

    raw = url.strip()
    if not raw:
        return url

    try:
        has_scheme = "://" in raw
        candidate = raw if has_scheme else f"{default_scheme}://{raw}"
        parsed = urlsplit(candidate)
    except Exception:
        return url

    host = parsed.hostname or ""
    if not force and host not in {"localhost", "127.0.0.1", ""}:
        return url

    scheme = parsed.scheme or default_scheme
    userinfo = ""
    if parsed.username:
        userinfo = parsed.username
        if parsed.password:
            userinfo = f"{userinfo}:{parsed.password}"
        userinfo = f"{userinfo}@"

    port = f":{parsed.port}" if parsed.port else ""
    path = parsed.path or "/"
    normalized = urlunsplit((scheme, f"{userinfo}{new_host}{port}", path, parsed.query, parsed.fragment))
    return normalized


class Settings(BaseSettings):
    DEBUG: bool = False
    PAYMENT_CHECK_INTERVAL: int = 60
    MIN_BIRTH_YEAR: int = 1940
    MAX_BIRTH_YEAR: int = 2020
    MAX_FILE_SIZE_MB: int = 10

    API_MAX_RETRIES: int = 1
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
    AI_COACH_TIMEOUT: int = 420
    LLM_COOLDOWN: int = 60
    COACH_AGENT_RETRIES: int = 1
    COACH_AGENT_TIMEOUT: int = 60
    CHAT_HISTORY_LIMIT: int = 20
    AI_COACH_MAX_TOOL_CALLS: Annotated[int, Field(default=5)]
    AI_COACH_REQUEST_TIMEOUT: Annotated[int, Field(default=60)]
    AI_COACH_GLOBAL_PROJECTION_TIMEOUT: Annotated[float, Field(default=15.0)]
    AI_COACH_DEFAULT_TOOL_TIMEOUT: Annotated[float, Field(default=3.0)]
    AI_COACH_SEARCH_TIMEOUT: Annotated[float, Field(default=8.0)]
    AI_COACH_HISTORY_TIMEOUT: Annotated[float, Field(default=6.0)]
    AI_COACH_PROGRAM_HISTORY_TIMEOUT: Annotated[float, Field(default=6.0)]
    AI_COACH_SAVE_TIMEOUT: Annotated[float, Field(default=30.0)]
    AI_COACH_ATTACH_GIFS_MIN_BUDGET: Annotated[float, Field(default=10.0)]
    AI_COACH_SECONDARY_MODEL: Annotated[str | None, Field(default=None)]
    AI_COACH_FIRST_PASS_MAX_TOKENS: Annotated[int, Field(default=900)]
    AI_COACH_RETRY_MAX_TOKENS: Annotated[int, Field(default=600)]
    AI_COACH_EMPTY_COMPLETION_RETRY: Annotated[bool, Field(default=True)]
    AI_COACH_PRIMARY_CONTEXT_LIMIT: Annotated[int, Field(default=2200)]
    AI_COACH_RETRY_CONTEXT_LIMIT: Annotated[int, Field(default=1400)]
    DISABLE_MANUAL_PLACEHOLDER: Annotated[bool, Field(default=True)]
    AI_PLAN_DEDUP_TTL: Annotated[int, Field(default=3600)]
    AI_PLAN_NOTIFY_TIMEOUT: Annotated[int, Field(default=900)]
    AI_PLAN_NOTIFY_POLL_INTERVAL: Annotated[int, Field(default=30)]
    AI_PLAN_NOTIFY_FAILURE_TTL: Annotated[int, Field(default=86400)]

    COGNEE_STORAGE_PATH: Annotated[str, Field(default=".data_storage")]
    COGNEE_GLOBAL_DATASET: Annotated[str, Field(default="kb_global")]

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
    LOG_VERBOSE_CELERY: Annotated[bool, Field(default=False)]

    REDIS_URL: Annotated[str, Field(default="redis://redis:6379")]
    RABBITMQ_URL: Annotated[str | None, Field(default=None)]
    RABBITMQ_HOST: Annotated[str, Field(default="rabbitmq")]
    RABBITMQ_PORT: Annotated[str, Field(default="5672")]
    RABBITMQ_USER: Annotated[str, Field(default="rabbitmq")]
    RABBITMQ_PASSWORD: Annotated[str, Field(default="rabbitmq")]
    RABBITMQ_VHOST: Annotated[str, Field(default="/")]
    HOST_REDIS_PORT: Annotated[str, Field(default="6379")]
    DOCKER_BOT_START: Annotated[bool, Field(default=False)]

    BOT_INTERNAL_URL: Annotated[str, Field(default="http://bot:8000/")]
    INTERNAL_HTTP_CONNECT_TIMEOUT: Annotated[float, Field(default=10.0)]
    INTERNAL_HTTP_READ_TIMEOUT: Annotated[float, Field(default=30.0)]

    DB_PORT: Annotated[str, Field(default="5432")]
    DB_NAME: Annotated[str, Field(default="postgres")]
    DB_USER: Annotated[str, Field(default="postgres")]
    DB_PASSWORD: Annotated[str, Field(alias="POSTGRES_PASSWORD", default="password")]
    DB_HOST: Annotated[str, Field(default="db")]
    DB_PROVIDER: Annotated[str, Field(default="postgres")]
    VECTORDATABASE_PROVIDER: Annotated[str, Field(default="pgvector")]
    GRAPH_DATABASE_PROVIDER: Annotated[str, Field(default="networkx")]
    AI_COACH_URL: Annotated[str, Field(default="http://ai_coach:9000/")]
    COGNEE_CLIENT_DATASET_NAMESPACE: Annotated[str | None, Field(default=None)]

    API_KEY: Annotated[str, Field(default="")]
    INTERNAL_API_KEY: Annotated[str | None, Field(default=None)]
    INTERNAL_IP_ALLOWLIST: Annotated[list[str], Field(default_factory=list)]
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
    ASK_AI_PRICE: Annotated[int, Field(default=10)]
    AI_QA_IMAGE_MAX_BYTES: Annotated[int, Field(default=512_000)]
    AI_QA_DEDUP_TTL: Annotated[int, Field(default=1800)]
    AI_QA_MAX_RETRIES: Annotated[int, Field(default=5)]
    AI_QA_RETRY_BACKOFF_S: Annotated[int, Field(default=30)]

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
        "extra": "ignore",
    }

    @field_validator("INTERNAL_IP_ALLOWLIST", mode="before")
    @classmethod
    def _normalize_ip_allowlist(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            candidates = value.split(",")
        elif isinstance(value, (list, tuple, set)):
            candidates = list(value)
        else:
            return []
        result: list[str] = []
        for candidate in candidates:
            text = str(candidate).strip()
            if text:
                result.append(text)
        return result

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

        # Cognee dataset namespace
        if not self.COGNEE_CLIENT_DATASET_NAMESPACE:
            namespace_seed: str = self.SECRET_KEY or self.SITE_NAME or "gymbot"
            base_namespace = uuid5(NAMESPACE_DNS, "gymbot.cognee")
            self.COGNEE_CLIENT_DATASET_NAMESPACE = str(uuid5(base_namespace, namespace_seed))

        # --- Redis URL selection ---
        if not in_docker:
            normalized = (self.REDIS_URL or "").strip().lower()
            if not normalized or normalized.startswith("redis://redis"):
                self.REDIS_URL = "redis://127.0.0.1:6379"

        if not self.RABBITMQ_URL:
            encoded_user: str = quote_plus(self.RABBITMQ_USER)
            encoded_password: str = quote_plus(self.RABBITMQ_PASSWORD)
            encoded_vhost: str = quote(self.RABBITMQ_VHOST, safe="")
            self.RABBITMQ_URL = (
                f"amqp://{encoded_user}:{encoded_password}@{self.RABBITMQ_HOST}:{self.RABBITMQ_PORT}/{encoded_vhost}"
            )

        if in_docker:
            rabbitmq_host_override: str = os.getenv("RABBITMQ_SERVICE_HOST", self.RABBITMQ_HOST or "rabbitmq")
            if self.RABBITMQ_URL:
                self.RABBITMQ_URL = normalize_service_host(
                    self.RABBITMQ_URL,
                    rabbitmq_host_override,
                    default_scheme="amqp",
                )
            if self.AI_COACH_URL:
                ai_coach_host: str = os.getenv("AI_COACH_SERVICE_HOST", "ai_coach")
                self.AI_COACH_URL = normalize_service_host(self.AI_COACH_URL, ai_coach_host)
            if self.BOT_INTERNAL_URL:
                bot_service_host: str = os.getenv("BOT_SERVICE_HOST", "host.docker.internal")
                force_override: bool = not self.DOCKER_BOT_START
                self.BOT_INTERNAL_URL = normalize_service_host(
                    self.BOT_INTERNAL_URL,
                    bot_service_host,
                    force=force_override,
                )

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
