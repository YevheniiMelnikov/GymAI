"""Celery tasks for AI diet plan generation."""

from typing import Any

import httpx
from asgiref.sync import async_to_sync
from celery import Task
from loguru import logger
from redis.exceptions import RedisError

import orjson

from config.app_settings import settings
from core.ai_coach.state.diet import AiDietState
from core.celery_app import app
from core.internal_http import build_internal_hmac_auth_headers, internal_request_timeout
from core.schemas import DietPlan, Profile
from core.services import APIService
from core.services.internal.api_client import APIClientHTTPError, APIClientTransportError
from core.metrics.constants import METRICS_EVENT_DIET_PLAN, METRICS_SOURCE_DIET
from core.tasks.ai_coach.metrics import emit_metrics_event

__all__ = [
    "generate_ai_diet_plan",
    "notify_ai_diet_ready_task",
    "handle_ai_diet_failure",
    "refund_ai_diet_credits_task",
]

AI_DIET_SOFT_TIME_LIMIT = settings.AI_COACH_TIMEOUT
AI_DIET_TIME_LIMIT = AI_DIET_SOFT_TIME_LIMIT + 30
AI_DIET_NOTIFY_SOFT_LIMIT = settings.AI_PLAN_NOTIFY_TIMEOUT
AI_DIET_NOTIFY_TIME_LIMIT = AI_DIET_NOTIFY_SOFT_LIMIT + 30
AI_DIET_REFUND_SOFT_LIMIT = 120
AI_DIET_REFUND_TIME_LIMIT = 150


def _resolve_profile_id(payload: dict[str, Any]) -> int | None:
    raw = payload.get("profile_id")
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _dispatch_refund_task(payload: dict[str, Any]) -> None:
    request_id = str(payload.get("request_id", ""))
    profile_id = _resolve_profile_id(payload)
    cost = int(payload.get("cost", 0))
    if not request_id or profile_id is None or cost <= 0:
        logger.debug(
            f"event=ai_diet_refund_skip request_id={request_id} profile_id={profile_id} cost={cost} reason=invalid"
        )
        return
    refund_payload = {
        "request_id": request_id,
        "profile_id": profile_id,
        "cost": cost,
    }
    refund_ai_diet_credits_task.apply_async(  # pyrefly: ignore[not-callable]
        args=[refund_payload],
        queue="ai_coach",
        routing_key="ai_coach",
    )


async def _attempt_inline_refund(payload: dict[str, Any]) -> bool:
    request_id = str(payload.get("request_id", ""))
    profile_id = _resolve_profile_id(payload)
    try:
        return await _refund_credits_impl(payload)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            f"event=ai_diet_refund_inline_failed request_id={request_id} profile_id={profile_id} error={exc!s}"
        )
        return False


async def _refund_credits_impl(payload: dict[str, Any]) -> bool:
    request_id = str(payload.get("request_id", ""))
    if not request_id:
        logger.error("event=ai_diet_refund_missing_request_id")
        return False
    state = AiDietState.create()

    profile_id = _resolve_profile_id(payload)
    if profile_id is None:
        logger.error(f"event=ai_diet_refund_missing_profile request_id={request_id}")
        return False
    cost = int(payload.get("cost", 0))
    if cost <= 0:
        logger.debug(f"event=ai_diet_refund_skip request_id={request_id} profile_id={profile_id} reason=invalid_cost")
        return False
    locked = await state.claim_refund(request_id, ttl_s=settings.AI_QA_DEDUP_TTL)
    if not locked:
        logger.debug(f"event=ai_diet_refund_skip request_id={request_id} reason=lock_held")
        return False
    release_lock = True
    try:
        if await state.is_refunded(request_id):
            logger.debug(f"event=ai_diet_refund_skip request_id={request_id} reason=already_refunded")
            return True
        if not await state.is_charged(request_id):
            logger.debug(f"event=ai_diet_refund_skip request_id={request_id} reason=not_charged")
            return False

        profile: Profile | None = None
        try:
            await APIService.profile.adjust_credits(profile_id, cost)
            profile = await APIService.profile.get_profile(profile_id)
        except APIClientHTTPError as exc:
            logger.error(
                f"event=ai_diet_refund_failed request_id={request_id} profile_id={profile_id} error={exc.reason}"
            )
            raise
        except Exception as exc:
            logger.error(f"event=ai_diet_refund_failed request_id={request_id} profile_id={profile_id} error={exc!s}")
            raise

        refunded_marked = False
        charged_cleared = False
        try:
            refunded_marked = await state.mark_refunded(request_id)
        except RedisError as exc:
            logger.warning(f"event=ai_diet_refund_mark_failed request_id={request_id} error={exc!s}")
        try:
            charged_cleared = await state.unmark_charged(request_id)
        except RedisError as exc:
            logger.warning(f"event=ai_diet_refund_clear_failed request_id={request_id} error={exc!s}")
        if not refunded_marked and not charged_cleared:
            release_lock = False
            logger.warning(f"event=ai_diet_refund_state_unstable request_id={request_id}")

        balance = profile.credits if profile is not None else None
        logger.debug(
            f"event=ai_diet_refund_ok request_id={request_id} profile_id={profile_id} cost={cost} balance={balance}"
        )
        return True
    finally:
        if release_lock:
            await state.release_refund_lock(request_id)


