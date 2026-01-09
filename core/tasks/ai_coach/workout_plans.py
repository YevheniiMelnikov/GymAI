"""AI coach Celery tasks and helpers."""

import asyncio
from collections.abc import Mapping
from typing import Any

import httpx
import orjson
from celery import Task
from loguru import logger

from config.app_settings import settings
from core.ai_coach.state.plan import AiPlanState
from core.celery_app import app
from core.enums import WorkoutPlanType, WorkoutLocation
from core.internal_http import build_internal_hmac_auth_headers, internal_request_timeout
from core.schemas import Program, Subscription
from core.services import APIService
from core.services.internal.api_client import APIClientHTTPError, APIClientTransportError
from core.metrics.constants import METRICS_EVENT_WORKOUT_PLAN, METRICS_SOURCE_WORKOUT_PLAN
from core.tasks.ai_coach.metrics import emit_metrics_event

__all__ = [
    "handle_ai_plan_failure",
    "notify_ai_plan_ready_task",
    "generate_ai_workout_plan",
    "update_ai_workout_plan",
    "_generate_ai_workout_plan_impl",
    "_update_ai_workout_plan_impl",
]

AI_PLAN_SOFT_TIME_LIMIT = settings.AI_COACH_TIMEOUT
AI_PLAN_TIME_LIMIT = AI_PLAN_SOFT_TIME_LIMIT + 30
AI_PLAN_NOTIFY_SOFT_LIMIT = settings.AI_PLAN_NOTIFY_TIMEOUT
AI_PLAN_NOTIFY_TIME_LIMIT = AI_PLAN_NOTIFY_SOFT_LIMIT + 30


def _resolve_profile_id(payload: Mapping[str, Any]) -> int | None:
    raw = payload.get("profile_id")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _normalize_payload(payload: Any, *, context: str) -> dict[str, Any] | None:
    if isinstance(payload, Mapping):
        return dict(payload)
    logger.warning(
        "ai_plan_payload_invalid context={} type={} value={}",
        context,
        type(payload).__name__,
        payload,
    )
    return None


async def _claim_plan_request(request_id: str, action: str, *, attempt: int) -> bool:
    if not request_id or attempt > 0:
        return True
    state = AiPlanState.create()
    claim_key = f"{action}:{request_id}"
    claimed = await state.claim_delivery(claim_key, ttl_s=settings.AI_PLAN_DEDUP_TTL)
    if not claimed:
        logger.debug(f"ai_plan_request_duplicate action={action} request_id={request_id}")
    return claimed


async def _notify_ai_plan_ready(payload: dict[str, Any]) -> None:
    base_url: str = settings.BOT_INTERNAL_URL.rstrip("/")
    url: str = f"{base_url}/internal/tasks/ai_plan_ready/"
    body = orjson.dumps(payload)
    if settings.INTERNAL_API_KEY:
        headers = build_internal_hmac_auth_headers(
            key_id=settings.INTERNAL_KEY_ID,
            secret_key=settings.INTERNAL_API_KEY,
            body=body,
        )
        headers.setdefault("X-Internal-Api-Key", settings.INTERNAL_API_KEY)
    else:
        headers = {"Authorization": f"Api-Key {settings.API_KEY}"}
    timeout = internal_request_timeout(settings)
    request_id = str(payload.get("request_id", ""))
    action = str(payload.get("action", ""))
    status = str(payload.get("status", ""))
    state = AiPlanState.create()
    if request_id:
        if status == "success" and await state.is_delivered(request_id):
            logger.debug(f"ai_plan_notify_skip_already_delivered action={action} request_id={request_id}")
            return
        if status != "success" and await state.is_failed(request_id):
            logger.debug(f"ai_plan_notify_skip_already_failed action={action} request_id={request_id}")
            return
    logger.info(f"ai_plan_notify_start action={action} request_id={request_id} url={url}")
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response: httpx.Response = await client.post(url, content=body, headers=headers)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status_code: int | None = exc.response.status_code if exc.response is not None else None
        detail: str = f"status={status_code} error={exc!s}"
        logger.error(f"ai_plan_notify_failed action={action} request_id={request_id} {detail}")
        raise
    except httpx.TransportError as exc:
        detail: str = f"transport_error={exc!r}"
        logger.error(f"ai_plan_notify_transport_error action={action} request_id={request_id} {detail}")
        raise
    status_code = response.status_code
    logger.info(f"ai_plan_notify_done action={action} request_id={request_id} status={status_code}")
    if payload.get("status") == "success":
        await state.mark_delivered(request_id)
    else:
        await state.mark_failed(request_id, str(payload.get("error", "unknown")))


