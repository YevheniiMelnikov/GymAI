import importlib
import os
import cognee
from pathlib import Path
from types import ModuleType
from typing import Any, ClassVar

from loguru import logger
from sqlalchemy.engine.url import URL, make_url

from ai_coach.agent.knowledge.utils.storage_helpers import (
    collect_storage_info,
    patch_local_file_storage,
    prepare_storage_root,
)
from config.app_settings import settings

_COGNEE_MODULE: ModuleType | None = None


class CogneeConfig:
    _STORAGE_ROOT: ClassVar[Path | None] = None
    _CACHE_PATCHED: ClassVar[bool] = False

    @classmethod
    def apply(cls) -> None:
        storage_root = prepare_storage_root()
        cls._STORAGE_ROOT = storage_root

        global _COGNEE_MODULE
        if _COGNEE_MODULE is None:
            _COGNEE_MODULE = importlib.import_module("cognee")
        globals()["cognee"] = _COGNEE_MODULE

        cls._ensure_openai_env()
        cls._configure_cache()

        patch_local_file_storage(storage_root)
        cls._configure_llm()
        cls._configure_vector_db()
        cls._configure_graph_db()
        cls._configure_relational_db()
        cls._patch_cognee()

    @classmethod
    def storage_root(cls) -> Path | None:
        return cls._STORAGE_ROOT

    @classmethod
    def describe_storage(cls) -> dict[str, Any]:
        root = cls._STORAGE_ROOT
        if root is None:
            candidate = os.environ.get("COGNEE_STORAGE_PATH") or os.environ.get("COGNEE_DATA_ROOT")
            if candidate:
                root = Path(candidate).expanduser().resolve()
        return collect_storage_info(root)

    @staticmethod
    def _ensure_openai_env() -> None:
        openai_key = os.environ.get("OPENAI_API_KEY")
        if not openai_key and settings.LLM_API_KEY:
            os.environ["OPENAI_API_KEY"] = settings.LLM_API_KEY
            openai_key = settings.LLM_API_KEY

        openai_base = os.environ.get("OPENAI_BASE_URL")
        if not openai_base:
            candidate_url = settings.LLM_API_URL or settings.OPENAI_BASE_URL
            if candidate_url:
                os.environ["OPENAI_BASE_URL"] = candidate_url
                openai_base = candidate_url

        def _mask(value: str | None) -> str:
            if not value:
                return "unset"
            if len(value) <= 8:
                return value
            return f"{value[:4]}...{value[-4:]}"

        logger.debug(
            (
                "cognee_embedding_env OPENAI_BASE_URL={} LLM_PROVIDER={} "
                "AGENT_PROVIDER={} EMBEDDING_MODEL={} OPENAI_API_KEY={}"
            ),
            openai_base or "unset",
            settings.LLM_PROVIDER,
            settings.AGENT_PROVIDER,
            settings.EMBEDDING_MODEL,
            _mask(openai_key),
        )

    @staticmethod
    def _configure_llm() -> None:
        cognee.config.set_llm_provider(settings.LLM_PROVIDER)
        cognee.config.set_llm_model(settings.LLM_MODEL)
        cognee.config.set_llm_api_key(settings.LLM_API_KEY)
        cognee.config.set_llm_endpoint(settings.LLM_API_URL)

    @staticmethod
    def _configure_vector_db() -> None:
        provider = settings.VECTOR_DB_PROVIDER
        vector_url = settings.VECTOR_DB_URL
        vector_key = settings.VECTOR_DB_KEY
        vector_url_safe = CogneeConfig._render_safe_url(vector_url)
        vector_meta = CogneeConfig._extract_url_meta(vector_url)
        vector_host = vector_meta.get("host") or ""

        if provider == "qdrant":
            importlib.import_module("cognee_community_vector_adapter_qdrant.register")
            cognee.config.set_vector_db_config(
                {
                    "vector_db_provider": provider,
                    "vector_db_url": vector_url,
                    "vector_db_key": vector_key,
                }
            )
        else:
            cognee.config.set_vector_db_provider(provider)
            cognee.config.set_vector_db_url(vector_url)
        os.environ["VECTOR_DB_PROVIDER"] = provider
        os.environ["VECTOR_DB_URL"] = vector_url
        os.environ["VECTOR_DB_KEY"] = vector_key

        logger.info(
            "cognee_vector_config provider={} url={} host={} port={} db={} user={}",
            provider,
            vector_url_safe,
            vector_host or "unset",
            vector_meta.get("port") or "unset",
            vector_meta.get("database") or "unset",
            vector_meta.get("username") or "unset",
        )

    @staticmethod
    def _configure_graph_db() -> None:
        graph_host = settings.GRAPH_DATABASE_HOST or "neo4j"
        if graph_host in {"localhost", "127.0.0.1", ""}:
            graph_host = "neo4j"
        graph_port = settings.GRAPH_DATABASE_PORT or "7687"
        graph_url = settings.GRAPH_DATABASE_URL or f"bolt://{graph_host}:{graph_port}"

        env_graph_provider = os.environ.get("GRAPH_DATABASE_PROVIDER")
        if env_graph_provider and env_graph_provider != settings.GRAPH_DATABASE_PROVIDER:
            logger.warning(
                "cognee_graph_provider_mismatch env={} config={}",
                env_graph_provider,
                settings.GRAPH_DATABASE_PROVIDER,
            )
        os.environ["GRAPH_DATABASE_PROVIDER"] = settings.GRAPH_DATABASE_PROVIDER
        os.environ.setdefault("GRAPH_DATABASE_URL", graph_url)
        os.environ.setdefault("GRAPH_DATABASE_NAME", settings.GRAPH_DATABASE_NAME)
        os.environ.setdefault("GRAPH_DATABASE_USERNAME", settings.GRAPH_DATABASE_USERNAME)
        os.environ.setdefault("GRAPH_DATABASE_PASSWORD", settings.GRAPH_DATABASE_PASSWORD)
        os.environ.setdefault("GRAPH_DATABASE_PORT", str(graph_port))

        graph_db_config = {
            "graph_database_provider": settings.GRAPH_DATABASE_PROVIDER,
            "graph_database_url": graph_url,
            "graph_database_name": settings.GRAPH_DATABASE_NAME,
            "graph_database_username": settings.GRAPH_DATABASE_USERNAME,
            "graph_database_password": settings.GRAPH_DATABASE_PASSWORD,
            "graph_database_port": graph_port,
        }
        cognee.config.set_graph_db_config(graph_db_config)
        env_vector_provider = os.environ.get("VECTOR_DB_PROVIDER", "unset")
        logger.info(
            (
                "cognee_graph_config_applied env_graph_provider={} config_graph_provider={} "
                "env_vector_provider={} url={} host={} port={} name={} user={}"
            ),
            env_graph_provider or "unset",
            settings.GRAPH_DATABASE_PROVIDER,
            env_vector_provider,
            CogneeConfig._render_safe_url(graph_url),
            graph_host,
            graph_port,
            settings.GRAPH_DATABASE_NAME or "unset",
            settings.GRAPH_DATABASE_USERNAME or "unset",
        )

    @staticmethod
    def _configure_relational_db() -> None:
        cognee.config.set_relational_db_config(
            {
                "db_host": settings.DB_HOST,
                "db_port": settings.DB_PORT,
                "db_username": settings.DB_USER,
                "db_password": settings.DB_PASSWORD,
                "db_name": settings.DB_NAME,
                "db_path": "",
                "db_provider": settings.DB_PROVIDER,
            }
        )

    @staticmethod
    def _configure_cache() -> None:
        os.environ["CACHING"] = "true"
        os.environ["CACHE_BACKEND"] = "redis"
        if settings.REDIS_HOST:
            os.environ["CACHE_HOST"] = settings.REDIS_HOST
        if settings.REDIS_PORT:
            os.environ["CACHE_PORT"] = str(settings.REDIS_PORT)
        os.environ["CACHE_DB"] = str(settings.AI_COACH_REDIS_CHAT_DB)
        os.environ["COGNEE_CACHE_TTL"] = str(settings.AI_COACH_COGNEE_SESSION_TTL)
        try:
            from cognee.infrastructure.databases.cache import get_cache_engine as cache_module
        except Exception:
            return
        config = getattr(cache_module, "config", None)
        if config is None:
            return
        config.caching = True
        config.cache_host = os.getenv("CACHE_HOST", settings.REDIS_HOST)
        config.cache_port = int(os.getenv("CACHE_PORT", str(settings.REDIS_PORT)))
        config.cache_username = os.getenv("CACHE_USERNAME")
        config.cache_password = os.getenv("CACHE_PASSWORD")
        create_engine = getattr(cache_module, "create_cache_engine", None)
        if create_engine is not None and hasattr(create_engine, "cache_clear"):
            create_engine.cache_clear()

    @classmethod
    def _patch_cognee(cls) -> None:
        """Apply runtime patches to Cognee (ledger, embeddings, API adapter)."""
        try:
            from cognee.infrastructure.databases.vector.embeddings import LiteLLMEmbeddingEngine

            CogneeConfig._patch_litellm_embedding_engine(LiteLLMEmbeddingEngine)  # pyrefly: ignore[bad-argument-type]

        except Exception as exc:  # noqa: BLE001
            logger.debug(f"Cognee patch failed: {exc}")

        cls._patch_cache_adapter()

    @staticmethod
    def _patch_litellm_embedding_engine(engine_cls: type) -> None:
        """Replace embedding method with LiteLLM-powered async function."""

        logger.trace(
            "Configuring LiteLLM embedding",
            model=settings.EMBEDDING_MODEL,
            endpoint=settings.EMBEDDING_ENDPOINT,
        )

        async def patched_embedding(texts: list[str], model: str | None = None, **kwargs: Any) -> Any:
            from litellm import embedding

            return await embedding(  # pyrefly: ignore[async-error]
                model=model or settings.EMBEDDING_MODEL,
                input=texts,
                api_key=settings.LLM_API_KEY,
                base_url=settings.EMBEDDING_ENDPOINT,
                dimensions=kwargs.get("dimensions"),
                user=kwargs.get("user"),
                extra_body=kwargs.get("extra_body"),
                metadata=kwargs.get("metadata"),
                caching=kwargs.get("caching", False),
            )

        engine_cls.embedding = staticmethod(patched_embedding)  # pyrefly: ignore[missing-attribute]

    @staticmethod
    def _patch_cache_adapter() -> None:
        if CogneeConfig._CACHE_PATCHED:
            logger.debug("cognee_cache_patch_skipped reason=already_patched")
            return
        try:
            from cognee.infrastructure.databases.cache.redis.RedisAdapter import RedisAdapter
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"cognee_cache_patch_skipped detail={exc}")
            return

        def _resolve_cache_db() -> int:
            raw_db = os.getenv("CACHE_DB", "")
            try:
                return int(raw_db)
            except (TypeError, ValueError):
                return 0

        def _resolve_cache_ttl() -> int | None:
            raw_ttl = os.getenv("COGNEE_CACHE_TTL", "").strip().lower()
            if raw_ttl in {"", "0", "none", "null", "false"}:
                return None
            try:
                ttl = int(raw_ttl)
                return ttl if ttl > 0 else None
            except (TypeError, ValueError):
                return None

        def patched_init(
            self,
            host: str,
            port: int,
            lock_name: str = "default_lock",
            username: str | None = None,
            password: str | None = None,
            timeout: int = 240,
            blocking_timeout: int = 300,
            connection_timeout: int = 30,
            db: int | None = None,
        ) -> None:
            from cognee.infrastructure.databases.cache.cache_db_interface import CacheDBInterface
            from cognee.infrastructure.databases.exceptions import CacheConnectionError
            from cognee.shared.logging_utils import get_logger
            import redis
            import redis.asyncio as aioredis

            adapter_logger = get_logger("RedisAdapter")
            CacheDBInterface.__init__(self, host, port, lock_name)

            self.host = host
            self.port = port
            self.connection_timeout = connection_timeout
            db_value = db if db is not None else _resolve_cache_db()
            try:
                self.sync_redis = redis.Redis(
                    host=host,
                    port=port,
                    username=username,
                    password=password,
                    db=db_value,
                    socket_connect_timeout=connection_timeout,
                    socket_timeout=connection_timeout,
                )
                self.async_redis = aioredis.Redis(
                    host=host,
                    port=port,
                    username=username,
                    password=password,
                    db=db_value,
                    decode_responses=True,
                    socket_connect_timeout=connection_timeout,
                )
                self.timeout = timeout
                self.blocking_timeout = blocking_timeout
                self._validate_connection()
                adapter_logger.debug(f"Successfully connected to Redis at {host}:{port}/{db_value}")
            except (redis.ConnectionError, redis.TimeoutError) as exc:
                error_msg = f"Failed to connect to Redis at {host}:{port}: {exc}"
                adapter_logger.error(error_msg)
                raise CacheConnectionError(error_msg) from exc
            except Exception as exc:  # noqa: BLE001
                error_msg = f"Unexpected error initializing Redis adapter: {exc}"
                adapter_logger.error(error_msg)
                raise CacheConnectionError(error_msg) from exc
            logger.debug("cognee_cache_configured db={} host={} port={}", db_value, host, port)

        async def patched_add_qa(
            self,
            user_id: str,
            session_id: str,
            question: str,
            context: str,
            answer: str,
            ttl: int | None = 86400,
        ) -> None:
            from datetime import datetime
            import json

            session_key = f"agent_sessions:{user_id}:{session_id}"
            qa_entry = {
                "time": datetime.utcnow().isoformat(),
                "question": question,
                "context": context,
                "answer": answer,
            }
            payload = json.dumps(qa_entry, ensure_ascii=False)
            await self.async_redis.rpush(session_key, payload)
            resolved_ttl = _resolve_cache_ttl()
            if resolved_ttl is not None:
                await self.async_redis.expire(session_key, resolved_ttl)

        RedisAdapter.__init__ = patched_init  # type: ignore[assignment]
        RedisAdapter.add_qa = patched_add_qa  # type: ignore[assignment]
        CogneeConfig._CACHE_PATCHED = True

    @staticmethod
    def _render_safe_url(raw_url: str | None) -> str:
        if not raw_url:
            return "unset"
        try:
            parsed = make_url(raw_url)
            return parsed.render_as_string(hide_password=True)
        except Exception:
            return raw_url

    @staticmethod
    def _extract_url_meta(raw_url: str) -> dict[str, str | int | None]:
        try:
            parsed: URL = make_url(raw_url)
        except Exception:
            return {}
        return {
            "host": parsed.host,
            "port": parsed.port,
            "database": parsed.database,
            "username": parsed.username,
            "password": parsed.password,
        }