@app.task(
    bind=True,
    queue="ai_coach",
    routing_key="ai_coach",
    autoretry_for=(APIClientTransportError, APIClientHTTPError, RedisError),
    retry_backoff=settings.AI_QA_RETRY_BACKOFF_S,
    retry_jitter=True,
    max_retries=3,
    acks_late=True,
    task_acks_on_failure_or_timeout=False,
    soft_time_limit=AI_DIET_REFUND_SOFT_LIMIT,
    time_limit=AI_DIET_REFUND_TIME_LIMIT,
)
def refund_ai_diet_credits_task(self, payload: dict[str, Any]) -> None:  # pyrefly: ignore[valid-type]
    try:
        async_to_sync(_refund_credits_impl)(payload)
    except Exception:
        profile_id = _resolve_profile_id(payload)
        logger.error(f"event=ai_diet_refund_gave_up request_id={payload.get('request_id')} profile_id={profile_id}")
        raise


async def _claim_diet_request(request_id: str, state: AiDietState, *, attempt: int) -> bool:
    if not request_id or attempt > 0:
        return True
    claimed = await state.claim_task(request_id, ttl_s=settings.AI_QA_DEDUP_TTL)
    if not claimed:
        logger.debug(f"event=ai_diet_request_duplicate request_id={request_id}")
    return claimed


async def _notify_ai_diet_ready(payload: dict[str, Any]) -> None:
    base_url: str = settings.BOT_INTERNAL_URL.rstrip("/")
    url: str = f"{base_url}/internal/tasks/ai_diet_ready/"
    body = orjson.dumps(payload)
    headers = build_internal_hmac_auth_headers(
        key_id=settings.INTERNAL_KEY_ID,
        secret_key=settings.INTERNAL_API_KEY,
        body=body,
    )
    timeout = internal_request_timeout(settings)
    request_id = str(payload.get("request_id", ""))
    status = str(payload.get("status", "success"))
    if status == "duplicate":
        logger.debug(f"event=ai_diet_notify_skip request_id={request_id} status=duplicate")
        return
    force_delivery = bool(payload.get("force"))
    state = AiDietState.create()
    if request_id:
        if status == "success" and await state.is_delivered(request_id):
            logger.debug(f"event=ai_diet_notify_skip request_id={request_id} status=delivered")
            return
        if status != "success" and not force_delivery and await state.is_failed(request_id):
            logger.debug(f"event=ai_diet_notify_skip request_id={request_id} status=failed")
            return
    logger.info(f"event=ai_diet_notify_start request_id={request_id} status={status}")
    logger.info(f"event=ai_diet_notify_target request_id={request_id} base_url={base_url} url={url}")  # Diagnostic log
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response: httpx.Response = await client.post(url, content=body, headers=headers)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response is not None else None
        logger.error(
            "event=ai_diet_notify_http_error request_id={} status={} code={}",
            request_id,
            status,
            status_code,
        )
        raise
    except httpx.TransportError as exc:
        logger.error(f"event=ai_diet_notify_transport_error request_id={request_id} error={exc}")
        raise

    logger.info(f"event=ai_diet_notify_done request_id={request_id} status={status}")
    if request_id:
        if payload.get("status") == "success":
            await state.mark_delivered(request_id)
        else:
            await state.mark_failed(request_id, str(payload.get("error", "unknown")))
            _dispatch_refund_task(payload)