async def _handle_notify_failure(payload: dict[str, Any], exc: Exception) -> None:
    request_id = str(payload.get("request_id", ""))
    action = str(payload.get("action", ""))
    profile_id = _resolve_profile_id(payload)
    detail = f"{type(exc).__name__}: {exc!s}"
    state = AiPlanState.create()
    await state.mark_failed(request_id, detail)
    logger.error(
        f"ai_plan_notify_gave_up action={action} profile_id={profile_id} request_id={request_id} detail={detail}"
    )


def _extract_failure_detail(exc_info: tuple[Any, ...]) -> str:
    for item in exc_info:
        if isinstance(item, BaseException):
            return f"{type(item).__name__}: {item!s}"
        if isinstance(item, dict):
            candidate = item.get("exc")
            if isinstance(candidate, BaseException):
                return f"{type(candidate).__name__}: {candidate!s}"
            if candidate:
                return str(candidate)
        if isinstance(item, str) and item:
            return item
    return "task_failed"


async def _handle_ai_plan_failure_impl(
    payload: Mapping[str, Any],
    action: str,
    detail: str,
) -> None:
    profile_id = _resolve_profile_id(payload)
    request_id = str(payload.get("request_id", ""))
    if profile_id is None:
        logger.error(f"ai_plan_failure_missing_profile action={action} request_id={request_id}")
        return
    plan_type_raw = payload.get("plan_type", WorkoutPlanType.PROGRAM.value)
    try:
        plan_type = WorkoutPlanType(plan_type_raw)
    except ValueError:
        plan_type = WorkoutPlanType.PROGRAM
    reason = detail or "task_failed"
    await _notify_error(
        plan_type=plan_type,
        request_id=request_id,
        action=action,
        error=reason,
        profile_id=profile_id,
    )


@app.task(
    bind=True,
    queue="ai_coach",
    routing_key="ai_coach",
    acks_late=True,
    task_acks_on_failure_or_timeout=False,
    soft_time_limit=AI_PLAN_NOTIFY_SOFT_LIMIT,
    time_limit=AI_PLAN_NOTIFY_TIME_LIMIT,
)
def handle_ai_plan_failure(self, payload: Any, action: str, *exc_info: Any) -> None:  # pyrefly: ignore[valid-type]
    detail = _extract_failure_detail(exc_info)
    normalized = _normalize_payload(payload, context="handle_ai_plan_failure")
    if normalized is None:
        logger.error(f"ai_plan_failure_payload_missing action={action} detail={detail}")
        return
    asyncio.run(_handle_ai_plan_failure_impl(normalized, action, detail))


def _parse_workout_location(raw: Any) -> WorkoutLocation | None:
    if not raw:
        return None
    try:
        return WorkoutLocation(str(raw))
    except ValueError:
        return None


async def _notify_error(
    *,
    profile_id: int,
    plan_type: WorkoutPlanType,
    request_id: str,
    action: str,
    error: str,
) -> None:
    payload: dict[str, Any] = {
        "profile_id": profile_id,
        "plan_type": plan_type.value,
        "status": "error",
        "action": action,
        "request_id": request_id,
        "error": error,
    }
    notify_ai_plan_ready_task.apply_async(  # pyrefly: ignore[not-callable]
        args=[payload],
        queue="ai_coach",
        routing_key="ai_coach",
    )


