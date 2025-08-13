from __future__ import annotations

import base64
from enum import Enum
from urllib.parse import urljoin

import httpx
from loguru import logger

from core.exceptions import UserServiceError
from core.schemas import AiCoachAskRequest, AiCoachMessageRequest
from .api_client import APIClient


class AiCoachService(APIClient):
    def __init__(self, client: httpx.AsyncClient, settings) -> None:
        super().__init__(client, settings)
        self.base_url = settings.AI_COACH_URL
        self.use_default_auth = False

    async def ask(
        self,
        prompt: str,
        *,
        client_id: int,
        language: str | None = None,
        request_id: str | None = None,
    ) -> list[str] | None:
        url = urljoin(self.base_url, "ask/")
        request = AiCoachAskRequest(
            prompt=prompt,
            client_id=client_id,
            language=language.value if isinstance(language, Enum) else language,
            request_id=request_id,
        )
        headers = {"X-Request-ID": request_id} if request_id else None
        logger.debug("AI coach ask request_id={} client_id={}", request_id, client_id)
        status, data = await self._api_request(
            "post", url, request.model_dump(), headers=headers, timeout=self.settings.AI_COACH_TIMEOUT
        )
        logger.debug(
            "AI coach ask response request_id={} HTTP={}: {}",
            request_id,
            status,
            data,
        )
        if status == 200 and isinstance(data, list):
            return data
        if status == 200 and isinstance(data, dict):
            return data.get("responses")  # type: ignore[return-value]
        logger.error(f"AI coach request failed HTTP={status}: {data}")
        return None

    async def save_user_message(self, text: str, client_id: int) -> None:
        url = urljoin(self.base_url, "messages/")
        request = AiCoachMessageRequest(text=text, client_id=client_id)
        await self._api_request("post", url, request.model_dump())

    async def get_client_context(self, client_id: int, query: str) -> dict[str, list[str]]:
        url = urljoin(self.base_url, f"knowledge/?client_id={client_id}&query={query}")
        status, data = await self._api_request("get", url)
        if status == 200 and isinstance(data, dict):
            msgs = data.get("messages")
            if isinstance(msgs, list):
                return {"messages": msgs}
        logger.error(f"Failed to fetch knowledge HTTP={status}: {data}")
        return {"messages": []}

    async def refresh_knowledge(self) -> None:
        url = urljoin(self.base_url, "knowledge/refresh/")
        token = base64.b64encode(
            f"{self.settings.AI_COACH_REFRESH_USER}:{self.settings.AI_COACH_REFRESH_PASSWORD}".encode()
        ).decode()
        headers = {"Authorization": f"Basic {token}"}
        try:
            status, _ = await self._api_request("post", url, headers=headers, timeout=self.settings.AI_COACH_TIMEOUT)
        except UserServiceError as exc:
            logger.error(f"Knowledge refresh request failed: {exc}")
            raise
        if status != 200:
            logger.error(f"Knowledge refresh failed HTTP={status}")
            raise UserServiceError(f"Knowledge refresh failed HTTP={status}")

    async def health(self, timeout: float = 3.0) -> bool:
        url = urljoin(self.base_url, "health/")
        try:
            status, _ = await self._api_request("get", url, timeout=int(timeout))
        except UserServiceError as exc:
            logger.debug(f"AI coach health check failed: {exc}")
            return False
        return status == 200
