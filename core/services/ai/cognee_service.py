from __future__ import annotations

from typing import Any

import cognee
from cognee.api.v1.config import config

from config.env_settings import settings
from .coach_service import AIService
from core.schemas import Client



class CogneeService(AIService):
    """Minimal Cognee-based implementation of :class:`AICoachService`."""

    api_url = settings.COGNEE_API_URL
    api_key = settings.COGNEE_API_KEY
    model = settings.COGNEE_MODEL  # TODO: IMPLEMENT KNOWLEDGE BASE
    _configured = False

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
    async def coach_assign(cls, client: Client) -> None:
        client_data = cls._extract_client_data(client)
        prompt = cls._make_initial_prompt(client_data)
        await cls.coach_request(prompt)