async def _handle_notify_diet_failure(payload: dict[str, Any], exc: Exception) -> None:
    request_id = str(payload.get("request_id", ""))
    profile_id = _resolve_profile_id(payload)
    detail = f"{type(exc).__name__}: {exc!s}"
    state = AiDietState.create()
    marked_failed = await state.mark_failed(request_id, detail)
    if marked_failed:
        logger.error(f"event=ai_diet_notify_gave_up request_id={request_id} profile_id={profile_id} detail={detail}")
        _dispatch_refund_task(payload)


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


async def _notify_ai_diet_error(
    *,
    profile_id: int | None,
    request_id: str,
    error: str,
    cost: int,
    credits_refunded: bool = False,
    dispatch: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": "error",
        "request_id": request_id,
        "error": error,
        "force": True,
        "cost": cost,
        "credits_refunded": credits_refunded,
        "error_code": error or "ai_diet_error",
        "localized_message_key": "coach_agent_error",
        "support_contact_action": True,
    }
    if profile_id is not None:
        payload["profile_id"] = profile_id
    if dispatch:
        notify_ai_diet_ready_task.apply_async(  # pyrefly: ignore[not-callable]
            args=[payload],
            queue="ai_coach",
            routing_key="ai_coach",
        )
    return payload


async def _handle_ai_diet_failure_impl(payload: dict[str, Any], detail: str) -> None:
    profile_id = _resolve_profile_id(payload)
    request_id = str(payload.get("request_id", ""))
    state = AiDietState.create()
    if request_id and await state.is_failed(request_id):
        logger.debug(f"event=ai_diet_failure_skip request_id={request_id} reason=already_failed")
        return
    marked_failed = await state.mark_failed(request_id, detail)
    if marked_failed:
        logger.error(f"event=ai_diet_gave_up request_id={request_id} profile_id={profile_id} detail={detail}")
        _dispatch_refund_task(payload)
    else:
        logger.debug(f"event=ai_diet_failure_skip request_id={request_id} reason=mark_failed_skipped")

    reason = detail or "task_failed"
    if marked_failed:
        await _notify_ai_diet_error(
            profile_id=profile_id,
            request_id=request_id,
            error=reason,
            cost=int(payload.get("cost", 0)),
            dispatch=True,
        )


