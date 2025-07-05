from __future__ import annotations

from typing import Optional

from loguru import logger

import cognee
from cognee.api.v1.config import config

from config.env_settings import settings
from ..knowledge_loader import KnowledgeLoader
from .base import BaseAICoachService
from core.schemas import Client


async def init_cognee_memory() -> None:
    """Run Cognee migrations and ensure DB connectivity."""
    await cognee.alembic("upgrade", "head")
    try:
        await cognee.search("ping")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Cognee connection failed: %s", exc)
        raise


class CogneeService(BaseAICoachService):
    """Minimal Cognee-based implementation of :class:`BaseAIService`."""

    api_url = settings.COGNEE_API_URL
    api_key = settings.COGNEE_API_KEY
    model = settings.COGNEE_MODEL  # TODO: IMPLEMENT KNOWLEDGE BASE
    _configured = False
    _loader: Optional[KnowledgeLoader] = None

    @classmethod
    def set_loader(cls, loader: KnowledgeLoader) -> None:
        """Register a loader instance for fetching external knowledge."""
        cls._loader = loader

    @classmethod
    async def init_loader(cls, loader: KnowledgeLoader) -> None:
        """Register ``loader`` and load its data.

        This should be invoked once during startup, e.g. from ``bot/main.py``.
        """
        cls.set_loader(loader)
        await cls.load_external_knowledge()

    @classmethod
    def _ensure_config(cls) -> None:
        """Ensure Cognee is configured."""
        if cls._configured:
            return
        if cls.api_url:
            config.set_llm_endpoint(cls.api_url)
        if cls.api_key:
            config.set_llm_api_key(cls.api_key)
        if cls.model:
            config.set_llm_model(cls.model)
        config.set_vector_db_provider(settings.VECTORDATABASE_PROVIDER)
        config.set_vector_db_url(settings.VECTORDATABASE_URL)
        config.set_graph_database_provider(settings.GRAPH_DATABASE_PROVIDER)
        cls._configured = True

    @staticmethod
    def _extract_client_data(client: Client) -> str:
        """Extract client data from the client object."""
        return ""

    @staticmethod
    def _make_initial_prompt(client_data: str) -> str:
        """Create the initial prompt based on the client data."""
        return ""  # TODO IMPLEMENT DB (CHAT MEMORY)

    @classmethod
    async def coach_request(cls, text: str) -> None:
        cls._ensure_config()
        await cognee.add(text)
        await cognee.cognify()
        await cognee.search(text)

    @classmethod
    async def load_external_knowledge(cls) -> None:
        cls._ensure_config()
        if cls._loader is None:
            return
        await cls._loader.load()
        await cls.update_knowledge_base()

    @classmethod
    async def update_knowledge_base(cls) -> None:
        cls._ensure_config()
        await cognee.cognify()

    @classmethod
    async def coach_assign(cls, client: Client) -> None:
        client_data = cls._extract_client_data(client)
        prompt = cls._make_initial_prompt(client_data)
        await cls.coach_request(prompt)

    @classmethod
    async def save_user_message(cls, text: str, chat_id: int, client_id: int) -> None:
        """Persist user message in Cognee memory."""
        if not text.strip():
            return
        cls._ensure_config()
        await cognee.memory.add(text, metadata={"chat_id": chat_id, "client_id": client_id})
        await cognee.cognify()

    @classmethod
    async def get_context(cls, chat_id: int, query: str) -> list:
        """Retrieve context for ``query`` from chat history."""
        cls._ensure_config()
        return await cognee.memory.search(query, filter_metadata={"chat_id": chat_id}, top_k=5)