async def _generate_ai_workout_plan_impl(payload: dict[str, Any], task: Task) -> dict[str, Any] | None:
    profile_id = _resolve_profile_id(payload)
    if profile_id is None:
        request_id = str(payload.get("request_id", ""))
        logger.error(f"ai_generate_plan_missing_profile request_id={request_id}")
        return None
    request_id = str(payload.get("request_id", ""))
    wishes = str(payload.get("wishes", ""))
    language = str(payload.get("language", settings.DEFAULT_LANG))
    period = payload.get("period")
    split_raw = payload.get("split_number")
    if isinstance(split_raw, int):
        split_number = split_raw
    elif isinstance(split_raw, (str, bytes, bytearray)) and str(split_raw).strip().isdigit():
        split_number = int(split_raw)
    else:
        split_number = 3
    split_number = max(1, min(7, split_number))
    plan_type = WorkoutPlanType(payload.get("plan_type", WorkoutPlanType.PROGRAM.value))
    workout_location = _parse_workout_location(payload.get("workout_location"))
    attempt = getattr(task.request, "retries", 0)

    if not await _claim_plan_request(request_id, "create", attempt=attempt):
        logger.info(
            f"ai_generate_plan_duplicate profile_id={profile_id} plan_type={plan_type.value} request_id={request_id}"
        )
        return None

    from django.core.cache import cache

    cache.set(
        f"generation_status:{request_id}",
        {"status": "processing", "progress": 20, "stage": "agent_start"},
        timeout=settings.AI_COACH_TIMEOUT,
    )

    logger.info(
        f"ai_generate_plan started profile_id={profile_id} plan_type={plan_type.value} "
        f"request_id={request_id} attempt={attempt} split_number={split_number}"
    )

    try:
        plan = await APIService.ai_coach.create_workout_plan(
            plan_type,
            profile_id=profile_id,
            language=language,
            period=str(period) if period else None,
            split_number=split_number,
            wishes=wishes,
            workout_location=workout_location,
            request_id=request_id or None,
        )
        cache.set(
            f"generation_status:{request_id}",
            {"status": "processing", "progress": 90, "stage": "plan_received"},
            timeout=settings.AI_COACH_TIMEOUT,
        )
    except APIClientHTTPError as exc:
        logger.error(
            f"ai_generate_plan failed profile_id={profile_id} plan_type={plan_type.value} "
            f"request_id={request_id} attempt={attempt} status={exc.status} retryable={exc.retryable} "
            f"reason={exc.reason}"
        )
        if not exc.retryable:
            await _notify_error(
                plan_type=plan_type,
                request_id=request_id,
                action="create",
                error=exc.reason or f"http_{exc.status}",
                profile_id=profile_id,
            )
            cache.set(
                f"generation_status:{request_id}",
                {"status": "error", "progress": 0, "error": exc.reason or f"http_{exc.status}"},
                timeout=settings.AI_COACH_TIMEOUT,
            )
            return None
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error(
            f"ai_generate_plan failed profile_id={profile_id} plan_type={plan_type.value} "
            f"request_id={request_id} attempt={attempt} error={exc}"
        )
        if attempt >= getattr(task, "max_retries", 0):
            await _notify_error(
                plan_type=plan_type,
                request_id=request_id,
                action="create",
                error=str(exc),
                profile_id=profile_id,
            )
        raise

    if plan is None:
        logger.error(
            "ai_generate_plan returned empty "
            f"profile_id={profile_id} plan_type={plan_type.value} request_id={request_id}"
        )
        cache.set(
            f"generation_status:{request_id}",
            {"status": "error", "progress": 0, "error": "empty_plan"},
            timeout=settings.AI_COACH_TIMEOUT,
        )
        await _notify_error(
            plan_type=plan_type,
            request_id=request_id,
            action="create",
            error="empty_plan",
            profile_id=profile_id,
        )
        return None

    if plan_type is WorkoutPlanType.PROGRAM:
        program = Program.model_validate(plan)
        plan_payload = program.model_dump(mode="json")
    else:
        subscription = Subscription.model_validate(plan)
        plan_payload = subscription.model_dump(mode="json")

    previous_subscription_id = payload.get("previous_subscription_id")
    notify_payload = {
        "profile_id": profile_id,
        "plan_type": plan_type.value,
        "status": "success",
        "action": "create",
        "request_id": request_id,
        "plan": plan_payload,
    }
    if previous_subscription_id is not None:
        notify_payload["previous_subscription_id"] = previous_subscription_id
    logger.info(
        f"ai_generate_plan completed profile_id={profile_id} plan_type={plan_type.value} request_id={request_id}"
    )
    await emit_metrics_event(
        METRICS_EVENT_WORKOUT_PLAN,
        source=METRICS_SOURCE_WORKOUT_PLAN,
        source_id=request_id,
    )
    cache.set(
        f"generation_status:{request_id}",
        {"status": "success", "progress": 100, "stage": "completed", "result_id": plan_payload.get("id")},
        timeout=settings.AI_COACH_TIMEOUT,
    )
    return notify_payload


