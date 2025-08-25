from __future__ import annotations

import logging
import os
import warnings
from pathlib import Path
from typing import Any, Type
from uuid import uuid4

import cognee
from loguru import logger
from openai import AsyncOpenAI
from sqlalchemy import schema as sa_schema
from sqlalchemy.exc import SAWarning

from config import configure_loguru
from config.app_settings import settings


class CogneeConfig:
    """Configures the Cognee environment, including logging, databases, LLMs, and custom patches."""

    @classmethod
    def apply(cls) -> None:
        """Apply all configurations in sequence."""
        cls._configure_logging()
        cls._patch_cognee()
        cls._configure_llm()
        cls._configure_vector_db()
        cls._configure_data_processing()
        cls._configure_relational_db()

    @staticmethod
    def _configure_llm() -> None:
        """Configure Language Model (LLM) provider and settings."""
        cognee.config.set_llm_provider(settings.LLM_PROVIDER)
        cognee.config.set_llm_model(settings.LLM_MODEL)
        cognee.config.set_llm_api_key(settings.LLM_API_KEY)
        cognee.config.set_llm_endpoint(settings.LLM_API_URL)

    @staticmethod
    def _configure_vector_db() -> None:
        """Configure Vector Database provider and URL."""
        cognee.config.set_vector_db_provider(settings.VECTORDATABASE_PROVIDER)
        cognee.config.set_vector_db_url(settings.VECTORDATABASE_URL)

    @staticmethod
    def _configure_data_processing() -> None:
        """Configure Graph Database provider, storage root."""
        storage_root = Path(".data_storage").resolve()
        storage_root.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("COGNEE_DATA_ROOT", str(storage_root))

        cognee.config.data_root_directory(str(storage_root))
        cognee.config.set_graph_database_provider(settings.GRAPH_DATABASE_PROVIDER)

    @staticmethod
    def _configure_relational_db() -> None:
        """Configure Relational Database connection details."""
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
    def _configure_logging() -> None:
        """Set up logging levels, filters, and custom Loguru configuration."""
        warnings.filterwarnings("ignore", category=SAWarning)
        logging.getLogger("langfuse").setLevel(logging.ERROR)
        logging.getLogger("cognee").setLevel(logging.INFO)
        logging.getLogger("GraphCompletionRetriever").setLevel(logging.ERROR)

        configure_loguru()
        logger.level("COGNEE", no=45, color="<cyan>")

    @staticmethod
    def _patch_cognee() -> None:
        """Apply custom patches to Cognee modules."""
        try:
            from cognee.infrastructure.databases.vector.embeddings import LiteLLMEmbeddingEngine
            from cognee.modules.data.models.graph_relationship_ledger import GraphRelationshipLedger
            from cognee.infrastructure.llm.generic_llm_api.adapter import GenericAPIAdapter

            CogneeConfig._patch_graph_relationship_ledger(GraphRelationshipLedger)
            CogneeConfig._patch_litellm_embedding_engine(LiteLLMEmbeddingEngine)  # pyrefly: ignore[bad-argument-type]
            CogneeConfig._patch_generic_api_adapter(GenericAPIAdapter)

        except Exception as e:
            logger.debug(f"Cognee patch failed: {e}")

    @staticmethod
    def _patch_graph_relationship_ledger(ledger_cls: Type) -> None:
        """Patch GraphRelationshipLedger to use UUID as default ID."""
        ledger_cls.__table__.c.id.default = sa_schema.ColumnDefault(uuid4)  # pyrefly: ignore[bad-argument-type]

    @staticmethod
    def _patch_litellm_embedding_engine(engine_cls: Type) -> None:
        """Patch LiteLLMEmbeddingEngine with custom embedding function."""

        async def patched_embedding(texts: list[str], model: str | None = None, **kwargs: Any) -> Any:
            from litellm import embedding

            return await embedding(  # pyrefly: ignore[async-error]
                texts,
                model=settings.EMBEDDING_MODEL,
                api_key=settings.EMBEDDING_API_KEY,
                base_url=settings.OPENAI_BASE_URL,
            )

        engine_cls.get_embedding_fn = staticmethod(patched_embedding)  # pyrefly: ignore[implicitly-defined-attribute]

    @staticmethod
    def _patch_generic_api_adapter(adapter_cls: Type) -> None:
        """Patch GenericAPIAdapter to add custom HTTP headers."""
        orig_init = adapter_cls.__init__

        def new_init(self: Any, *args: Any, **kwargs: Any) -> None:
            orig_init(self, *args, **kwargs)
            target = getattr(getattr(self, "aclient", None), "client", None) or getattr(self, "aclient", None)
            if isinstance(target, AsyncOpenAI):
                target.default_headers.update({"HTTP-Referer": "https://gymbot.local", "X-Title": "GymBot"})

        adapter_cls.__init__ = new_init  # pyrefly: ignore[implicitly-defined-attribute]