async def _generate_diet_plan_impl(payload: dict[str, Any], task: Task) -> dict[str, Any] | None:
    profile_id = _resolve_profile_id(payload)
    request_id = str(payload.get("request_id", ""))
    if profile_id is None:
        logger.error(f"event=ai_diet_missing_profile request_id={request_id}")
        return await _notify_ai_diet_error(
            profile_id=None,
            request_id=request_id,
            error="missing_profile",
            cost=int(payload.get("cost", 0)),
        )
    language_raw = payload.get("language", settings.DEFAULT_LANG)
    language = str(language_raw or settings.DEFAULT_LANG)
    diet_allergies = str(payload.get("diet_allergies") or "").strip() or None
    diet_products_raw = payload.get("diet_products") or []
    diet_products = [str(item) for item in diet_products_raw if str(item).strip()]
    prompt_raw = payload.get("prompt", "")
    prompt = str(prompt_raw)
    cost = int(payload["cost"])
    attempt = getattr(task.request, "retries", 0)

    state = AiDietState.create()
    if not await _claim_diet_request(request_id, state, attempt=attempt):
        logger.debug(f"event=ai_diet_duplicate request_id={request_id} profile_id={profile_id}")
        return {
            "profile_id": profile_id,
            "request_id": request_id,
            "status": "duplicate",
        }

    if await state.mark_charged(request_id):
        profile: Profile | None = None
        try:
            await APIService.profile.adjust_credits(profile_id, -cost)
            profile = await APIService.profile.get_profile(profile_id)
        except APIClientHTTPError as exc:
            logger.error(
                f"event=ai_diet_charge_failed profile_id={profile_id} request_id={request_id} "
                f"status={exc.status} reason={exc.reason}"
            )
            if not exc.retryable:
                await state.unmark_charged(request_id)
            raise
        except Exception:
            logger.error(f"event=ai_diet_charge_failed profile_id={profile_id} request_id={request_id}")
            raise
        balance = profile.credits if profile is not None else None
        logger.info(
            f"event=ai_diet_charged request_id={request_id} profile_id={profile_id} cost={cost} balance={balance}"
        )
    else:
        try:
            already_charged = await state.is_charged(request_id)
        except RedisError as exc:
            logger.warning(
                f"event=ai_diet_charge_state_failed request_id={request_id} profile_id={profile_id} error={exc!s}"
            )
            raise
        if not already_charged:
            logger.warning(f"event=ai_diet_charge_state_missing request_id={request_id} profile_id={profile_id}")
            raise RedisError("ai_diet_charge_state_unavailable")
        logger.warning(f"event=ai_diet_charge_skipped request_id={request_id} profile_id={profile_id}")

    logger.debug(
        "event=ai_diet_started profile_id={} request_id={} attempt={}",
        profile_id,
        request_id,
        attempt,
    )

    from django.core.cache import cache

    cache.set(
        f"generation_status:{request_id}",
        {"status": "processing", "progress": 20, "stage": "agent_start"},
        timeout=settings.AI_COACH_TIMEOUT,
    )

    response: Any | None = None
    try:
        response = await APIService.ai_coach.create_diet_plan(
            profile_id=profile_id,
            language=language,
            diet_allergies=diet_allergies,
            diet_products=diet_products or None,
            prompt=prompt,
            request_id=request_id or None,
        )
        cache.set(
            f"generation_status:{request_id}",
            {"status": "processing", "progress": 90, "stage": "plan_received"},
            timeout=settings.AI_COACH_TIMEOUT,
        )
    except APIClientHTTPError as exc:
        logger.error(
            f"event=ai_diet_failed profile_id={profile_id} request_id={request_id} attempt={attempt} "
            f"status={exc.status} retryable={exc.retryable} reason={exc.reason}"
        )
        if not exc.retryable:
            refund_payload = {"request_id": request_id, "profile_id": profile_id, "cost": cost}
            refunded = await _attempt_inline_refund(refund_payload)
            error_payload = await _notify_ai_diet_error(
                profile_id=profile_id,
                request_id=request_id,
                error=exc.reason or f"http_{exc.status}",
                cost=cost,
                credits_refunded=refunded,
            )
            cache.set(
                f"generation_status:{request_id}",
                {
                    "status": "error",
                    "progress": 0,
                    "error": exc.reason or f"http_{exc.status}",
                    "error_code": error_payload.get("error_code", exc.reason or f"http_{exc.status}"),
                    "localized_message_key": error_payload.get("localized_message_key", "coach_agent_error"),
                    "credits_refunded": bool(error_payload.get("credits_refunded")),
                    "support_contact_action": bool(error_payload.get("support_contact_action", True)),
                    "request_id": request_id,
                },
                timeout=settings.AI_COACH_TIMEOUT,
            )
            return error_payload
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error(
            f"event=ai_diet_failed profile_id={profile_id} request_id={request_id} attempt={attempt} error={exc}"
        )
        if attempt >= getattr(task, "max_retries", 0):
            refund_payload = {"request_id": request_id, "profile_id": profile_id, "cost": cost}
            refunded = await _attempt_inline_refund(refund_payload)
            error_payload = await _notify_ai_diet_error(
                profile_id=profile_id,
                request_id=request_id,
                error=str(exc),
                cost=cost,
                credits_refunded=refunded,
            )
            cache.set(
                f"generation_status:{request_id}",
                {
                    "status": "error",
                    "progress": 0,
                    "error": str(exc),
                    "error_code": error_payload.get("error_code", str(exc)),
                    "localized_message_key": error_payload.get("localized_message_key", "coach_agent_error"),
                    "credits_refunded": bool(error_payload.get("credits_refunded")),
                    "support_contact_action": bool(error_payload.get("support_contact_action", True)),
                    "request_id": request_id,
                },
                timeout=settings.AI_COACH_TIMEOUT,
            )
            return error_payload

    if response is None:
        logger.error(f"event=ai_diet_empty_response profile_id={profile_id} request_id={request_id}")
        refund_payload = {"request_id": request_id, "profile_id": profile_id, "cost": cost}
        refunded = await _attempt_inline_refund(refund_payload)
        error_payload = await _notify_ai_diet_error(
            profile_id=profile_id,
            request_id=request_id,
            error="empty_response",
            cost=cost,
            credits_refunded=refunded,
        )
        cache.set(
            f"generation_status:{request_id}",
            {
                "status": "error",
                "progress": 0,
                "error": "empty_response",
                "error_code": error_payload.get("error_code", "empty_response"),
                "localized_message_key": error_payload.get("localized_message_key", "coach_agent_error"),
                "credits_refunded": bool(error_payload.get("credits_refunded")),
                "support_contact_action": bool(error_payload.get("support_contact_action", True)),
                "request_id": request_id,
            },
            timeout=settings.AI_COACH_TIMEOUT,
        )
        return error_payload

    diet_plan = response if isinstance(response, DietPlan) else DietPlan.model_validate(response)
    notify_payload: dict[str, Any] = {
        "profile_id": profile_id,
        "status": "success",
        "request_id": request_id,
        "plan": diet_plan.model_dump(mode="json"),
        "cost": cost,
    }
    logger.info(
        "event=ai_diet_completed profile_id={} request_id={} meals={}",
        profile_id,
        request_id,
        len(diet_plan.meals),
    )
    await emit_metrics_event(
        METRICS_EVENT_DIET_PLAN,
        source=METRICS_SOURCE_DIET,
        source_id=request_id,
    )
    cache.set(
        f"generation_status:{request_id}",
        {"status": "success", "progress": 100, "stage": "completed", "result_id": diet_plan.id},
        timeout=settings.AI_COACH_TIMEOUT,
    )
    return notify_payload