async def _update_ai_workout_plan_impl(payload: dict[str, Any], task: Task) -> dict[str, Any] | None:
    profile_id = _resolve_profile_id(payload)
    if profile_id is None:
        request_id = str(payload.get("request_id", ""))
        logger.error(f"ai_update_plan_missing_profile request_id={request_id}")
        return None
    request_id = str(payload.get("request_id", ""))
    language = str(payload.get("language", settings.DEFAULT_LANG))
    feedback_val = payload.get("feedback")
    feedback = str(feedback_val) if feedback_val is not None else None
    plan_type = WorkoutPlanType(payload.get("plan_type", WorkoutPlanType.SUBSCRIPTION.value))
    workout_location = _parse_workout_location(payload.get("workout_location"))
    attempt = getattr(task.request, "retries", 0)

    if not await _claim_plan_request(request_id, "update", attempt=attempt):
        logger.info(
            f"ai_update_plan_duplicate profile_id={profile_id} plan_type={plan_type.value} request_id={request_id}"
        )
        return None

    logger.info(
        f"ai_update_plan started profile_id={profile_id} plan_type={plan_type.value} "
        f"request_id={request_id} attempt={attempt}"
    )

    try:
        plan = await APIService.ai_coach.update_workout_plan(
            plan_type,
            profile_id=profile_id,
            language=language,
            feedback=feedback,
            workout_location=workout_location,
            request_id=request_id or None,
        )
    except APIClientHTTPError as exc:
        logger.error(
            f"ai_update_plan failed profile_id={profile_id} plan_type={plan_type.value} "
            f"request_id={request_id} attempt={attempt} status={exc.status} retryable={exc.retryable} "
            f"reason={exc.reason}"
        )
        if not exc.retryable:
            await _notify_error(
                plan_type=plan_type,
                request_id=request_id,
                action="update",
                error=exc.reason or f"http_{exc.status}",
                profile_id=profile_id,
            )
            return None
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error(
            f"ai_update_plan failed profile_id={profile_id} plan_type={plan_type.value} "
            f"request_id={request_id} attempt={attempt} error={exc}"
        )
        if attempt >= getattr(task, "max_retries", 0):
            await _notify_error(
                plan_type=plan_type,
                request_id=request_id,
                action="update",
                error=str(exc),
                profile_id=profile_id,
            )
        raise

    if plan is None:
        logger.error(
            f"ai_update_plan returned empty profile_id={profile_id} plan_type={plan_type.value} request_id={request_id}"
        )
        await _notify_error(
            plan_type=plan_type,
            request_id=request_id,
            action="update",
            error="empty_plan",
            profile_id=profile_id,
        )
        return None

    if plan_type is WorkoutPlanType.PROGRAM:
        program = Program.model_validate(plan)
        plan_payload = program.model_dump(mode="json")
    else:
        subscription = Subscription.model_validate(plan)
        plan_payload = subscription.model_dump(mode="json")

    notify_payload = {
        "profile_id": profile_id,
        "plan_type": plan_type.value,
        "status": "success",
        "action": "update",
        "request_id": request_id,
        "plan": plan_payload,
    }
    logger.info(f"ai_update_plan completed profile_id={profile_id} plan_type={plan_type.value} request_id={request_id}")
    return notify_payload


