# ai_coach_service.py
import asyncio
import base64
import json
from enum import Enum
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from loguru import logger
from pydantic import ValidationError

from ai_coach.schemas import AICoachRequest
from ai_coach.types import CoachMode
from core.exceptions import UserServiceError
from core.schemas import Program, Subscription
from core.schemas import QAResponse
from .api_client import APIClient, APIClientHTTPError, APIClientTransportError
from ...enums import WorkoutPlanType, WorkoutType


class AiCoachService(APIClient):
    def __init__(self, client: httpx.AsyncClient, settings) -> None:
        super().__init__(client, settings)
        self.base_url = settings.AI_COACH_URL
        self.use_default_auth = False
        parsed = urlsplit(self.base_url)
        logger.info(
            "AI coach service configured "
            f"base_url={self.base_url} scheme={parsed.scheme} host={parsed.hostname} port={parsed.port}"
        )

    async def ask_ai(
        self,
        prompt: str,
        *,
        client_id: int,
        language: str | Enum | None = None,
        request_id: str | None = None,
        attachments: list[dict[str, str]] | None = None,
    ) -> QAResponse | None:
        payload = AICoachRequest(
            prompt=prompt,
            client_id=client_id,
            language=language.value if isinstance(language, Enum) else language,
            mode=CoachMode.ask_ai,
            request_id=request_id,
            attachments=attachments,
        )
        data = await self._post_ask(payload, request_id=request_id)
        if data is None:
            return None
        return self._build_qa_response(
            data,
            client_id=client_id,
            request_id=request_id,
        )

    async def ask(
        self,
        prompt: str,
        *,
        client_id: int,
        language: str | Enum | None = None,
        request_id: str | None = None,
        use_agent_header: bool = False,
        attachments: list[dict[str, str]] | None = None,
    ) -> QAResponse | None:
        payload = AICoachRequest(
            prompt=prompt,
            client_id=client_id,
            language=language.value if isinstance(language, Enum) else language,
            mode=CoachMode.ask_ai,
            request_id=request_id,
            attachments=attachments,
        )
        headers = {"X-Agent": "pydanticai"} if use_agent_header else None
        data = await self._post_ask(payload, request_id=request_id, extra_headers=headers)
        if data is None:
            return None
        return self._build_qa_response(
            data,
            client_id=client_id,
            request_id=request_id,
        )

    async def create_workout_plan(
        self,
        plan_type: WorkoutPlanType,
        *,
        client_id: int,
        language: str | Enum | None = None,
        period: str | None = None,
        workout_days: list[str] | None = None,
        wishes: str | None = None,
        workout_type: WorkoutType | None = None,
        request_id: str | None = None,
    ) -> Program | Subscription | None:
        payload = AICoachRequest(
            prompt=None,
            client_id=client_id,
            language=language.value if isinstance(language, Enum) else language,
            mode=(CoachMode.program if plan_type is WorkoutPlanType.PROGRAM else CoachMode.subscription),
            period=period,
            workout_days=workout_days,
            wishes=wishes,
            workout_type=workout_type,
            plan_type=plan_type,
            request_id=request_id,
        )
        data = await self._post_ask(payload, request_id=request_id)
        if data is None:
            return None
        if plan_type is WorkoutPlanType.PROGRAM:
            return self._validate_program_response(
                data,
                client_id=client_id,
                request_id=request_id,
                context="create",
            )
        return Subscription.model_validate(data)

    async def update_workout_plan(
        self,
        plan_type: WorkoutPlanType,
        *,
        client_id: int,
        language: str | Enum | None = None,
        period: str | None = None,
        workout_days: list[str] | None = None,
        expected_workout: str | None = None,
        feedback: str | None = None,
        wishes: str | None = None,
        workout_type: WorkoutType | None = None,
        request_id: str | None = None,
    ) -> Program | Subscription | None:
        payload = AICoachRequest(
            prompt=None,
            client_id=client_id,
            language=language.value if isinstance(language, Enum) else language,
            mode=CoachMode.update,
            period=period,
            workout_days=workout_days,
            expected_workout=expected_workout,
            feedback=feedback,
            wishes=wishes,
            workout_type=workout_type,
            plan_type=plan_type,
            request_id=request_id,
        )
        data = await self._post_ask(payload, request_id=request_id)
        if data is None:
            return None
        if plan_type is WorkoutPlanType.PROGRAM:
            return self._validate_program_response(
                data,
                client_id=client_id,
                request_id=request_id,
                context="update",
            )
        return Subscription.model_validate(data)

    def _validate_program_response(
        self,
        data: Any,
        *,
        client_id: int,
        request_id: str | None,
        context: str,
    ) -> Program:
        if isinstance(data, Program):
            return data
        try:
            return Program.model_validate(data)
        except (ValidationError, TypeError) as exc:
            logger.warning(
                f"ai_coach_invalid_program_payload client_id={client_id} request_id={request_id} "
                f"context={context} error={exc}"
            )
            raise UserServiceError("AI coach returned an invalid program payload") from exc

    async def _post_ask(
        self,
        payload: AICoachRequest,
        *,
        request_id: str | None,
        extra_headers: dict[str, str] | None = None,
    ) -> Any | None:
        headers: dict[str, str] = {}
        if request_id:
            headers["X-Request-ID"] = request_id
        if extra_headers:
            headers.update(extra_headers)
        payload_dict: dict[str, Any] = payload.model_dump(exclude_none=True)
        logger.debug(
            f"ai_coach.ask POST client_id={payload.client_id} mode={payload.mode.value} "
            f"language={payload_dict.get('language')}"
        )
        logger.debug(f"AI coach ask request_id={request_id} client_id={payload.client_id}")
        ping_path = "internal/debug/ping"
        ping_url = urljoin(self.base_url, ping_path)
        # Retry readiness ping with exponential backoff
        attempts = 5
        delay = 0.5
        for attempt in range(1, attempts + 1):
            try:
                async with httpx.AsyncClient(base_url=self.base_url, timeout=self.settings.AI_COACH_TIMEOUT) as client:
                    ping_status, _ = await self._api_request(
                        "get",
                        ping_path,
                        timeout=5,
                        client=client,
                    )
                logger.debug(f"AI coach ping request_id={request_id} status={ping_status} url={ping_url}")
                break
            except (APIClientTransportError, APIClientHTTPError) as exc:
                if attempt >= attempts:
                    logger.warning(f"ai_coach.ping.giveup request_id={request_id} attempts={attempts} error={exc}")
                    # Continue to main request; POST will also have its own retries
                    break
                logger.info(f"ai_coach.ping.retry attempt={attempt} delay={delay:.2f}s error={exc} url={ping_url}")
                await asyncio.sleep(delay)
                delay = min(delay * 2.0, 4.5)

        # Main POST /ask with retries and per-call client
        attempts = 5
        delay = 0.5
        last_exc: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                async with httpx.AsyncClient(base_url=self.base_url, timeout=self.settings.AI_COACH_TIMEOUT) as client:
                    status, data = await self._api_request(
                        "post",
                        "ask/",
                        payload_dict,
                        headers=headers or None,
                        timeout=self.settings.AI_COACH_TIMEOUT,
                        client=client,
                    )
                break
            except (APIClientHTTPError, APIClientTransportError) as exc:
                last_exc = exc
                if attempt >= attempts:
                    if isinstance(exc, APIClientHTTPError):
                        logger.error(
                            "AI coach request failed "
                            f"request_id={request_id} client_id={payload.client_id} "
                            f"status={exc.status} reason={exc.reason}"
                        )
                        raise
                    logger.error(
                        f"AI coach request transport failed request_id={request_id} client_id={payload.client_id} error={exc}"
                    )
                    raise
                logger.info(
                    f"ai_coach.ask.retry attempt={attempt} delay={delay:.2f}s request_id={request_id} error={exc}"
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2.0, 4.5)

        logger.debug(f"AI coach ask response request_id={request_id} HTTP={status}: {data}")
        if status == 200:
            return data

        reason: str | None = None
        if isinstance(data, dict):
            reason = data.get("reason") or data.get("detail")
        text = json.dumps(data) if isinstance(data, (dict, list)) else str(data or "")
        raise APIClientHTTPError(
            status,
            text,
            method="post",
            url="ask/",
            retryable=False,
            reason=reason if isinstance(reason, str) else None,
        )

    def _build_qa_response(
        self,
        data: Any,
        *,
        client_id: int,
        request_id: str | None,
    ) -> QAResponse:
        if isinstance(data, QAResponse):
            return data
        if isinstance(data, dict):
            try:
                return QAResponse.model_validate(data)
            except (ValidationError, TypeError) as exc:
                logger.error(
                    f"AI coach QA payload validation failed client_id={client_id} request_id={request_id} error={exc}"
                )
                raise UserServiceError("AI coach returned an invalid QA payload") from exc
        if isinstance(data, str):
            text = data.strip()
            if not text:
                logger.error(f"AI coach QA payload empty string client_id={client_id} request_id={request_id}")
                raise UserServiceError("AI coach returned an empty QA answer")
            return QAResponse(answer=text)
        if isinstance(data, list):
            parts: list[str] = []
            for item in data:
                if isinstance(item, str) and item.strip():
                    parts.append(item.strip())
                elif item:
                    parts.append(str(item))
            if not parts:
                logger.error(f"AI coach QA payload empty list client_id={client_id} request_id={request_id}")
                raise UserServiceError("AI coach returned an empty QA answer")
            return QAResponse(answer="\n\n".join(parts))
        logger.error(
            f"AI coach QA payload unexpected type client_id={client_id} request_id={request_id} type={type(data)}"
        )
        raise UserServiceError("AI coach returned an invalid QA payload")

    async def refresh_knowledge(self) -> None:
        token = base64.b64encode(
            f"{self.settings.AI_COACH_REFRESH_USER}:{self.settings.AI_COACH_REFRESH_PASSWORD}".encode()
        ).decode()
        headers = {"Authorization": f"Basic {token}"}
        try:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=self.settings.AI_COACH_TIMEOUT) as client:
                status, _ = await self._api_request(
                    "post",
                    "knowledge/refresh/",
                    headers=headers,
                    timeout=self.settings.AI_COACH_TIMEOUT,
                    client=client,
                )
        except (APIClientHTTPError, APIClientTransportError) as exc:
            logger.error(f"Knowledge refresh request failed: {exc}")
            raise UserServiceError(str(exc)) from exc
        if status != 200:
            logger.error(f"Knowledge refresh failed HTTP={status}")
            raise UserServiceError(f"Knowledge refresh failed HTTP={status}")

    async def health(self, timeout: float = 3.0) -> bool:
        try:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=self.settings.AI_COACH_TIMEOUT) as client:
                status, _ = await self._api_request(
                    "get",
                    "health/",
                    timeout=int(timeout),
                    client=client,
                )
        except (APIClientHTTPError, APIClientTransportError) as exc:
            logger.debug(f"AI coach health check failed: {exc}")
            return False
        return status == 200