@app.task(
    bind=True,
    queue="ai_coach",
    routing_key="ai_coach",
    autoretry_for=(APIClientTransportError, RedisError),
    retry_backoff=settings.AI_QA_RETRY_BACKOFF_S,
    retry_jitter=True,
    max_retries=settings.AI_QA_MAX_RETRIES,
    acks_late=True,
    task_acks_on_failure_or_timeout=False,
    soft_time_limit=AI_DIET_SOFT_TIME_LIMIT,
    time_limit=AI_DIET_TIME_LIMIT,
)
def generate_ai_diet_plan(self, payload: dict[str, Any]) -> dict[str, Any] | None:  # pyrefly: ignore[valid-type]
    try:
        notify_payload = async_to_sync(_generate_diet_plan_impl)(payload, self)
    except APIClientHTTPError as exc:
        retries = int(getattr(self.request, "retries", 0))
        max_retries = int(getattr(self, "max_retries", 0) or 0)
        if exc.retryable and retries < max_retries:
            logger.warning(
                f"event=ai_diet_retry request_id={payload.get('request_id', '')} status={exc.status} attempt={retries}"
            )
            raise self.retry(exc=exc)
        raise
    else:
        return notify_payload


@app.task(
    bind=True,
    queue="ai_coach",
    routing_key="ai_coach",
    autoretry_for=(httpx.RequestError, httpx.HTTPStatusError),
    retry_backoff=settings.AI_QA_RETRY_BACKOFF_S,
    retry_jitter=True,
    max_retries=settings.AI_QA_MAX_RETRIES,
    acks_late=True,
    task_acks_on_failure_or_timeout=False,
    soft_time_limit=AI_DIET_NOTIFY_SOFT_LIMIT,
    time_limit=AI_DIET_NOTIFY_TIME_LIMIT,
)
def notify_ai_diet_ready_task(self, payload: dict[str, Any]) -> None:  # pyrefly: ignore[valid-type]
    if not isinstance(payload, dict):
        logger.error(f"event=ai_diet_notify_invalid_payload payload_type={type(payload)!r}")
        return
    try:
        async_to_sync(_notify_ai_diet_ready)(payload)
    except Exception as exc:  # noqa: BLE001
        async_to_sync(_handle_notify_diet_failure)(payload, exc)
        raise


@app.task(
    bind=True,
    queue="ai_coach",
    routing_key="ai_coach",
    acks_late=True,
    task_acks_on_failure_or_timeout=False,
    soft_time_limit=AI_DIET_NOTIFY_SOFT_LIMIT,
    time_limit=AI_DIET_NOTIFY_TIME_LIMIT,
)
def handle_ai_diet_failure(self, payload: Any, *exc_info: Any) -> None:  # pyrefly: ignore[valid-type]
    def _coerce_payload(obj: Any) -> dict[str, Any]:
        if isinstance(obj, dict):
            return obj
        if isinstance(obj, (bytes, str)):
            try:
                return orjson.loads(obj)
            except orjson.JSONDecodeError:
                try:
                    text = obj.decode() if isinstance(obj, bytes) else str(obj)
                except Exception:
                    text = repr(obj)
                return {"raw": text}
        return {"raw": repr(obj)}

    detail = _extract_failure_detail(exc_info)
    safe_payload = _coerce_payload(payload)
    preview = str(safe_payload)[:200]
    logger.warning(f"event=ai_diet_failure_payload shape={type(payload).__name__} preview={preview}")
    async_to_sync(_handle_ai_diet_failure_impl)(safe_payload, detail)
