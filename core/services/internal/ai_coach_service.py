# ai_coach_service.py
import base64
from enum import Enum
from typing import Any
from urllib.parse import urljoin

import httpx
from loguru import logger

from core.exceptions import UserServiceError
from core.schemas import CoachAgentRequest, CoachAgentMessageRequest, Program, Subscription, QAResponse
from .api_client import APIClient
from ...enums import CoachAgentMode


class AiCoachService(APIClient):
    def __init__(self, client: httpx.AsyncClient, settings) -> None:
        super().__init__(client, settings)
        self.base_url = settings.AI_COACH_URL
        self.use_default_auth = False

    async def ask_ai(
        self,
        prompt: str,
        *,
        client_id: int,
        language: str | Enum | None = None,
        request_id: str | None = None,
    ) -> QAResponse | None:
        payload = CoachAgentRequest(
            prompt=prompt,
            client_id=client_id,
            language=language.value if isinstance(language, Enum) else language,
            mode=CoachAgentMode.ASK_AI,
            request_id=request_id,
        )
        data = await self._post_ask(payload, request_id=request_id)
        if data is None:
            return None
        return QAResponse.model_validate(data)

    async def create_program(
        self,
        prompt: str,
        *,
        client_id: int,
        language: str | Enum | None = None,
        period: str | None = None,
        workout_days: list[str] | None = None,
        wishes: str | None = None,
        request_id: str | None = None,
    ) -> Program | None:
        payload = CoachAgentRequest(
            prompt=prompt,
            client_id=client_id,
            language=language.value if isinstance(language, Enum) else language,
            mode=CoachAgentMode.PROGRAM,
            period=period,
            workout_days=workout_days,
            wishes=wishes,
            request_id=request_id,
        )
        data = await self._post_ask(payload, request_id=request_id)
        if data is None:
            return None
        return Program.model_validate(data)

    async def update_program(
        self,
        prompt: str,
        *,
        client_id: int,
        language: str | Enum | None = None,
        period: str | None = None,
        workout_days: list[str] | None = None,
        expected_workout: str | None = None,
        feedback: str | None = None,
        wishes: str | None = None,
        request_id: str | None = None,
    ) -> Program | None:
        payload = CoachAgentRequest(
            prompt=prompt,
            client_id=client_id,
            language=language.value if isinstance(language, Enum) else language,
            mode=CoachAgentMode.UPDATE,
            period=period,
            workout_days=workout_days,
            expected_workout=expected_workout,
            feedback=feedback,
            wishes=wishes,
            request_id=request_id,
        )
        data = await self._post_ask(payload, request_id=request_id)
        if data is None:
            return None
        return Program.model_validate(data)

    async def create_subscription(
        self,
        prompt: str,
        *,
        client_id: int,
        language: str | Enum | None = None,
        period: str | None = None,
        workout_days: list[str] | None = None,
        wishes: str | None = None,
        request_id: str | None = None,
    ) -> Subscription | None:
        payload = CoachAgentRequest(
            prompt=prompt,
            client_id=client_id,
            language=language.value if isinstance(language, Enum) else language,
            mode=CoachAgentMode.SUBSCRIPTION,
            period=period,
            workout_days=workout_days,
            wishes=wishes,
            request_id=request_id,
        )
        data = await self._post_ask(payload, request_id=request_id)
        if data is None:
            return None
        return Subscription.model_validate(data)

    async def _post_ask(
        self,
        payload: CoachAgentRequest,
        *,
        request_id: str | None,
    ) -> Any | None:
        url = urljoin(self.base_url, "ask/")
        headers: dict[str, str] = {}
        if request_id:
            headers["X-Request-ID"] = request_id
        logger.debug(f"AI coach ask request_id={request_id} client_id={payload.client_id}")
        status, data = await self._api_request(
            "post",
            url,
            payload.model_dump(exclude_none=True),
            headers=headers or None,
            timeout=self.settings.AI_COACH_TIMEOUT,
        )
        logger.debug(f"AI coach ask response request_id={request_id} HTTP={status}: {data}")
        if status == 200:
            return data
        logger.error(f"AI coach request failed HTTP={status}: {data}")
        return None

    async def save_user_message(self, text: str, client_id: int) -> None:
        url = urljoin(self.base_url, "messages/")
        request = CoachAgentMessageRequest(text=text, client_id=client_id)
        await self._api_request("post", url, request.model_dump())

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
