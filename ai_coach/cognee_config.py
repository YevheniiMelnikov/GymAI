from __future__ import annotations

import importlib
import logging
import os
import warnings
from pathlib import Path
from typing import Any
from uuid import uuid4

import cognee
from loguru import logger
from sqlalchemy import schema as sa_schema
from sqlalchemy.exc import SAWarning

from config import configure_loguru
from config.app_settings import settings


def _prepare_storage_root() -> Path:
    root = Path(os.environ.get("COGNEE_DATA_ROOT") or ".data_storage").resolve()
    root.mkdir(parents=True, exist_ok=True)
    for sub in (".cognee_system/databases", ".cognee_system/vectordb"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("COGNEE_DATA_ROOT", str(root))
    return root


class CogneeConfig:
    @classmethod
    def apply(cls) -> None:
        _prepare_storage_root()
        cls._configure_llm()
        cls._configure_vector_db()
        cls._configure_relational_db()
        cls._patch_cognee()
        cls._patch_dataset_creation()
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
    def _patch_cognee() -> None:
        """Apply runtime patches to Cognee (ledger, embeddings, API adapter)."""
        try:
            from cognee.infrastructure.databases.vector.embeddings import LiteLLMEmbeddingEngine
            from cognee.modules.data.models.graph_relationship_ledger import GraphRelationshipLedger

            GenericAPIAdapter = None
            for path in [
                "cognee.infrastructure.llm.generic_api.adapter",
                "cognee.infrastructure.llm.generic_llm_api.adapter",
            ]:
                try:
                    mod = importlib.import_module(path)
                    GenericAPIAdapter = getattr(mod, "GenericAPIAdapter", None)
                    if GenericAPIAdapter:
                        break
                except Exception:
                    continue

            CogneeConfig._patch_graph_relationship_ledger(GraphRelationshipLedger)
            CogneeConfig._patch_litellm_embedding_engine(LiteLLMEmbeddingEngine)
            if GenericAPIAdapter:
                CogneeConfig._patch_generic_api_adapter(GenericAPIAdapter)

        except Exception as e:
            logger.debug(f"Cognee patch failed: {e}")

    @staticmethod
    def _patch_graph_relationship_ledger(ledger_cls: type) -> None:
        """Fix default ID generation for graph relationship ledger."""
        ledger_cls.__table__.c.id.default = sa_schema.ColumnDefault(uuid4)

    @staticmethod
    def _patch_litellm_embedding_engine(engine_cls: type) -> None:
        """Replace embedding method with LiteLLM-powered async function."""

        async def patched_embedding(texts: list[str], model: str | None = None, **kwargs: Any) -> Any:
            from litellm import embedding

            return await embedding(
                model=model or settings.LLM_EMBEDDINGS_MODEL,
                input=texts,
                api_key=settings.LLM_API_KEY,
                base_url=settings.LLM_API_URL or None,
                dimensions=kwargs.get("dimensions"),
                user=kwargs.get("user"),
                extra_body=kwargs.get("extra_body"),
                metadata=kwargs.get("metadata"),
                caching=kwargs.get("caching", False),
            )

        engine_cls.embedding = staticmethod(patched_embedding)

    @staticmethod
    def _patch_generic_api_adapter(adapter_cls: type) -> None:
        """Force GenericAPIAdapter to use OpenAI client."""
        original_create = getattr(adapter_cls, "create_client", None)

        async def _create_client(*args: Any, **kwargs: Any) -> Any:
            try:
                from openai import AsyncOpenAI

                return AsyncOpenAI(api_key=settings.LLM_API_KEY, base_url=settings.LLM_API_URL or None)
            except Exception:
                if callable(original_create):
                    result = original_create(*args, **kwargs)
                    if hasattr(result, "__await__"):
                        return await result
                    return result
                raise

        setattr(adapter_cls, "create_client", staticmethod(_create_client))

    @classmethod
    def _patch_dataset_creation(cls) -> None:
        """Ensure create_authorized_dataset is properly loaded in Cognee."""
        try:
            m_lcd = importlib.import_module("cognee.modules.data.methods.load_or_create_datasets")
            cad_obj = m_lcd.__dict__.get("create_authorized_dataset")
            if not callable(cad_obj):
                m_cad = importlib.import_module("cognee.modules.data.methods.create_authorized_dataset")
                func = getattr(m_cad, "create_authorized_dataset", None)
                if callable(func):
                    m_lcd.__dict__["create_authorized_dataset"] = func
        except Exception as e:
            logger.debug(f"Patch dataset creation failed: {e}")

    @classmethod
    def _patch_rbac_and_dataset_resolvers(cls) -> None:
        """Harden RBAC and dataset resolvers to avoid errors on missing IDs."""
        try:
            m_all = importlib.import_module("cognee.modules.users.permissions.methods.get_all_user_permission_datasets")
            orig_all = getattr(m_all, "get_all_user_permission_datasets", None)
            m_auth = importlib.import_module("cognee.modules.data.methods.get_authorized_existing_datasets")
            orig_auth = getattr(m_auth, "get_authorized_existing_datasets", None)

            if callable(orig_all):

                async def safe_all(user: Any, permission_type: str):
                    try:
                        res = await orig_all(user, permission_type)
                    except Exception:
                        return []
                    return [x for x in (res or []) if getattr(x, "id", None)]

                setattr(m_all, "get_all_user_permission_datasets", safe_all)

            if callable(orig_auth):

                async def safe_auth(datasets: list[Any], permission_type: str, user: Any):
                    try:
                        res = await orig_auth(datasets, permission_type, user)
                    except Exception:
                        return []
                    return [x for x in (res or []) if getattr(x, "id", None)]

                setattr(m_auth, "get_authorized_existing_datasets", safe_auth)

            for mod_path in [
                "cognee.modules.data.methods.get_authorized_existing_datasets",
                "cognee.modules.users.permissions.methods.get_specific_user_permission_datasets",
                "cognee.modules.pipelines.layers.resolve_authorized_user_datasets",
                "cognee.modules.data.methods.get_authorized_dataset_by_name",
                "cognee.modules.pipelines.layers.resolve_authorized_user_dataset",
            ]:
                mod = importlib.import_module(mod_path)
                if "get_all_user_permission_datasets" in mod.__dict__ and callable(orig_all):
                    mod.__dict__["get_all_user_permission_datasets"] = m_all.get_all_user_permission_datasets
                if "get_authorized_existing_datasets" in mod.__dict__ and callable(orig_auth):
                    mod.__dict__["get_authorized_existing_datasets"] = m_auth.get_authorized_existing_datasets
        except Exception as e:
            logger.debug(f"Patch RBAC resolvers failed: {e}")
