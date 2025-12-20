# ruff: noqa: E501
import json
import logging
import os
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote, quote_plus, urlsplit, urlunsplit
from uuid import NAMESPACE_DNS, uuid5

from loguru import logger
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # --- Core Settings ---
    ENVIRONMENT: Annotated[str, Field(default="development", description="Application environment (e.g., 'development', 'staging', 'production').")]
    DEBUG: bool = Field(default=False, description="Enable application debug mode, providing detailed error pages.")
    TIME_ZONE: Annotated[str, Field(default="Europe/Kyiv", description="Default timezone for the application, used for dates and times.")]
    DEFAULT_LANG: Annotated[str, Field(default="ua", description="Default language for user-facing content.")]
    ADMIN_LANG: Annotated[str, Field(default="ru", description="Default language for the admin interface.")]
    SITE_NAME: Annotated[str, Field(default="AchieveTogether", description="Public name of the site or application.")]
    SECRET_KEY: Annotated[str, Field(default="", description="Secret key for signing session data and tokens. Must be set in production.")]

    # --- Logging ---
    LOG_LEVEL: Annotated[str, Field(default="DEBUG", description="Logging level for the application (e.g., DEBUG, INFO, WARNING).")]
    LOG_VERBOSE_CELERY: Annotated[bool, Field(default=False, description="If True, Celery logs will be more verbose.")]

    # --- Web Server & API ---
    API_HOST: Annotated[str, Field(default="http://127.0.0.1", description="Hostname or IP address the API server binds to.")]
    HOST_API_PORT: Annotated[str, Field(default="8000", description="Port for the API exposed to the host machine (non-Docker).")]
    API_INTERNAL_PORT: Annotated[str, Field(default="8000", description="Port for the API used for inter-service communication inside Docker.")]
    API_URL: Annotated[str | None, Field(default=None, description="Canonical public URL for the API. Auto-derived if not set.")]
    WEB_SERVER_HOST: Annotated[str, Field(default="0.0.0.0", description="Host for the web server to bind to.")]
    ALLOWED_HOSTS: Annotated[list[str], Field(default=["localhost", "127.0.0.1"], description="A list of allowed host/domain names for the application.")]
    CORS_ALLOW_ALL_ORIGINS: bool = Field(default=False, description="If True, allow Cross-Origin Resource Sharing from any origin.")

    # --- Webhooks & Public URLs ---
    WEBHOOK_HOST: Annotated[str, Field(default="", description="Publicly accessible base host for webhooks (e.g., https://example.com).")]
    HOST_NGINX_PORT: Annotated[str, Field(default="8000", description="Port NGINX listens on from the host's perspective.")]
    WEBHOOK_PATH: Annotated[str, Field(default="/telegram/webhook", description="Path for the Telegram bot webhook.")]
    WEBHOOK_URL: str | None = Field(default=None, description="Full URL for the Telegram bot webhook. Auto-derived if not set.")
    WEBAPP_PUBLIC_URL: Annotated[str | None, Field(default=None, description="Public URL for the web application. Auto-derived if not set.")]
    PAYMENT_CALLBACK_URL: str | None = Field(default=None, description="URL for receiving payment status callbacks. Auto-derived if not set.")

    # --- Security & API Keys ---
    API_KEY: Annotated[str, Field(default="", description="External API key for client access. Must be set in production.")]
    INTERNAL_KEY_ID: Annotated[str, Field(default="gymbot-internal-v1", description="Identifier for the internal HMAC key.")]
    INTERNAL_API_KEY: Annotated[str, Field(default="", description="Shared secret for internal service-to-service HMAC authentication.")]
    INTERNAL_IP_ALLOWLIST: Annotated[list[str], Field(default_factory=list, description="List of IP addresses allowed to bypass certain checks.")]
    AI_COACH_INTERNAL_KEY_ID: Annotated[str, Field(default="", description="Key ID for authenticating with the AI Coach service.")]
    AI_COACH_INTERNAL_API_KEY: Annotated[str, Field(default="", description="Secret key for authenticating with the AI Coach service.")]

    # --- Database (PostgreSQL) ---
    DB_HOST: Annotated[str, Field(default="db", description="Hostname of the PostgreSQL database server.")]
    DB_PORT: Annotated[str, Field(default="5432", description="Port of the PostgreSQL database server.")]
    DB_NAME: Annotated[str, Field(default="postgres", description="Name of the PostgreSQL database.")]
    DB_USER: Annotated[str, Field(default="postgres", description="Username for the PostgreSQL database.")]
    DB_PASSWORD: Annotated[str, Field(alias="POSTGRES_PASSWORD", default="password", description="Password for the PostgreSQL database.")]
    DB_PROVIDER: Annotated[str, Field(default="postgres", description="Database provider type (for internal use).")]

    # --- Vector Database ---
    VECTOR_DB_PROVIDER: Annotated[str, Field(default="qdrant", description="Vector database provider (e.g., 'qdrant').")]
    VECTOR_DB_URL_OVERRIDE: Annotated[str | None, Field(alias="VECTOR_DB_URL", default=None, description="Explicit connection URL for the vector database. Overrides provider-derived defaults.")]
    VECTOR_DB_KEY: Annotated[str, Field(default="", description="API key for vector database access (e.g., Qdrant Cloud).")]
    QDRANT_HOST: Annotated[str, Field(default="qdrant", description="Hostname of the Qdrant service within Docker networks.")]
    QDRANT_HTTP_PORT: Annotated[int, Field(default=6333, description="HTTP port of the Qdrant service.")]
    QDRANT_GRPC_PORT: Annotated[int, Field(default=6334, description="gRPC port of the Qdrant service.")]

    # --- Graph Database ---
    GRAPH_DATABASE_PROVIDER: Annotated[str, Field(default="networkx", description="Graph database provider (e.g., 'networkx', 'neo4j').")]
    GRAPH_DATABASE_HOST: Annotated[str, Field(default="neo4j", description="Hostname of the graph database server.")]
    GRAPH_DATABASE_PORT: Annotated[str, Field(default="7687", description="Port of the graph database server.")]
    GRAPH_DATABASE_NAME: Annotated[str, Field(default="neo4j", description="Name of the graph database.")]
    GRAPH_DATABASE_USERNAME: Annotated[str, Field(default="neo4j", description="Username for the graph database.")]
    GRAPH_DATABASE_PASSWORD: Annotated[str, Field(default="neo4j", description="Password for the graph database.")]

    # --- Cache (Redis) ---
    REDIS_URL: Annotated[str, Field(default="redis://redis:6379", description="Full connection URL for Redis.")]
    REDIS_HOST: Annotated[str, Field(default="redis", description="Hostname of the Redis server.")]
    REDIS_PORT: Annotated[int, Field(default=6379, description="Port of the Redis server.")]
    HOST_REDIS_PORT: Annotated[str, Field(default="6379", description="Port for Redis exposed to the host machine (non-Docker).")]
    CACHE_TTL: int = Field(default=60 * 5, description="Default Time-To-Live for cached items in seconds.")

    # --- Message Broker (RabbitMQ) ---
    RABBITMQ_URL: Annotated[str | None, Field(default=None, description="Full connection URL for RabbitMQ. Auto-derived if not set.")]
    RABBITMQ_HOST: Annotated[str, Field(default="rabbitmq", description="Hostname of the RabbitMQ server.")]
    RABBITMQ_PORT: Annotated[str, Field(default="5672", description="Port of the RabbitMQ server.")]
    RABBITMQ_USER: Annotated[str, Field(default="rabbitmq", description="Username for RabbitMQ. Must be set in production.")]
    RABBITMQ_PASSWORD: Annotated[str, Field(default="rabbitmq", description="Password for RabbitMQ. Must be set in production.")]
    RABBITMQ_VHOST: Annotated[str, Field(default="/", description="RabbitMQ virtual host.")]

    # --- Telegram Bot ---
    BOT_TOKEN: Annotated[str, Field(default="", description="Authentication token for the Telegram Bot API.")]
    BOT_LINK: Annotated[str, Field(default="", description="Public link to the Telegram bot (e.g., t.me/my_bot).")]
    BOT_NAME: str = Field(default="Lifty", description="Display name for the bot.")
    BOT_PORT: Annotated[int, Field(default=8088, description="Port the bot webhook server listens on.")]
    BOT_INTERNAL_HOST: Annotated[str, Field(default="bot", description="Internal hostname for the bot service (in Docker).")]
    BOT_INTERNAL_PORT: Annotated[int, Field(default=8000, description="Internal port for the bot service (in Docker).")]
    BOT_INTERNAL_URL: Annotated[str, Field(default="http://bot:8000/", description="Internal URL for the API to communicate with the bot.")]
    DOCKER_BOT_START: Annotated[bool, Field(default=False, description="Flag indicating if the bot is running in a Docker container.")]

    # --- AI Coach Service ---
    AI_COACH_URL: Annotated[str, Field(default="http://ai_coach:9000/", description="URL of the AI Coach service.")]
    AI_COACH_HOST: Annotated[str, Field(default="ai_coach", description="Hostname of the AI Coach service.")]
    AI_COACH_PORT: Annotated[int, Field(default=9000, description="Port of the AI Coach service.")]
    AI_COACH_TIMEOUT: int = Field(default=420, description="Timeout in seconds for long-running AI coach operations.")
    AI_COACH_REFRESH_USER: Annotated[str, Field(default="admin", description="Username for AI Coach knowledge base refresh endpoint.")]
    AI_COACH_REFRESH_PASSWORD: Annotated[str, Field(default="password", description="Password for AI Coach knowledge base refresh endpoint.")]
    AI_COACH_MAX_TOOL_CALLS: Annotated[int, Field(default=5, description="Maximum number of tool calls an AI agent can make in one turn.")]
    AI_COACH_REQUEST_TIMEOUT: Annotated[int, Field(default=60, description="Default timeout for requests to the AI Coach in seconds.")]
    AI_COACH_MAX_RUN_SECONDS: Annotated[float, Field(default=200.0, description="Time budget in seconds for a single AI coach agent run before aborting.")]
    AI_COACH_GLOBAL_PROJECTION_TIMEOUT: Annotated[float, Field(default=15.0, description="Timeout for global projection operations in seconds.")]
    AI_COACH_GRAPH_ATTACH_TIMEOUT: Annotated[
        float,
        Field(default=45.0, description="Maximum time to wait for the graph engine to become reachable during startup."),
    ]
    AI_COACH_DEFAULT_TOOL_TIMEOUT: Annotated[float, Field(default=3.0, description="Default timeout for AI agent tool calls in seconds.")]
    AI_COACH_SEARCH_TIMEOUT: Annotated[float, Field(default=180.0, description="Timeout for search tool calls in seconds.")]
    AI_COACH_MEMIFY_DELAY_SECONDS: Annotated[
        float, Field(default=3600.0, description="Delay in seconds before scheduling Cognee memify for profile datasets.")
    ]
    AI_COACH_CHAT_SUMMARY_PAIR_LIMIT: Annotated[int, Field(default=10, description="Number of client/coach message pairs required before summarizing chat history.")]
    AI_COACH_CHAT_SUMMARY_MAX_TOKENS: Annotated[int, Field(default=400, description="Max tokens for the chat summary LLM request.")]
    AI_COACH_REDIS_CHAT_DB: Annotated[int, Field(default=2, description="Redis database index used for cached chat history summaries.")]
    AI_COACH_REDIS_STATE_DB: Annotated[int, Field(default=3, description="Redis database index used for AI coach idempotency and delivery state.")]
    AI_COACH_COGNEE_SESSION_TTL: Annotated[int, Field(default=0, description="TTL in seconds for Cognee session cache; 0 disables expiry.")]
    AI_COACH_LOG_PAYLOADS: Annotated[bool, Field(default=False, description="Log AI coach payloads and sources in debug logs when enabled.")]
    AI_COACH_HISTORY_TIMEOUT: Annotated[float, Field(default=180.0, description="Timeout for retrieving user history in seconds.")]
    AI_COACH_PROGRAM_HISTORY_TIMEOUT: Annotated[float, Field(default=6.0, description="Timeout for retrieving workout program history in seconds.")]
    AI_COACH_SAVE_TIMEOUT: Annotated[float, Field(default=30.0, description="Timeout for saving data from the AI coach in seconds.")]
    AI_COACH_ATTACH_GIFS_MIN_BUDGET: Annotated[float, Field(default=10.0, description="Minimum time budget in seconds to allow attaching GIFs.")]
    AI_COACH_RATE_LIMIT: Annotated[int, Field(default=120, description="Number of allowed AI Coach requests per rate-limiting period.")]
    AI_COACH_RATE_PERIOD: Annotated[int, Field(default=60, description="Rate-limiting period in seconds for AI Coach requests.")]

    # --- LLM & Agent Settings ---
    OPENAI_BASE_URL: Annotated[str, Field(default="https://api.openai.com/v1", description="Base URL for OpenAI-compatible API.")]
    LLM_API_URL: Annotated[str, Field(default="https://openrouter.ai/api/v1", description="API URL for the primary LLM provider.")]
    LLM_API_KEY: Annotated[str, Field(default="", description="API key for the LLM provider (used for both Cognee embeddings and agent generations).")]
    LLM_MODEL: Annotated[str, Field(default="gpt-5-mini", description="Default LLM model identifier for Cognee.")]
    LLM_PROVIDER: Annotated[str, Field(default="custom", description="LLM provider identifier for Cognee (e.g., 'openai', 'custom').")]
    AGENT_MODEL: Annotated[str, Field(default="openai/gpt-5-mini", description="Model identifier for the AI Coach agent.")]
    AGENT_PROVIDER: Annotated[str, Field(default="openrouter", description="Provider for the AI Coach agent model.")]
    COACH_AGENT_RETRIES: int = Field(default=1, description="Number of retries for the coach agent if an operation fails.")
    COACH_AGENT_TIMEOUT: int = Field(default=60, description="Timeout in seconds for a single coach agent operation.")
    CHAT_HISTORY_LIMIT: int = Field(default=20, description="Number of past messages to include in the chat history for context.")
    LLM_COOLDOWN: int = Field(default=60, description="Cooldown period in seconds between certain LLM-intensive actions.")
    AI_COACH_SECONDARY_MODEL: Annotated[str | None, Field(default=None, description="A fallback or secondary LLM model for specific tasks.")]
    AI_COACH_FIRST_PASS_MAX_TOKENS: Annotated[int, Field(default=8192, description="Max tokens for the first generation pass of the AI coach.")]
    AI_COACH_RETRY_MAX_TOKENS: Annotated[int, Field(default=8192, description="Max tokens for retry attempts in the AI coach.")]
    AI_COACH_CONTINUATION_MAX_TOKENS: Annotated[int, Field(default=4096, description="Max tokens for continuation prompts in the AI coach.")]
    AI_COACH_EMPTY_COMPLETION_RETRY: Annotated[bool, Field(default=True, description="Whether to retry if the LLM returns an empty completion.")]
    AI_COACH_PRIMARY_CONTEXT_LIMIT: Annotated[int, Field(default=2200, description="Context token limit for primary AI coach prompts.")]
    AI_COACH_RETRY_CONTEXT_LIMIT: Annotated[int, Field(default=1400, description="Context token limit for retry AI coach prompts.")]
    DISABLE_MANUAL_PLACEHOLDER: Annotated[bool, Field(default=True, description="Disable manual placeholder replacement in AI responses.")]
    COACH_AGENT_TEMPERATURE: Annotated[float, Field(default=0.2, description="Temperature used by the AI coach agent when sampling responses from the LLM.")]

    # --- Embedding Settings ---
    EMBEDDING_MODEL: Annotated[str, Field(default="openai/text-embedding-3-large", description="Identifier for the text embedding model.")]
    EMBEDDING_PROVIDER: Annotated[str, Field(default="openai", description="Provider for the text embedding model.")]
    EMBEDDING_ENDPOINT: Annotated[str, Field(default="https://openrouter.ai/api/v1", description="API endpoint for the embedding service.")]

    # --- Cognee & Knowledge Base ---
    COGNEE_STORAGE_PATH: Annotated[str, Field(default="cognee_storage", description="Path to the directory for Cognee's persistent storage.")]
    COGNEE_CLIENT_DATASET_NAMESPACE: Annotated[str | None, Field(default=None, description="Unique namespace for Cognee datasets. Auto-generated if not set.")]
    KB_CHAT_PROJECT_DEBOUNCE_MIN: Annotated[float, Field(default=5.0, description="Debounce time for knowledge base chat projects.")]
    COGNEE_STORAGE_SHA_PRIMARY: Annotated[bool, Field(default=True, description="Use SHA-based primary keys in Cognee storage.")]
    COGNEE_GLOBAL_DATASET: Annotated[str, Field(default="kb_global", description="Name of the global dataset in the knowledge base.")]
    COGNEE_ENABLE_AGGRESSIVE_REBUILD: Annotated[bool, Field(default=False, description="If True, aggressively rebuild knowledge base on changes.")]
    KB_BOOTSTRAP_ALWAYS: Annotated[bool, Field(default=False, description="If True, always run the knowledge base bootstrap process on startup.")]
    KNOWLEDGE_BASE_FOLDER_ID: Annotated[str, Field(default="", description="Google Drive folder ID for knowledge base documents.")]
    KNOWLEDGE_REFRESH_INTERVAL: int = Field(default=60 * 60, description="Interval in seconds to refresh the knowledge base from the source.")
    KNOWLEDGE_REFRESH_START_DELAY: int = Field(default=180, description="Delay in seconds before starting the first knowledge base refresh.")
    COGNEE_SEARCH_MODE: Annotated[str, Field(default="GRAPH_COMPLETION_CONTEXT_EXTENSION", description="Search type for Cognee queries (e.g., 'GRAPH_COMPLETION_CONTEXT_EXTENSION').")]

    EXERCISE_GIF_BUCKET: Annotated[str, Field(default="exercises_guide", description="Google Cloud Storage bucket name used for exercise GIF assets.")]
    EXERCISE_GIF_BASE_URL: Annotated[str, Field(default="https://storage.googleapis.com", description="Base URL for the exercise GIF storage.")]

    # --- AI-Generated Workout Plans ---
    AI_PLAN_DEDUP_TTL: Annotated[int, Field(default=3600, description="TTL in seconds for workout plan request deduplication.")]
    AI_PLAN_NOTIFY_TIMEOUT: Annotated[int, Field(default=900, description="Timeout in seconds for sending workout plan notifications.")]
    AI_PLAN_NOTIFY_POLL_INTERVAL: Annotated[int, Field(default=30, description="Polling interval in seconds for workout plan notification status.")]
    AI_PLAN_NOTIFY_FAILURE_TTL: Annotated[int, Field(default=86400, description="TTL in seconds for storing workout plan notification failures.")]

    # --- AI Q&A Feature ---
    AI_QA_IMAGE_MAX_BYTES: Annotated[int, Field(default=512_000, description="Maximum size in bytes for images uploaded for AI Q&A.")]
    AI_QA_DEDUP_TTL: Annotated[int, Field(default=86400, description="TTL in seconds for 'Ask AI' request deduplication (24 hours).")]
    AI_QA_MAX_RETRIES: Annotated[int, Field(default=5, description="Maximum number of retries for a failed 'Ask AI' request.")]
    AI_QA_RETRY_BACKOFF_S: Annotated[int, Field(default=30, description="Backoff delay in seconds between 'Ask AI' retries.")]

    # --- HTTP Client ---
    API_MAX_RETRIES: int = Field(default=1, description="Maximum number of retries for failing outbound API calls.")
    API_RETRY_INITIAL_DELAY: int = Field(default=1, description="Initial delay in seconds for API call retries.")
    API_RETRY_BACKOFF_FACTOR: int = Field(default=2, description="Factor by which to increase delay between API retries.")
    API_RETRY_MAX_DELAY: int = Field(default=10, description="Maximum delay in seconds between API retries.")
    API_TIMEOUT: int = Field(default=10, description="Default timeout in seconds for outbound API calls.")
    API_MAX_CONNECTIONS: int = Field(default=100, description="Maximum number of connections for the HTTP client pool.")
    API_MAX_KEEPALIVE_CONNECTIONS: int = Field(default=20, description="Maximum number of keep-alive connections for the HTTP client.")
    INTERNAL_HTTP_CONNECT_TIMEOUT: Annotated[float, Field(default=10.0, description="Connect timeout in seconds for internal HTTP calls.")]
    INTERNAL_HTTP_READ_TIMEOUT: Annotated[float, Field(default=30.0, description="Read timeout in seconds for internal HTTP calls.")]

    # --- Business Logic & Pricing ---
    MIN_BIRTH_YEAR: int = Field(default=1940, description="Minimum allowed birth year for user profiles.")
    MAX_BIRTH_YEAR: int = Field(default=2020, description="Maximum allowed birth year for user profiles.")
    MAX_FILE_SIZE_MB: int = Field(default=10, description="Maximum size in megabytes for uploaded files.")
    DEFAULT_CREDITS: int = Field(default=500, description="Number of credits new users receive upon registration.")
    PACKAGE_START_CREDITS: int = Field(default=500, description="Number of credits in the 'Start' package.")
    PACKAGE_START_PRICE: Decimal = Field(default=Decimal("250"), description="Price of the 'Start' credit package.")
    PACKAGE_OPTIMUM_CREDITS: int = Field(default=1200, description="Number of credits in the 'Optimum' package.")
    PACKAGE_OPTIMUM_PRICE: Decimal = Field(default=Decimal("500"), description="Price of the 'Optimum' credit package.")
    PACKAGE_MAX_CREDITS: int = Field(default=5000, description="Number of credits in the 'Max' package.")
    PACKAGE_MAX_PRICE: Decimal = Field(default=Decimal("1500"), description="Price of the 'Max' credit package.")
    AI_PROGRAM_PRICE: Decimal = Field(default=Decimal("400"), description="Price in credits for generating an AI workout program.")
    SMALL_SUBSCRIPTION_PRICE: Decimal = Field(default=Decimal("500"), description="Price in credits for a 1 month AI coach subscription.")
    MEDIUM_SUBSCRIPTION_PRICE: Decimal = Field(default=Decimal("2400"), description="Price in credits for a 6 months AI coach subscription.")
    LARGE_SUBSCRIPTION_PRICE: Decimal = Field(default=Decimal("4750"), description="Price in credits for a 1 year AI coach subscription.")
    ASK_AI_PRICE: Annotated[int, Field(default=25, description="Price in credits for a single 'Ask AI' question.")]

    # --- Payments ---
    PAYMENT_PRIVATE_KEY: Annotated[str, Field(default="", description="Private key for the payment provider API.")]

    @field_validator("LLM_API_KEY", mode="before")
    @classmethod
    def _populate_llm_api_key(cls, value: str | None) -> str:
        if value:
            return value
        for env_name in ("EMBEDDING_API_KEY", "OPENAI_API_KEY"):
            fallback = os.environ.get(env_name)
            if fallback:
                return fallback
        return ""

    def model_post_init(self, __context: Any) -> None:
        super().model_post_init(__context)
        if not self.LLM_API_KEY:
            logger.warning("LLM_API_KEY is not configured; AI coach operations may fail.")
        else:
            os.environ.setdefault("OPENAI_API_KEY", self.LLM_API_KEY)
            os.environ.setdefault("EMBEDDING_API_KEY", self.LLM_API_KEY)
        os.environ.setdefault("OPENAI_API_BASE", self.EMBEDDING_ENDPOINT)
        os.environ.setdefault("OPENAI_API_URL", self.EMBEDDING_ENDPOINT)
    PAYMENT_PUB_KEY: Annotated[str, Field(default="", description="Public key for the payment provider API.")]
    CHECKOUT_URL: Annotated[str, Field(default="", description="Base URL for the payment provider's checkout page.")]
    BOT_PAYMENT_OPTIONS: Annotated[str, Field(default="bot/images", description="Path to image assets for payment options in the bot.")]
    PAYMENT_CHECK_INTERVAL: int = Field(default=60, description="Interval in seconds for periodic payment status checks.")

    # --- Miscellaneous & Integrations ---
    GOOGLE_APPLICATION_CREDENTIALS: Annotated[str, Field(default="google_creds.json", description="Path to Google Cloud service account credentials file.")]
    SPREADSHEET_ID: Annotated[str, Field(default="", description="ID of the Google Sheet for data integration.")]
    TG_SUPPORT_CONTACT: Annotated[str, Field(default="", description="Telegram username or link for user support.")]
    PUBLIC_OFFER: Annotated[str, Field(default="", description="URL to the public offer document.")]
    PRIVACY_POLICY: Annotated[str, Field(default="", description="URL to the privacy policy document.")]
    EMAIL: Annotated[str, Field(default="", description="Contact email address.")]
    ADMIN_ID: Annotated[str, Field(default="", description="Telegram user ID of the primary administrator.")]
    BACKUP_RETENTION_DAYS: int = Field(default=30, description="Number of days to retain database and storage backups.")
    ENABLE_KB_BACKUPS: bool = Field(default=False, description="Enable scheduled backups for Neo4j and Qdrant.")

    # --- Admin Credentials ---
    DJANGO_ADMIN: Annotated[str, Field(default="admin", description="Username for the Django admin panel superuser.")]
    DJANGO_PASSWORD: Annotated[str, Field(default="admin", description="Password for the Django admin panel superuser.")]

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
        "extra": "ignore",
    }

    @field_validator("ALLOWED_HOSTS", mode="before")
    @classmethod
    def _parse_allowed_hosts(cls, v: Any) -> list[str]:
        """
        Normalize ALLOWED_HOSTS from environment.

        Behaviour (kept compatible with the original implementation):
        - If value is None or an empty string -> default to ["localhost", "127.0.0.1"].
        - If value is a string:
            * first try to parse it as JSON list;
            * on JSON error, treat it as a comma-separated list.
        - Otherwise, return value as is.
        """
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

    @field_validator("INTERNAL_IP_ALLOWLIST", mode="before")
    @classmethod
    def _normalize_ip_allowlist(cls, value: Any) -> list[str]:
        """
        Normalize INTERNAL_IP_ALLOWLIST from environment.

        Behaviour (kept compatible with the original implementation):
        - None -> []
        - string "a,b,c" -> ["a", "b", "c"]
        - list/tuple/set -> cast each item to string and strip
        - anything else -> []
        """
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
        """
        Compute and validate derived configuration fields after initial parsing.
        This method acts as an orchestrator for domain-specific configuration logic.
        """
        environment = str(self.ENVIRONMENT).lower()
        in_docker = os.path.exists("/.dockerenv") or os.getenv("KUBERNETES_SERVICE_HOST") is not None

        self._configure_web_urls(in_docker)
        self._configure_storage_paths(in_docker)
        self._configure_cognee_namespace()
        self._configure_redis(in_docker)
        self._configure_rabbitmq(in_docker, environment)
        self._configure_ai_coach(in_docker)
        self._configure_bot(in_docker)

        if environment == "production":
            self._validate_production_secrets()

        return self

    def _configure_web_urls(self, in_docker: bool) -> None:
        """Configure public-facing URLs and the main API URL."""
        if not self.WEBHOOK_URL:
            self.WEBHOOK_URL = f"{self.WEBHOOK_HOST}{self.WEBHOOK_PATH}"

        if not self.WEBAPP_PUBLIC_URL:
            self.WEBAPP_PUBLIC_URL = self.WEBHOOK_HOST

        if not self.PAYMENT_CALLBACK_URL:
            self.PAYMENT_CALLBACK_URL = f"{self.WEBHOOK_HOST}/payments-webhook/"

        if not self.API_URL:
            self.API_URL = self._derive_api_url(in_docker)

    def _configure_storage_paths(self, in_docker: bool) -> None:
        """Resolve and absolutize storage paths."""
        storage_path = Path(self.COGNEE_STORAGE_PATH).expanduser()
        if in_docker and not storage_path.is_absolute():
            storage_path = Path("/app") / storage_path
        try:
            self.COGNEE_STORAGE_PATH = str(storage_path.resolve(strict=False))
        except RuntimeError:
            self.COGNEE_STORAGE_PATH = str(storage_path)

    def _configure_cognee_namespace(self) -> None:
        """Generate a deterministic namespace for Cognee datasets if not provided."""
        if not self.COGNEE_CLIENT_DATASET_NAMESPACE:
            namespace_seed = self.SECRET_KEY or self.SITE_NAME or "gymbot"
            base_namespace = uuid5(NAMESPACE_DNS, "gymbot.cognee")
            self.COGNEE_CLIENT_DATASET_NAMESPACE = str(uuid5(base_namespace, namespace_seed))

    def _configure_redis(self, in_docker: bool) -> None:
        """Configure the Redis connection URL."""
        # Compose URL from host/port hints when provided or URL is missing
        if os.getenv("REDIS_HOST") or os.getenv("REDIS_PORT") or not self.REDIS_URL:
            redis_host = os.getenv("REDIS_HOST", self.REDIS_HOST or "redis")
            redis_port = os.getenv("REDIS_PORT", str(self.REDIS_PORT or self.HOST_REDIS_PORT or 6379))
            self.REDIS_URL = f"redis://{redis_host}:{redis_port}"

        # In non-Docker, if URL still points to default Docker service, switch to localhost
        if not in_docker:
            normalized = (self.REDIS_URL or "").strip().lower()
            if not normalized or normalized.startswith("redis://redis"):
                # Preserve original behaviour: default to 127.0.0.1:6379 for host processes
                self.REDIS_URL = "redis://127.0.0.1:6379"

    def _configure_rabbitmq(self, in_docker: bool, environment: str) -> None:
        """Configure the RabbitMQ connection URL and credentials."""
        # Non-Docker: help host processes reach broker by switching 'rabbitmq' to 'localhost'
        if not in_docker and (self.RABBITMQ_HOST or "").lower() == "rabbitmq":
            self.RABBITMQ_HOST = os.getenv("RABBITMQ_HOST_LOCAL", "localhost")

        # Validate credentials in production or use fallback for dev
        if not self.RABBITMQ_USER or not self.RABBITMQ_PASSWORD:
            if environment == "production":
                raise ValueError("RABBITMQ_USER and RABBITMQ_PASSWORD must be set in production")
            self.RABBITMQ_USER = self.RABBITMQ_USER or "rabbitmq"
            self.RABBITMQ_PASSWORD = self.RABBITMQ_PASSWORD or "rabbitmq"
            logging.getLogger(__name__).warning(
                "RabbitMQ credentials not set; using fallback values for non-production environment"
            )

        # Determine whether we should rebuild the URL
        rebuild_url = not self.RABBITMQ_URL and bool(
            os.getenv("RABBITMQ_HOST") or os.getenv("RABBITMQ_PORT") or self.RABBITMQ_HOST or self.RABBITMQ_PORT
        )
        if rebuild_url:
            encoded_user = quote_plus(self.RABBITMQ_USER)
            encoded_password = quote_plus(self.RABBITMQ_PASSWORD)
            encoded_vhost = quote(self.RABBITMQ_VHOST, safe="")
            rabbit_host_env = os.getenv("RABBITMQ_HOST")

            if in_docker:
                rabbit_host = rabbit_host_env or self.RABBITMQ_HOST or "rabbitmq"
                if rabbit_host in {"", "localhost", "127.0.0.1"}:
                    rabbit_host = os.getenv("RABBITMQ_SERVICE_HOST", "rabbitmq")
            else:
                rabbit_host = self.RABBITMQ_HOST or rabbit_host_env or "localhost"

            rabbit_port = os.getenv("RABBITMQ_PORT", self.RABBITMQ_PORT or "5672")
            self.RABBITMQ_URL = f"amqp://{encoded_user}:{encoded_password}@{rabbit_host}:{rabbit_port}/{encoded_vhost}"
        # In Docker, normalize service host if an override is present
        if in_docker and self.RABBITMQ_URL:
            rabbitmq_service_host = os.getenv("RABBITMQ_SERVICE_HOST")
            if rabbitmq_service_host:
                self.RABBITMQ_URL = self.normalize_service_host(
                    self.RABBITMQ_URL,
                    rabbitmq_service_host,
                    default_scheme="amqp",
                    force=False,
                )

    def _configure_ai_coach(self, in_docker: bool) -> None:
        """Configure the AI Coach service URL."""
        # Rebuild from host/port if specified via env vars or URL is missing
        if os.getenv("AI_COACH_HOST") or os.getenv("AI_COACH_PORT") or not self.AI_COACH_URL:
            coach_host = os.getenv("AI_COACH_HOST", self.AI_COACH_HOST or "ai_coach")
            coach_port = os.getenv("AI_COACH_PORT", str(self.AI_COACH_PORT or 9000))
            self.AI_COACH_URL = f"http://{coach_host}:{coach_port}"

        # In Docker, normalize service host if an override is present
        if in_docker and self.AI_COACH_URL:
            ai_coach_host = os.getenv("AI_COACH_SERVICE_HOST", "ai_coach")
            self.AI_COACH_URL = self.normalize_service_host(self.AI_COACH_URL, ai_coach_host)

        self.AI_COACH_URL = self.normalize_service_url(self.AI_COACH_URL)

    def _configure_bot(self, in_docker: bool) -> None:
        """Configure the internal Bot service URL."""
        # Rebuild from host/port if specified via env vars or URL is missing
        if os.getenv("BOT_INTERNAL_HOST") or os.getenv("BOT_INTERNAL_PORT") or not self.BOT_INTERNAL_URL:
            bot_host = os.getenv("BOT_INTERNAL_HOST", self.BOT_INTERNAL_HOST or "bot")
            bot_port = os.getenv("BOT_INTERNAL_PORT", str(self.BOT_INTERNAL_PORT or 8000))
            self.BOT_INTERNAL_URL = f"http://{bot_host}:{bot_port}"

        # In Docker, handle service host override (e.g., host.docker.internal)
        if in_docker and self.BOT_INTERNAL_URL:
            # When the API (not in Docker) calls the bot (in Docker), it needs the host override.
            force_override = not self.DOCKER_BOT_START
            bot_service_host = os.getenv("BOT_SERVICE_HOST", "host.docker.internal")
            self.BOT_INTERNAL_URL = self.normalize_service_host(
                self.BOT_INTERNAL_URL,
                bot_service_host,
                force=force_override,
            )

    def _validate_production_secrets(self) -> None:
        """Ensure that critical secrets are not using default or empty values in production."""
        self._require_secret("SECRET_KEY", self.SECRET_KEY)
        self._require_secret("API_KEY", self.API_KEY)
        self._require_secret("INTERNAL_API_KEY", self.INTERNAL_API_KEY)
        self._require_secret("INTERNAL_KEY_ID", self.INTERNAL_KEY_ID)
        self._require_secret("AI_COACH_INTERNAL_KEY_ID", self.AI_COACH_INTERNAL_KEY_ID)
        self._require_secret("AI_COACH_INTERNAL_API_KEY", self.AI_COACH_INTERNAL_API_KEY)
        self._require_secret("RABBITMQ_USER", self.RABBITMQ_USER)
        self._require_secret("RABBITMQ_PASSWORD", self.RABBITMQ_PASSWORD)

    @staticmethod
    def _require_secret(name: str, value: Any) -> None:
        """
        Raise a ValueError if a required secret has a weak or empty value.
        Behaviour is kept compatible with the original implementation.
        """
        bad_values = {
            "",
            "changeme",
            "admin",
            "password",
            "secure_rabbitmq_password",
            "change_me_ai_coach_hmac",
            "placeholder",
        }
        if str(value or "").strip() in bad_values:
            raise ValueError(f"{name} must be set in production")

    def _derive_api_url(self, in_docker: bool) -> str:
        """
        Build the canonical API URL, accounting for container networking.
        It intelligently combines host, port, and scheme from various sources.
        """
        api_host_raw = str(self.API_HOST).strip()
        has_scheme = "://" in api_host_raw
        prepared_host = api_host_raw if has_scheme else f"http://{api_host_raw}"
        parsed = urlsplit(prepared_host)

        scheme = parsed.scheme or "http"
        netloc_source = parsed.netloc or parsed.path
        if ":" in netloc_source:
            hostname, existing_port = netloc_source.split(":", 1)
        else:
            hostname, existing_port = netloc_source, None

        normalized_hostname = hostname or "api"
        if in_docker and normalized_hostname in {"127.0.0.1", "localhost"}:
            normalized_hostname = os.getenv("API_SERVICE_HOST", "api")

        port_env_raw = os.getenv("API_PORT")
        port_env = port_env_raw.strip() if port_env_raw else None
        existing_port_clean = existing_port.strip() if existing_port else None
        port_candidates = (
            port_env,
            existing_port_clean,
        )
        resolved_port = next((candidate for candidate in port_candidates if candidate), None)
        if not resolved_port:
            resolved_port = self.API_INTERNAL_PORT if in_docker else self.HOST_API_PORT

        netloc = f"{normalized_hostname}:{resolved_port}" if resolved_port else normalized_hostname
        return urlunsplit((scheme, netloc, "/", "", ""))

    @property
    def VECTOR_DB_URL(self) -> str:
        """Construct the full connection URL for the vector database."""
        if self.VECTOR_DB_URL_OVERRIDE:
            return self.VECTOR_DB_URL_OVERRIDE
        provider = (self.VECTOR_DB_PROVIDER or "").lower()
        if provider == "qdrant":
            host = self.QDRANT_HOST or "qdrant"
            port = self.QDRANT_HTTP_PORT or 6333
            return f"http://{host}:{port}"
        raise RuntimeError(f"Unsupported vector database provider: {self.VECTOR_DB_PROVIDER!r}")

    @property
    def GRAPH_DATABASE_URL(self) -> str:
        """Construct the full connection URL for the graph database."""
        host = (self.GRAPH_DATABASE_HOST or "").strip() or "neo4j"
        port = (str(self.GRAPH_DATABASE_PORT) or "").strip()
        endpoint = f"{host}:{port}" if port else host
        db_name = (self.GRAPH_DATABASE_NAME or "").strip()
        path = f"/{db_name}" if db_name else ""
        return f"bolt://{endpoint}{path}"

    @staticmethod
    def normalize_service_host(
        url: str,
        new_host: str,
        *,
        default_scheme: str = "http",
        force: bool = False,
    ) -> str:
        """
        Replace localhost-like hosts in a URL with a specified service host.

        This is used to switch from local development addresses (like localhost, 127.0.0.1)
        to internal Docker service names (like 'api', 'bot', 'rabbitmq').

        Args:
            url: The original URL to process.
            new_host: The new hostname to substitute.
            default_scheme: The URL scheme to assume if none is present.
            force: If True, replace the host regardless of what it is.

        Returns:
            The URL with the host replaced, or the original URL if replacement criteria are not met.
        """
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

    @staticmethod
    def normalize_service_url(
        url: str,
        *,
        default_scheme: str = "http",
        ensure_trailing_slash: bool = True,
    ) -> str:
        """
        Ensure a service URL has a scheme and a consistent trailing slash.

        Args:
            url: The URL to normalize.
            default_scheme: The scheme to add if missing (e.g., 'http').
            ensure_trailing_slash: If True, ensures the URL ends with a '/' if the original path did.

        Returns:
            The normalized URL string.
        """
        raw = (url or "").strip()
        if not raw:
            return url

        candidate = raw if "://" in raw else f"{default_scheme}://{raw}"
        parsed = urlsplit(candidate)
        scheme = parsed.scheme or default_scheme
        netloc = parsed.netloc or parsed.path
        path = parsed.path if parsed.netloc else "/"
        normalized = urlunsplit((scheme, netloc, path or "/", parsed.query, parsed.fragment))

        if ensure_trailing_slash:
            original_path = parsed.path or "/"
            if (original_path == "/" or original_path.endswith("/")) and not normalized.endswith("/"):
                normalized = f"{normalized}/"

        return normalized


def normalize_service_host(
    url: str,
    new_host: str,
    *,
    default_scheme: str = "http",
    force: bool = False,
) -> str:
    """
    Backwards-compatible wrapper around Settings.normalize_service_host.

    Tests and legacy code import this helper from the module level; keep the same signature.
    """
    return Settings.normalize_service_host(url, new_host, default_scheme=default_scheme, force=force)


settings = Settings()  # noqa  # pyrefly: ignore[missing-argument]
