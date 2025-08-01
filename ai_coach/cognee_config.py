from __future__ import annotations

import logging
import os
import warnings
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Type
from urllib.parse import urlparse
from uuid import uuid4

import cognee
from cognee.base_config import get_base_config
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
            from cognee.infrastructure.files.storage.LocalFileStorage import LocalFileStorage, get_parsed_path
            from cognee.infrastructure.files.utils import open_data_file as orig_open_data_file
            from cognee.infrastructure.llm.generic_llm_api.adapter import GenericAPIAdapter
            from cognee.modules.data.models.graph_relationship_ledger import GraphRelationshipLedger
            import cognee.infrastructure.files.utils as file_utils

            CogneeConfig._patch_graph_relationship_ledger(GraphRelationshipLedger)
            CogneeConfig._patch_litellm_embedding_engine(LiteLLMEmbeddingEngine)
            CogneeConfig._patch_generic_api_adapter(GenericAPIAdapter)
            CogneeConfig._patch_open_data_file(file_utils, orig_open_data_file, LocalFileStorage)
            CogneeConfig._patch_local_file_storage(LocalFileStorage, get_parsed_path)

        except Exception as e:
            logger.debug(f"Cognee patch failed: {e}")

    @staticmethod
    def _patch_graph_relationship_ledger(ledger_cls: Type) -> None:
        """Patch GraphRelationshipLedger to use UUID as default ID."""
        ledger_cls.__table__.c.id.default = sa_schema.ColumnDefault(uuid4)

    @staticmethod
    def _patch_litellm_embedding_engine(engine_cls: Type) -> None:
        """Patch LiteLLMEmbeddingEngine with custom embedding function."""

        async def patched_embedding(texts: list[str], model: str | None = None, **kwargs: Any) -> Any:
            from litellm import embedding

            return await embedding(
                texts,
                model=settings.EMBEDDING_MODEL,
                api_key=settings.OPENAI_API_KEY,
                base_url=settings.OPENAI_BASE_URL,
            )

        engine_cls.get_embedding_fn = staticmethod(patched_embedding)

    @staticmethod
    def _patch_generic_api_adapter(adapter_cls: Type) -> None:
        """Patch GenericAPIAdapter to add custom HTTP headers."""
        orig_init = adapter_cls.__init__

        def new_init(self: Any, *args: Any, **kwargs: Any) -> None:
            orig_init(self, *args, **kwargs)
            target = getattr(getattr(self, "aclient", None), "client", None) or getattr(self, "aclient", None)
            if isinstance(target, AsyncOpenAI):
                target.default_headers.update({"HTTP-Referer": "https://gymbot.local", "X-Title": "GymBot"})

        adapter_cls.__init__ = new_init

    @staticmethod
    def _patch_open_data_file(file_utils: Any, orig_open: Any, local_storage_cls: Type) -> None:
        """Patch open_data_file to handle Windows paths and file URIs robustly."""

        @asynccontextmanager
        async def fixed_open_data_file(
            file_path: str, mode: str = "rb", encoding: str | None = None, **kwargs: Any
        ) -> AsyncIterator[Any]:
            if ":" in file_path and "\\" in file_path:
                file_path = "file://" + file_path.replace("\\", "/")

            if file_path.startswith("file://"):
                parsed = urlparse(file_path)
                path_str = (parsed.path or parsed.netloc).replace("\\", "/").lstrip("/")
                if len(path_str) > 1 and path_str[1] == ":":  # Handle Windows drive letters
                    path_str = path_str[1:]

                abs_path = Path(path_str).resolve()
                if not abs_path.exists():
                    abs_path = Path(get_base_config().data_root_directory) / abs_path.name

                storage = local_storage_cls(str(abs_path.parent))
                with storage.open(abs_path.name, mode=mode, encoding=encoding, **kwargs) as f:
                    yield f
            else:
                async with orig_open(file_path, mode=mode, encoding=encoding, **kwargs) as f:
                    yield f

        file_utils.open_data_file = fixed_open_data_file

    @staticmethod
    def _patch_local_file_storage(storage_cls: Type, get_parsed_path_fn: Any) -> None:
        """Patch LocalFileStorage.open to ensure the storage directory exists."""
        orig_open = storage_cls.open

        def ensure_open(self: Any, file_path: str, mode: str = "rb", *args: Any, **kwargs: Any) -> Any:
            path = Path(get_parsed_path_fn(self.storage_path)).resolve()
            path.mkdir(parents=True, exist_ok=True)
            self.storage_path = str(path)
            return orig_open(self, file_path, mode=mode, *args, **kwargs)

        storage_cls.open = ensure_open