@app.task(
    bind=True,
    queue="ai_coach",
    routing_key="ai_coach",
    retry_backoff=30,
    retry_jitter=True,
    max_retries=8,
    acks_late=True,
    task_acks_on_failure_or_timeout=False,
    soft_time_limit=AI_PLAN_NOTIFY_SOFT_LIMIT,
    time_limit=AI_PLAN_NOTIFY_TIME_LIMIT,
)
def notify_ai_plan_ready_task(self, payload: dict[str, Any]) -> None:  # pyrefly: ignore[valid-type]
    normalized = _normalize_payload(payload, context="notify_ai_plan_ready_task")
    if normalized is None:
        return
    request_id = str(normalized.get("request_id", ""))
    action = str(normalized.get("action", ""))
    logger.info(
        "ai_plan_notify_enqueued action={} request_id={} status={} plan_type={} profile_id={}",
        action,
        request_id,
        normalized.get("status"),
        normalized.get("plan_type"),
        normalized.get("profile_id"),
    )
    try:
        asyncio.run(_notify_ai_plan_ready(normalized))
    except (httpx.HTTPStatusError, httpx.TransportError) as exc:
        attempt = int(getattr(self.request, "retries", 0))
        max_retries = int(getattr(self, "max_retries", 0) or 0)
        logger.warning(f"ai_plan_notify_retry action={action} request_id={request_id} attempt={attempt} error={exc}")
        if attempt >= max_retries:
            asyncio.run(_handle_notify_failure(normalized, exc))
            raise
        raise self.retry(exc=exc)
    except Exception as exc:  # noqa: BLE001
        asyncio.run(_handle_notify_failure(normalized, exc))
        raise


@app.task(
    bind=True,
    queue="ai_coach",
    routing_key="ai_coach",
    autoretry_for=(APIClientTransportError,),
    retry_backoff=30,
    retry_jitter=True,
    max_retries=5,
    acks_late=True,
    task_acks_on_failure_or_timeout=False,
    soft_time_limit=AI_PLAN_SOFT_TIME_LIMIT,
    time_limit=AI_PLAN_TIME_LIMIT,
)
def generate_ai_workout_plan(self, payload: dict[str, Any]) -> dict[str, Any] | None:  # pyrefly: ignore[valid-type]
    try:
        logger.info(
            "ai_generate_plan_task_start request_id={} profile_id={} plan_type={}",
            payload.get("request_id"),
            payload.get("profile_id"),
            payload.get("plan_type"),
        )
        notify_payload = asyncio.run(_generate_ai_workout_plan_impl(payload, self))
    except APIClientHTTPError as exc:
        retries = int(getattr(self.request, "retries", 0))
        max_retries = int(getattr(self, "max_retries", 0) or 0)
        if exc.retryable and retries < max_retries:
            logger.warning(f"ai_generate_plan_retry status={exc.status} reason={exc.reason} attempt={retries}")
            raise self.retry(exc=exc)
        raise
    else:
        if notify_payload is None:
            logger.error(
                "ai_generate_plan_task_empty request_id={} profile_id={} plan_type={}",
                payload.get("request_id"),
                payload.get("profile_id"),
                payload.get("plan_type"),
            )
        return notify_payload


@app.task(
    bind=True,
    queue="ai_coach",
    routing_key="ai_coach",
    autoretry_for=(APIClientTransportError,),
    retry_backoff=30,
    retry_jitter=True,
    max_retries=5,
    acks_late=True,
    task_acks_on_failure_or_timeout=False,
    soft_time_limit=AI_PLAN_SOFT_TIME_LIMIT,
    time_limit=AI_PLAN_TIME_LIMIT,
)
def update_ai_workout_plan(self, payload: dict[str, Any]) -> dict[str, Any] | None:  # pyrefly: ignore[valid-type]
    try:
        notify_payload = asyncio.run(_update_ai_workout_plan_impl(payload, self))
    except APIClientHTTPError as exc:
        retries = int(getattr(self.request, "retries", 0))
        max_retries = int(getattr(self, "max_retries", 0) or 0)
        if exc.retryable and retries < max_retries:
            logger.warning(f"ai_update_plan_retry status={exc.status} reason={exc.reason} attempt={retries}")
            raise self.retry(exc=exc)
        raise
    else:
        return notify_payload
