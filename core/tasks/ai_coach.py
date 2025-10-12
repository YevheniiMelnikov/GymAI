"""AI coach Celery tasks and helpers."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from celery import Task
from loguru import logger

from config.app_settings import settings
from core.ai_plan_state import AiPlanState
from core.celery_app import app
from core.enums import WorkoutPlanType, WorkoutType
from core.internal_http import build_internal_auth_headers, internal_request_timeout
from core.schemas import Program, Subscription
from core.services import APIService
from core.services.internal.api_client import APIClientHTTPError, APIClientTransportError
from core.utils.redis_lock import get_redis_client, redis_try_lock

__all__ = [
    "handle_ai_plan_failure",
    "notify_ai_plan_ready_task",
    "generate_ai_workout_plan",
    "update_ai_workout_plan",
    "ai_coach_echo",
    "ai_coach_worker_report",
    "refresh_external_knowledge",
]

AI_PLAN_SOFT_TIME_LIMIT = settings.AI_COACH_TIMEOUT
AI_PLAN_TIME_LIMIT = AI_PLAN_SOFT_TIME_LIMIT + 30
AI_PLAN_NOTIFY_SOFT_LIMIT = settings.AI_PLAN_NOTIFY_TIMEOUT
AI_PLAN_NOTIFY_TIME_LIMIT = AI_PLAN_NOTIFY_SOFT_LIMIT + 30


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
    headers = build_internal_auth_headers(
        internal_api_key=settings.INTERNAL_API_KEY,
        fallback_api_key=settings.API_KEY,
    )
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
            response: httpx.Response = await client.post(url, json=payload, headers=headers)
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
    client_id = payload.get("client_id")
    detail = f"{type(exc).__name__}: {exc!s}"
    state = AiPlanState.create()
    await state.mark_failed(request_id, detail)
    logger.error(
        f"ai_plan_notify_gave_up action={action} client_id={client_id} request_id={request_id} detail={detail}"
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
    payload: dict[str, Any],
    action: str,
    detail: str,
) -> None:
    client_id = int(payload.get("client_id", 0))
    plan_type_raw = payload.get("plan_type", WorkoutPlanType.PROGRAM.value)
    try:
        plan_type = WorkoutPlanType(plan_type_raw)
    except ValueError:
        plan_type = WorkoutPlanType.PROGRAM
    request_id = str(payload.get("request_id", ""))
    client_profile_id_raw = payload.get("client_profile_id")
    client_profile_id: int | None
    try:
        client_profile_id = int(client_profile_id_raw) if client_profile_id_raw is not None else None
    except (TypeError, ValueError):
        client_profile_id = None
    reason = detail or "task_failed"
    await _notify_error(
        client_id=client_id,
        plan_type=plan_type,
        request_id=request_id,
        action=action,
        error=reason,
        client_profile_id=client_profile_id,
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
def handle_ai_plan_failure(
    self, payload: dict[str, Any], action: str, *exc_info: Any
) -> None:  # pyrefly: ignore[valid-type]
    detail = _extract_failure_detail(exc_info)
    asyncio.run(_handle_ai_plan_failure_impl(payload, action, detail))


def _parse_workout_type(raw: Any) -> WorkoutType | None:
    if not raw:
        return None
    try:
        return WorkoutType(str(raw))
    except ValueError:
        return None


async def _notify_error(
    *,
    client_id: int,
    plan_type: WorkoutPlanType,
    request_id: str,
    action: str,
    error: str,
    client_profile_id: int | None,
) -> None:
    payload: dict[str, Any] = {
        "client_id": client_id,
        "plan_type": plan_type.value,
        "status": "error",
        "action": action,
        "request_id": request_id,
        "error": error,
    }
    if client_profile_id is not None:
        payload["client_profile_id"] = client_profile_id
    notify_ai_plan_ready_task.apply_async(
        args=[payload],
        queue="ai_coach",
        routing_key="ai_coach",
    )


async def _generate_ai_workout_plan_impl(payload: dict[str, Any], task: Task) -> dict[str, Any] | None:
    client_id = int(payload["client_id"])
    client_profile_id_raw = payload.get("client_profile_id")
    client_profile_id: int | None
    try:
        client_profile_id = int(client_profile_id_raw) if client_profile_id_raw is not None else None
    except (TypeError, ValueError):
        logger.warning(
            f"ai_generate_plan invalid_profile_id client_id={client_id} "
            f"raw={client_profile_id_raw!r} request_id={payload.get('request_id', '')}"
        )
        client_profile_id = None
    request_id = str(payload.get("request_id", ""))
    wishes = str(payload.get("wishes", ""))
    language = str(payload.get("language", settings.DEFAULT_LANG))
    period = payload.get("period")
    workout_days = payload.get("workout_days") or []
    plan_type = WorkoutPlanType(payload.get("plan_type", WorkoutPlanType.PROGRAM.value))
    workout_type = _parse_workout_type(payload.get("workout_type"))
    attempt = getattr(task.request, "retries", 0)

    if not await _claim_plan_request(request_id, "create", attempt=attempt):
        logger.info(
            f"ai_generate_plan_duplicate client_id={client_id} plan_type={plan_type.value} request_id={request_id}"
        )
        return None

    logger.info(
        f"ai_generate_plan started client_id={client_id} plan_type={plan_type.value} "
        f"request_id={request_id} attempt={attempt}"
    )

    try:
        plan = await APIService.ai_coach.create_workout_plan(
            plan_type,
            client_id=client_id,
            language=language,
            period=str(period) if period else None,
            workout_days=list(workout_days),
            wishes=wishes,
            workout_type=workout_type,
            request_id=request_id or None,
        )
    except APIClientHTTPError as exc:
        logger.error(
            f"ai_generate_plan failed client_id={client_id} plan_type={plan_type.value} "
            f"request_id={request_id} attempt={attempt} status={exc.status} retryable={exc.retryable} "
            f"reason={exc.reason}"
        )
        if not exc.retryable:
            await _notify_error(
                client_id=client_id,
                plan_type=plan_type,
                request_id=request_id,
                action="create",
                error=exc.reason or f"http_{exc.status}",
                client_profile_id=client_profile_id,
            )
            return None
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error(
            f"ai_generate_plan failed client_id={client_id} plan_type={plan_type.value} "
            f"request_id={request_id} attempt={attempt} error={exc}"
        )
        if attempt >= getattr(task, "max_retries", 0):
            await _notify_error(
                client_id=client_id,
                plan_type=plan_type,
                request_id=request_id,
                action="create",
                error=str(exc),
                client_profile_id=client_profile_id,
            )
        raise

    if plan is None:
        logger.error(
            f"ai_generate_plan returned empty client_id={client_id} plan_type={plan_type.value} request_id={request_id}"
        )
        await _notify_error(
            client_id=client_id,
            plan_type=plan_type,
            request_id=request_id,
            action="create",
            error="empty_plan",
            client_profile_id=client_profile_id,
        )
        return None

    if plan_type is WorkoutPlanType.PROGRAM:
        program = Program.model_validate(plan)
        plan_payload = program.model_dump(mode="json")
    else:
        subscription = Subscription.model_validate(plan)
        plan_payload = subscription.model_dump(mode="json")

    notify_payload = {
        "client_id": client_id,
        "plan_type": plan_type.value,
        "status": "success",
        "action": "create",
        "request_id": request_id,
        "plan": plan_payload,
    }
    if client_profile_id is not None:
        notify_payload["client_profile_id"] = client_profile_id

    logger.info(f"ai_generate_plan completed client_id={client_id} plan_type={plan_type.value} request_id={request_id}")
    return notify_payload


async def _update_ai_workout_plan_impl(payload: dict[str, Any], task: Task) -> dict[str, Any] | None:
    client_id = int(payload["client_id"])
    client_profile_id_raw = payload.get("client_profile_id")
    client_profile_id: int | None
    try:
        client_profile_id = int(client_profile_id_raw) if client_profile_id_raw is not None else None
    except (TypeError, ValueError):
        logger.warning(
            f"ai_update_plan invalid_profile_id client_id={client_id} "
            f"raw={client_profile_id_raw!r} request_id={payload.get('request_id', '')}"
        )
        client_profile_id = None
    request_id = str(payload.get("request_id", ""))
    language = str(payload.get("language", settings.DEFAULT_LANG))
    expected_workout = payload.get("expected_workout")
    if expected_workout is None:
        expected_workout = payload.get("expected_workout_result")
    expected_workout = str(expected_workout) if expected_workout is not None else None

    feedback_val = payload.get("feedback")
    feedback = str(feedback_val) if feedback_val is not None else None
    plan_type = WorkoutPlanType(payload.get("plan_type", WorkoutPlanType.SUBSCRIPTION.value))
    workout_type = _parse_workout_type(payload.get("workout_type"))
    attempt = getattr(task.request, "retries", 0)

    if not await _claim_plan_request(request_id, "update", attempt=attempt):
        logger.info(
            f"ai_update_plan_duplicate client_id={client_id} plan_type={plan_type.value} request_id={request_id}"
        )
        return None

    logger.info(
        f"ai_update_plan started client_id={client_id} plan_type={plan_type.value} "
        f"request_id={request_id} attempt={attempt}"
    )

    try:
        plan = await APIService.ai_coach.update_workout_plan(
            plan_type,
            client_id=client_id,
            language=language,
            expected_workout=expected_workout,
            feedback=feedback,
            workout_type=workout_type,
            request_id=request_id or None,
        )
    except APIClientHTTPError as exc:
        logger.error(
            f"ai_update_plan failed client_id={client_id} plan_type={plan_type.value} "
            f"request_id={request_id} attempt={attempt} status={exc.status} retryable={exc.retryable} "
            f"reason={exc.reason}"
        )
        if not exc.retryable:
            await _notify_error(
                client_id=client_id,
                plan_type=plan_type,
                request_id=request_id,
                action="update",
                error=exc.reason or f"http_{exc.status}",
                client_profile_id=client_profile_id,
            )
            return None
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error(
            f"ai_update_plan failed client_id={client_id} plan_type={plan_type.value} "
            f"request_id={request_id} attempt={attempt} error={exc}"
        )
        if attempt >= getattr(task, "max_retries", 0):
            await _notify_error(
                client_id=client_id,
                plan_type=plan_type,
                request_id=request_id,
                action="update",
                error=str(exc),
                client_profile_id=client_profile_id,
            )
        raise

    if plan is None:
        logger.error(
            f"ai_update_plan returned empty client_id={client_id} plan_type={plan_type.value} request_id={request_id}"
        )
        await _notify_error(
            client_id=client_id,
            plan_type=plan_type,
            request_id=request_id,
            action="update",
            error="empty_plan",
            client_profile_id=client_profile_id,
        )
        return None

    if plan_type is WorkoutPlanType.PROGRAM:
        program = Program.model_validate(plan)
        plan_payload = program.model_dump(mode="json")
    else:
        subscription = Subscription.model_validate(plan)
        plan_payload = subscription.model_dump(mode="json")

    notify_payload = {
        "client_id": client_id,
        "plan_type": plan_type.value,
        "status": "success",
        "action": "update",
        "request_id": request_id,
        "plan": plan_payload,
    }
    if client_profile_id is not None:
        notify_payload["client_profile_id"] = client_profile_id

    logger.info(f"ai_update_plan completed client_id={client_id} plan_type={plan_type.value} request_id={request_id}")
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
    request_id = str(payload.get("request_id", ""))
    action = str(payload.get("action", ""))
    try:
        asyncio.run(_notify_ai_plan_ready(payload))
    except (httpx.HTTPStatusError, httpx.TransportError) as exc:
        attempt = int(getattr(self.request, "retries", 0))
        max_retries = int(getattr(self, "max_retries", 0) or 0)
        logger.warning(f"ai_plan_notify_retry action={action} request_id={request_id} attempt={attempt} error={exc}")
        if attempt >= max_retries:
            asyncio.run(_handle_notify_failure(payload, exc))
            raise
        raise self.retry(exc=exc)
    except Exception as exc:  # noqa: BLE001
        asyncio.run(_handle_notify_failure(payload, exc))
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
        notify_payload = asyncio.run(_generate_ai_workout_plan_impl(payload, self))
    except APIClientHTTPError as exc:
        retries = int(getattr(self.request, "retries", 0))
        max_retries = int(getattr(self, "max_retries", 0) or 0)
        if exc.retryable and retries < max_retries:
            logger.warning(f"ai_generate_plan_retry status={exc.status} reason={exc.reason} attempt={retries}")
            raise self.retry(exc=exc)
        raise
    else:
        if notify_payload:
            notify_ai_plan_ready_task.apply_async(args=[notify_payload], queue="ai_coach", routing_key="ai_coach")
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
        if notify_payload:
            notify_ai_plan_ready_task.apply_async(args=[notify_payload], queue="ai_coach", routing_key="ai_coach")
        return notify_payload


@app.task(
    bind=True,
    queue="ai_coach",
    routing_key="ai_coach",
)
def ai_coach_echo(self, payload: dict[str, Any]) -> dict[str, Any]:
    payload_descriptor: str
    if isinstance(payload, dict):
        payload_descriptor = ",".join(sorted(str(key) for key in payload.keys()))
    else:
        payload_descriptor = type(payload).__name__
    logger.info(f"ai_coach_echo started task_id={self.request.id} payload_descriptor={payload_descriptor}")
    return {"ok": True, "echo": payload}


@app.task(
    bind=True,
    queue="ai_coach",
    routing_key="ai_coach",
)
def ai_coach_worker_report(self) -> dict[str, Any]:
    broker_url = str(getattr(app.conf, "broker_url", ""))
    backend_url = str(getattr(app.conf, "result_backend", ""))
    hostname = getattr(self.request, "hostname", None)
    logger.info(f"ai_coach_worker_report hostname={hostname} broker={broker_url} backend={backend_url}")
    queues = [queue.name for queue in getattr(app.conf, "task_queues", [])]
    return {
        "broker": broker_url,
        "backend": backend_url,
        "hostname": hostname,
        "queues": queues,
    }


@app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=180,
    retry_jitter=True,
    max_retries=3,
)
def refresh_external_knowledge(self) -> None:
    """Refresh external knowledge and rebuild Cognee index."""
    logger.info("refresh_external_knowledge triggered")

    async def _dedupe_window(window_s: int = 30) -> bool:
        r = get_redis_client()
        ok = await r.set("dedupe:refresh_external_knowledge", "1", nx=True, ex=window_s)
        return bool(ok)

    async def _impl() -> None:
        if not await _dedupe_window(30):
            logger.info("refresh_external_knowledge skipped: dedupe window active")
            return

        async with redis_try_lock(
            "locks:refresh_external_knowledge",
            ttl_ms=180_000,
            wait=False,
        ) as got:
            if not got:
                logger.info("refresh_external_knowledge skipped: lock is held")
                return

            for attempt in range(3):
                if await APIService.ai_coach.health(timeout=3.0):
                    break
                logger.warning(f"AI coach health check failed attempt {attempt + 1}")
                await asyncio.sleep(1)
            else:
                logger.warning("AI coach not ready, skipping refresh_external_knowledge")
                return
            await APIService.ai_coach.refresh_knowledge()

    try:
        asyncio.run(_impl())
    except Exception as exc:  # noqa: BLE001
        logger.error(f"refresh_external_knowledge failed: {exc}")
        raise
    else:
        logger.info("refresh_external_knowledge completed")
