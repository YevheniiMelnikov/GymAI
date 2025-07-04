from __future__ import annotations

from typing import Any

import cognee
from cognee.api.v1.config import config

from config.env_settings import settings
from .coach_service import AICoachService


class CogneeService(AICoachService):
    """Minimal Cognee-based implementation of :class:`AICoachService`."""

    api_url = settings.COGNEE_API_URL
    api_key = settings.COGNEE_API_KEY
    _configured = False

    @classmethod
    def _ensure_config(cls) -> None:
        if cls._configured:
            return
        if cls.api_url:
            config.set_llm_endpoint(cls.api_url)
        if cls.api_key:
            config.set_llm_api_key(cls.api_key)
        cls._configured = True

    @classmethod
    async def coach_request(cls, text: str) -> None:
        cls._ensure_config()
        await cognee.add(text)
        await cognee.cognify()
        await cognee.search(text)

    @classmethod
    async def coach_assign(cls, client: Any) -> None:
        name = getattr(client, "name", None) or str(getattr(client, "id", ""))
        await cls.coach_request(f"New client assigned: {name}")

