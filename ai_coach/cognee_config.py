from __future__ import annotations

import logging
import os
import warnings
import importlib
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


def _prepare_storage_root() -> Path:
    storage_root = Path(os.environ.get("COGNEE_DATA_ROOT") or ".data_storage").resolve()
    storage_root.mkdir(parents=True, exist_ok=True)
    for sub in (".cognee_system/databases", ".cognee_system/vectordb"):
        (storage_root / sub).mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("COGNEE_DATA_ROOT", str(storage_root))
    return storage_root


class CogneeConfig:
    """Configures Cognee and applies patches."""

    @classmethod
    def apply(cls) -> None:
        cls._configure_logging()
        _prepare_storage_root()
        cls._configure_llm()
        cls._configure_vector_db()
        cls._configure_data_processing()
        cls._configure_relational_db()
        cls._patch_cognee()
        cls._patch_rbac_and_dataset_resolvers()

    @staticmethod
    def _configure_llm() -> None:
        cognee.config.set_llm_provider(settings.LLM_PROVIDER)
        cognee.config.set_llm_model(settings.LLM_MODEL)
        cognee.config.set_llm_api_key(settings.LLM_API_KEY)
        cognee.config.set_llm_endpoint(settings.LLM_API_URL)

    @staticmethod
    def _configure_vector_db() -> None:
        cognee.config.set_vector_db_provider(settings.VECTORDATABASE_PROVIDER)
        cognee.config.set_vector_db_url(settings.VECTORDATABASE_URL)

    @staticmethod
    def _configure_data_processing() -> None:
        root = _prepare_storage_root()
        cognee.config.data_root_directory(str(root))
        cognee.config.set_graph_database_provider(settings.GRAPH_DATABASE_PROVIDER)

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
    def _configure_logging() -> None:
        warnings.filterwarnings("ignore", category=SAWarning)
        logging.getLogger("langfuse").setLevel(logging.ERROR)
        logging.getLogger("cognee").setLevel(logging.INFO)
        logging.getLogger("GraphCompletionRetriever").setLevel(logging.ERROR)
        configure_loguru()
        logger.level("COGNEE", no=45, color="<cyan>")

    @staticmethod
    def _patch_cognee() -> None:
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
        ledger_cls.__table__.c.id.default = sa_schema.ColumnDefault(uuid4)  # pyrefly: ignore[bad-argument-type]

    @staticmethod
    def _patch_litellm_embedding_engine(engine_cls: Type) -> None:
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
        orig_init = adapter_cls.__init__

        def new_init(self: Any, *args: Any, **kwargs: Any) -> None:
            orig_init(self, *args, **kwargs)
            target = getattr(getattr(self, "aclient", None), "client", None) or getattr(self, "aclient", None)
            if isinstance(target, AsyncOpenAI):
                target.default_headers.update({"HTTP-Referer": "https://gymbot.local", "X-Title": "GymBot"})

        adapter_cls.__init__ = new_init  # pyrefly: ignore[implicitly-defined-attribute]

    # ---- RBAC / dataset resolver patches (defensive wrappers for 0.2.x quirks) ----

    @staticmethod
    def _rewire_symbol(module_path: str, symbol_name: str, new_func: Any) -> None:
        mod = importlib.import_module(module_path)
        old = getattr(mod, symbol_name)
        setattr(mod, symbol_name, new_func)
        logger.debug("[PATCH] %s.%s -> %s (was %s)", module_path, symbol_name, new_func, old)

    @classmethod
    def _patch_rbac_and_dataset_resolvers(cls) -> None:
        try:
            pass  # type: ignore
        except Exception as e:
            logger.debug(f"RBAC patch import failed: {e}")
            return

        try:
            from cognee.modules.data.methods.get_authorized_existing_datasets import (  # type: ignore
                get_all_user_permission_datasets,
            )

            async def _wrapped_get_all_user_permission_datasets(*args, **kwargs):
                result = await get_all_user_permission_datasets(*args, **kwargs)
                normalized = []
                for r in result:
                    if isinstance(r, dict) and "id" in r:
                        normalized.append(r)
                    elif hasattr(r, "id"):
                        normalized.append({"id": str(r.id)})
                    else:
                        logger.warning("Unrecognized permission record: %s", r)
                return normalized

            cls._rewire_symbol(
                "cognee.modules.data.methods.get_authorized_existing_datasets",
                "get_all_user_permission_datasets",
                _wrapped_get_all_user_permission_datasets,
            )
        except Exception as e:
            logger.debug(f"Patch get_all_user_permission_datasets failed: {e}")

        try:
            from cognee.modules.data.methods.get_authorized_existing_datasets import (  # type: ignore
                get_specific_user_permission_datasets,
            )

            async def _wrapped_get_specific_user_permission_datasets(*args, **kwargs):
                try:
                    return await get_specific_user_permission_datasets(*args, **kwargs)
                except Exception as e:
                    logger.warning("get_specific_user_permission_datasets fallback: %s", e)
                    return []

            cls._rewire_symbol(
                "cognee.modules.data.methods.get_authorized_existing_datasets",
                "get_specific_user_permission_datasets",
                _wrapped_get_specific_user_permission_datasets,
            )
        except Exception as e:
            logger.debug(f"Patch get_specific_user_permission_datasets failed: {e}")

        try:
            from cognee.modules.data.methods.get_authorized_dataset_by_name import (  # type: ignore
                get_authorized_existing_datasets,
            )

            async def _wrapped_get_authorized_existing_datasets(*args, **kwargs):
                try:
                    return await get_authorized_existing_datasets(*args, **kwargs)
                except Exception as e:
                    logger.warning("get_authorized_existing_datasets fallback: %s", e)
                    return []

            cls._rewire_symbol(
                "cognee.modules.data.methods.get_authorized_dataset_by_name",
                "get_authorized_existing_datasets",
                _wrapped_get_authorized_existing_datasets,
            )
            cls._rewire_symbol(
                "cognee.modules.pipelines.layers.resolve_authorized_user_datasets",
                "get_authorized_existing_datasets",
                _wrapped_get_authorized_existing_datasets,
            )
        except Exception as e:
            logger.debug(f"Patch data.get_authorized_existing_datasets failed: {e}")

        try:
            from cognee.modules.data.methods.get_authorized_dataset import (  # type: ignore
                get_authorized_dataset,
            )

            async def _wrapped_get_authorized_dataset(*args, **kwargs):
                try:
                    return await get_authorized_dataset(*args, **kwargs)
                except Exception as e:
                    logger.warning("get_authorized_dataset fallback: %s", e)
                    return None

            cls._rewire_symbol(
                "cognee.modules.pipelines.layers.resolve_authorized_user_dataset",
                "get_authorized_dataset",
                _wrapped_get_authorized_dataset,
            )
        except Exception as e:
            logger.debug(f"Patch data.get_authorized_dataset failed: {e}")
