from __future__ import annotations

from typing import Any, Optional

import cognee
from cognee.api.v1.config import config

from config.env_settings import settings
from .knowledge_loader import KnowledgeLoader
from .base import BaseAICoachService
from core.schemas import Client


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
