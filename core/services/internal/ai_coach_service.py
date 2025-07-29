from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

from loguru import logger

from config.app_settings import settings
from core.schemas import Client
from .api_client import APIClient


class AiCoachService(APIClient):
    base_url = settings.AI_COACH_URL

    @classmethod
    async def ask(
        cls,
        prompt: str,
        *,
        client: Client | None = None,
        chat_id: int | None = None,
        language: str | None = None,
    ) -> list[str] | None:
        url = urljoin(cls.base_url, "ask/")
        payload: dict[str, Any] = {
            "prompt": prompt,
            "client": client.model_dump(mode="json") if client else None,
            "chat_id": chat_id,
            "language": language,
        }
        status, data = await cls._api_request("post", url, payload)
        if status == 200 and isinstance(data, list):
            return data
        if status == 200 and isinstance(data, dict):
            return data.get("responses")  # type: ignore[return-value]
        logger.error(f"AI coach request failed HTTP={status}: {data}")
        return None

    @classmethod
    async def save_user_message(cls, text: str, chat_id: int, client_id: int) -> None:
        url = urljoin(cls.base_url, "messages/")
        payload = {"text": text, "chat_id": chat_id, "client_id": client_id}
        await cls._api_request("post", url, payload)

    @classmethod
    async def get_context(cls, chat_id: int, query: str) -> list[str]:
        url = urljoin(cls.base_url, f"context/?chat_id={chat_id}&query={query}")
        status, data = await cls._api_request("get", url)
        if status == 200 and isinstance(data, list):
            return data
        logger.error(f"Failed to fetch context HTTP={status}: {data}")
        return []

    @classmethod
    async def refresh_knowledge(cls) -> None:
        url = urljoin(cls.base_url, "knowledge/refresh/")
        status, _ = await cls._api_request("post", url)
        if status != 200:
            logger.error(f"Knowledge refresh failed HTTP={status}")
