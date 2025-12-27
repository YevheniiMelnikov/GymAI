# ai_coach_service.py
import asyncio
import json
from time import monotonic
from enum import Enum
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from loguru import logger
from pydantic import ValidationError

from ai_coach.schemas import AICoachRequest
from ai_coach.types import CoachMode
from core.exceptions import UserServiceError
from core.schemas import DietPlan, Program, Subscription
from core.schemas import QAResponse
from core.internal_http import build_internal_hmac_auth_headers, resolve_hmac_credentials
from .api_client import APIClient, APIClientHTTPError, APIClientTransportError
from ...enums import WorkoutPlanType, WorkoutLocation


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
        profile_id: int,
        language: str | Enum | None = None,
        request_id: str | None = None,
        attachments: list[dict[str, str]] | None = None,
    ) -> QAResponse | None:
        payload = AICoachRequest(
            prompt=prompt,
            profile_id=profile_id,
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
            profile_id=profile_id,
            request_id=request_id,
        )

    async def ask(
        self,
        prompt: str,
        *,
        profile_id: int,
        language: str | Enum | None = None,
        request_id: str | None = None,
        use_agent_header: bool = False,
        attachments: list[dict[str, str]] | None = None,
    ) -> QAResponse | None:
        payload = AICoachRequest(
            prompt=prompt,
            profile_id=profile_id,
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
            profile_id=profile_id,
            request_id=request_id,
        )

    async def create_workout_plan(
        self,
        plan_type: WorkoutPlanType,
        *,
        profile_id: int,
        language: str | Enum | None = None,
        period: str | None = None,
        split_number: int | None = None,
        wishes: str | None = None,
        workout_location: WorkoutLocation | None = None,
        request_id: str | None = None,
    ) -> Program | Subscription | None:
        payload = AICoachRequest(
            prompt=None,
            profile_id=profile_id,
            language=language.value if isinstance(language, Enum) else language,
            mode=(CoachMode.program if plan_type is WorkoutPlanType.PROGRAM else CoachMode.subscription),
            period=period,
            split_number=split_number,
            wishes=wishes,
            workout_location=workout_location,
            plan_type=plan_type,
            request_id=request_id,
        )
        data = await self._post_ask(payload, request_id=request_id)
        if data is None:
            return None
        if plan_type is WorkoutPlanType.PROGRAM:
            return self._validate_program_response(
                data,
                profile_id=profile_id,
                request_id=request_id,
                context="create",
            )
        return Subscription.model_validate(data)

    async def update_workout_plan(
        self,
        plan_type: WorkoutPlanType,
        *,
        profile_id: int,
        language: str | Enum | None = None,
        period: str | None = None,
        split_number: int | None = None,
        expected_workout: str | None = None,
        feedback: str | None = None,
        wishes: str | None = None,
        workout_location: WorkoutLocation | None = None,
        request_id: str | None = None,
    ) -> Program | Subscription | None:
        payload = AICoachRequest(
            prompt=None,
            profile_id=profile_id,
            language=language.value if isinstance(language, Enum) else language,
            mode=CoachMode.update,
            period=period,
            split_number=split_number,
            expected_workout=expected_workout,
            feedback=feedback,
            wishes=wishes,
            workout_location=workout_location,
            plan_type=plan_type,
            request_id=request_id,
        )
        data = await self._post_ask(payload, request_id=request_id)
        if data is None:
            return None
        if plan_type is WorkoutPlanType.PROGRAM:
            return self._validate_program_response(
                data,
                profile_id=profile_id,
                request_id=request_id,
                context="update",
            )
        return Subscription.model_validate(data)

    async def create_diet_plan(
        self,
        *,
        profile_id: int,
        language: str | Enum | None = None,
        diet_allergies: str | None = None,
        diet_products: list[str] | None = None,
        prompt: str | None = None,
        request_id: str | None = None,
    ) -> DietPlan | None:
        payload = AICoachRequest(
            prompt=prompt,
            profile_id=profile_id,
            language=language.value if isinstance(language, Enum) else language,
            mode=CoachMode.diet,
            request_id=request_id,
            diet_allergies=diet_allergies,
            diet_products=diet_products,
        )
        data = await self._post_ask(payload, request_id=request_id)
        if data is None:
            return None
        return DietPlan.model_validate(data)

    def _hmac_headers(self, body: bytes) -> dict[str, str]:
        env_mode = str(getattr(self.settings, "ENVIRONMENT", "development")).lower()
        creds = resolve_hmac_credentials(self.settings, prefer_ai_coach=True)
        if creds is None:
            if env_mode != "production":
                return {}
            raise UserServiceError("AI coach HMAC credentials are not configured")
        key_id, secret_key = creds
        return build_internal_hmac_auth_headers(key_id=key_id, secret_key=secret_key, body=body)

    def _validate_program_response(
        self,
        data: Any,
        *,
        profile_id: int,
        request_id: str | None,
        context: str,
    ) -> Program:
        if isinstance(data, Program):
            return data
        try:
            return Program.model_validate(data)
        except (ValidationError, TypeError) as exc:
            logger.warning(
                f"ai_coach_invalid_program_payload profile_id={profile_id} request_id={request_id} "
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
        # Serialize deterministically for HMAC; these bytes are sent as-is
        body_bytes: bytes = json.dumps(payload_dict, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
        headers.update(self._hmac_headers(body_bytes))
        if payload.mode is CoachMode.ask_ai:
            endpoint = "coach/chat/"
        elif payload.mode is CoachMode.diet:
            endpoint = "coach/diet/"
        else:
            endpoint = "coach/plan/"
        logger.debug(
            "ai_coach.request POST endpoint={} profile_id={} mode={} language={} request_id={}",
            endpoint,
            payload.profile_id,
            payload.mode.value,
            payload_dict.get("language"),
            request_id,
        )
        ping_path = "health/"
        ping_url = urljoin(self.base_url, ping_path)
        ping_headers = self._hmac_headers(b"")
        logger.debug("ai_coach.ping.start request_id={} url={}", request_id, ping_url)
        ping_started = monotonic()
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
                        headers=ping_headers,
                        client=client,
                    )
                logger.debug(
                    "ai_coach.ping.ok request_id={} status={} attempt={}",
                    request_id,
                    ping_status,
                    attempt,
                )
                ping_elapsed_ms = int((monotonic() - ping_started) * 1000)
                if ping_elapsed_ms >= 500:
                    logger.info(
                        f"ai_coach.ping.done request_id={request_id} status={ping_status} "
                        f"attempt={attempt} elapsed_ms={ping_elapsed_ms}"
                    )
                else:
                    logger.debug(
                        f"ai_coach.ping.done request_id={request_id} status={ping_status} "
                        f"attempt={attempt} elapsed_ms={ping_elapsed_ms}"
                    )
                break
            except (APIClientTransportError, APIClientHTTPError) as exc:
                if attempt >= attempts:
                    logger.warning(f"ai_coach.ping.giveup request_id={request_id} attempts={attempts} error={exc}")
                    # Continue to main request; POST will also have its own retries
                    break
                logger.debug(
                    "ai_coach.ping.retry request_id={} attempt={} delay={:.2f}s error={}",
                    request_id,
                    attempt,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2.0, 4.5)

        # Main POST with retries and per-call client
        attempts = 5
        delay = 0.5
        status: int = 0
        data: Any | None = None
        for attempt in range(1, attempts + 1):
            attempt_started = monotonic()
            try:
                async with httpx.AsyncClient(base_url=self.base_url, timeout=self.settings.AI_COACH_TIMEOUT) as client:
                    status, data = await self._api_request(
                        "post",
                        endpoint,
                        payload_dict,
                        body_bytes=body_bytes,
                        headers=headers or None,
                        timeout=self.settings.AI_COACH_TIMEOUT,
                        client=client,
                    )
                attempt_elapsed_ms = int((monotonic() - attempt_started) * 1000)
                if attempt_elapsed_ms >= 500:
                    logger.info(
                        f"ai_coach.request.ok request_id={request_id} endpoint={endpoint} "
                        f"attempt={attempt} elapsed_ms={attempt_elapsed_ms}"
                    )
                else:
                    logger.debug(
                        f"ai_coach.request.ok request_id={request_id} endpoint={endpoint} "
                        f"attempt={attempt} elapsed_ms={attempt_elapsed_ms}"
                    )
                break
            except (APIClientHTTPError, APIClientTransportError) as exc:
                attempt_elapsed_ms = int((monotonic() - attempt_started) * 1000)
                logger.warning(
                    f"ai_coach.request.failed request_id={request_id} endpoint={endpoint} "
                    f"attempt={attempt} elapsed_ms={attempt_elapsed_ms} error={exc}"
                )
                if attempt >= attempts:
                    if isinstance(exc, APIClientHTTPError):
                        logger.error(
                            f"AI coach request failed request_id={request_id} profile_id={payload.profile_id} "
                            f"status={exc.status} reason={exc.reason}"
                        )
                        raise
                    logger.error(
                        f"AI coach request transport failed request_id={request_id} "
                        f"profile_id={payload.profile_id} error={exc}"
                    )
                    raise
                logger.info(
                    f"ai_coach.request.retry attempt={attempt} delay={delay:.2f}s request_id={request_id} error={exc}"
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2.0, 4.5)

        logger.debug("ai_coach.response request_id={} endpoint={} HTTP={}", request_id, endpoint, status)
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
            url=endpoint,
            retryable=False,
            reason=reason if isinstance(reason, str) else None,
        )

    def _build_qa_response(
        self,
        data: Any,
        *,
        profile_id: int,
        request_id: str | None,
    ) -> QAResponse:
        if isinstance(data, QAResponse):
            return data
        if isinstance(data, dict):
            try:
                return QAResponse.model_validate(data)
            except (ValidationError, TypeError) as exc:
                logger.error(
                    f"AI coach QA payload validation failed profile_id={profile_id} request_id={request_id} error={exc}"
                )
                raise UserServiceError("AI coach returned an invalid QA payload") from exc
        if isinstance(data, str):
            text = data.strip()
            if not text:
                logger.error(f"AI coach QA payload empty string profile_id={profile_id} request_id={request_id}")
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
                logger.error(f"AI coach QA payload empty list profile_id={profile_id} request_id={request_id}")
                raise UserServiceError("AI coach returned an empty QA answer")
            return QAResponse(answer="\n\n".join(parts))
        logger.error(
            f"AI coach QA payload unexpected type profile_id={profile_id} request_id={request_id} type={type(data)}"
        )
        raise UserServiceError("AI coach returned an invalid QA payload")

    async def refresh_knowledge(self) -> None:
        creds = resolve_hmac_credentials(self.settings, prefer_ai_coach=True)
        env_mode = str(getattr(self.settings, "ENVIRONMENT", "development")).lower()
        body = b"{}"
        if creds is None:
            if env_mode != "production":
                headers = {}
            else:
                raise UserServiceError("AI coach HMAC credentials are not configured")
        else:
            key_id, secret_key = creds
            headers = build_internal_hmac_auth_headers(key_id=key_id, secret_key=secret_key, body=body)
            headers["Content-Type"] = "application/json"
        try:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=self.settings.AI_COACH_TIMEOUT) as client:
                status, _ = await self._api_request(
                    "post",
                    "knowledge/refresh/",
                    headers=headers,
                    body_bytes=body,
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
