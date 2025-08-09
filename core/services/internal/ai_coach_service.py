from __future__ import annotations

import base64
from enum import Enum
from urllib.parse import urljoin

from loguru import logger

from config.app_settings import settings
from core.exceptions import UserServiceError
from core.schemas import AiCoachAskRequest, AiCoachMessageRequest
from .api_client import APIClient


class AiCoachService(APIClient):
    base_url = settings.AI_COACH_URL
    use_default_auth = False

    @classmethod
    async def ask(
        cls,
        prompt: str,
        *,
        client_id: int,
        language: str | None = None,
    ) -> list[str] | None:
        url = urljoin(cls.base_url, "ask/")
        request = AiCoachAskRequest(
            prompt=prompt,
            client_id=client_id,
            language=language.value if isinstance(language, Enum) else language,
        )
        logger.debug(f"AI coach ask for client_id={client_id}")
        status, data = await cls._api_request(
            "post", url, request.model_dump(), timeout=settings.AI_COACH_TIMEOUT
        )
        logger.debug(f"AI coach ask response HTTP={status}: {data}")
        if status == 200 and isinstance(data, list):
            return data
        if status == 200 and isinstance(data, dict):
            return data.get("responses")  # type: ignore[return-value]
        logger.error(f"AI coach request failed HTTP={status}: {data}")
        return None

    @classmethod
    async def save_user_message(cls, text: str, client_id: int) -> None:
        url = urljoin(cls.base_url, "messages/")
        request = AiCoachMessageRequest(text=text, client_id=client_id)
        await cls._api_request("post", url, request.model_dump())

    @classmethod
    async def get_client_knowledge(cls, client_id: int, query: str) -> dict[str, list[str]]:
        url = urljoin(cls.base_url, f"knowledge/?client_id={client_id}&query={query}")
        status, data = await cls._api_request("get", url)
        if status == 200 and isinstance(data, dict):
            msgs = data.get("messages")
            prompts = data.get("prompts")
            if isinstance(msgs, list) and isinstance(prompts, list):
                return {"messages": msgs, "prompts": prompts}
        logger.error(f"Failed to fetch knowledge HTTP={status}: {data}")
        return {"messages": [], "prompts": []}

    @classmethod
    async def refresh_knowledge(cls) -> None:
        url = urljoin(cls.base_url, "knowledge/refresh/")
        token = base64.b64encode(
            f"{settings.AI_COACH_REFRESH_USER}:{settings.AI_COACH_REFRESH_PASSWORD}".encode()
        ).decode()
        headers = {"Authorization": f"Basic {token}"}
        try:
            status, _ = await cls._api_request(
                "post", url, headers=headers, timeout=settings.AI_COACH_TIMEOUT
            )
        except UserServiceError as exc:
            logger.error(f"Knowledge refresh request failed: {exc}")
            raise
        if status != 200:
            logger.error(f"Knowledge refresh failed HTTP={status}")
            raise UserServiceError(f"Knowledge refresh failed HTTP={status}")
