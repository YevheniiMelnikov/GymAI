"""Celery tasks for Ask AI question flow."""

from typing import Any

import httpx
from asgiref.sync import async_to_sync
from celery import Task
from loguru import logger

import orjson

from config.app_settings import settings
from core.ai_coach.state.ask_ai import AiQuestionState
from core.celery_app import app
from core.internal_http import build_internal_hmac_auth_headers, internal_request_timeout
from core.schemas import Profile, QAResponse
from core.services import APIService
from core.services.internal.api_client import APIClientHTTPError, APIClientTransportError

__all__ = [
    "ask_ai_question",
    "notify_ai_answer_ready_task",
    "handle_ai_question_failure",
    "refund_ai_qa_credits_task",
]

AI_QA_SOFT_TIME_LIMIT = settings.AI_COACH_TIMEOUT
AI_QA_TIME_LIMIT = AI_QA_SOFT_TIME_LIMIT + 30
AI_QA_NOTIFY_SOFT_LIMIT = settings.AI_PLAN_NOTIFY_TIMEOUT
AI_QA_NOTIFY_TIME_LIMIT = AI_QA_NOTIFY_SOFT_LIMIT + 30
AI_QA_REFUND_SOFT_LIMIT = 120
AI_QA_REFUND_TIME_LIMIT = 150


def _resolve_profile_id(payload: dict[str, Any]) -> int | None:
    raw = payload.get("profile_id")
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


async def _refund_credits_impl(payload: dict[str, Any]) -> None:
    request_id = str(payload["request_id"])
    state = AiQuestionState.create()
    if not await state.is_charged(request_id) or not await state.unmark_charged(request_id):
        logger.debug(f"event=ask_ai_refund_skip request_id={request_id}")
        return

    profile_id = _resolve_profile_id(payload)
    if profile_id is None:
        logger.error(f"event=ask_ai_refund_missing_profile request_id={request_id}")
        return
    cost = int(payload["cost"])
    profile: Profile | None = None
    try:
        await APIService.profile.adjust_credits(profile_id, cost)
        profile = await APIService.profile.get_profile(profile_id)
    except APIClientHTTPError as exc:
        logger.error(f"event=ask_ai_refund_failed request_id={request_id} profile_id={profile_id} error={exc.reason}")
        raise
    except Exception as exc:
        logger.error(f"event=ask_ai_refund_failed request_id={request_id} profile_id={profile_id} error={exc!s}")
        raise

    balance = profile.credits if profile is not None else None
    logger.debug(
        f"event=ask_ai_refund_ok request_id={request_id} profile_id={profile_id} cost={cost} balance={balance}"
    )


@app.task(
    bind=True,
    queue="ai_coach",
    routing_key="ai_coach",
    autoretry_for=(APIClientTransportError, APIClientHTTPError),
    retry_backoff=settings.AI_QA_RETRY_BACKOFF_S,
    retry_jitter=True,
    max_retries=3,
    acks_late=True,
    task_acks_on_failure_or_timeout=False,
    soft_time_limit=AI_QA_REFUND_SOFT_LIMIT,
    time_limit=AI_QA_REFUND_TIME_LIMIT,
)
def refund_ai_qa_credits_task(self, payload: dict[str, Any]) -> None:  # pyrefly: ignore[valid-type]
    try:
        async_to_sync(_refund_credits_impl)(payload)
    except Exception:
        profile_id = _resolve_profile_id(payload)
        logger.error(f"event=ask_ai_refund_gave_up request_id={payload.get('request_id')} profile_id={profile_id}")
        raise


async def _claim_answer_request(request_id: str, state: AiQuestionState, *, attempt: int) -> bool:
    """Deduplicate task execution without touching delivery claim state."""
    if not request_id or attempt > 0:
        return True
    claimed = await state.claim_task(request_id, ttl_s=settings.AI_QA_DEDUP_TTL)
    if not claimed:
        logger.debug(f"event=ask_ai_request_duplicate request_id={request_id}")
    return claimed


async def _notify_ai_answer_ready(payload: dict[str, Any]) -> None:
    base_url: str = settings.BOT_INTERNAL_URL.rstrip("/")
    url: str = f"{base_url}/internal/tasks/ai_answer_ready/"
    body = orjson.dumps(payload)
    headers = build_internal_hmac_auth_headers(
        key_id=settings.INTERNAL_KEY_ID,
        secret_key=settings.INTERNAL_API_KEY,
        body=body,
    )
    timeout = internal_request_timeout(settings)
    request_id = str(payload.get("request_id", ""))
    status = str(payload.get("status", "success"))
    force_delivery = bool(payload.get("force"))
    if status == "duplicate":
        logger.debug(f"event=ask_ai_notify_skip request_id={request_id} status=duplicate")
        return
    state = AiQuestionState.create()
    if request_id:
        if status == "success" and await state.is_delivered(request_id):
            logger.debug(f"event=ask_ai_notify_skip request_id={request_id} status=delivered")
            return
        if status != "success" and not force_delivery and await state.is_failed(request_id):
            logger.debug(f"event=ask_ai_notify_skip request_id={request_id} status=failed")
            return
    logger.info(f"event=ask_ai_notify_start request_id={request_id} status={status}")
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response: httpx.Response = await client.post(url, content=body, headers=headers)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response is not None else None
        body_preview = ""
        if exc.response is not None:
            try:
                body_preview = exc.response.text
            except Exception:
                body_preview = "<unavailable>"
        logger.error(
            "event=ask_ai_notify_http_error request_id={} status={} code={} body={}",
            request_id,
            status,
            status_code,
            (body_preview[:500] if body_preview else ""),
        )
        raise
    except httpx.TransportError as exc:
        logger.error(f"event=ask_ai_notify_transport_error request_id={request_id} error={exc}")
        raise

    logger.info(f"event=ask_ai_notify_done request_id={request_id} status={status}")
    if payload.get("status") == "success":
        await state.mark_delivered(request_id)
    else:
        await state.mark_failed(request_id, str(payload.get("error", "unknown")))


async def _handle_notify_answer_failure(payload: dict[str, Any], exc: Exception) -> None:
    request_id = str(payload.get("request_id", ""))
    profile_id = _resolve_profile_id(payload)
    detail = f"{type(exc).__name__}: {exc!s}"
    state = AiQuestionState.create()
    marked_failed = await state.mark_failed(request_id, detail)
    if marked_failed:
        logger.error(f"event=ask_ai_notify_gave_up request_id={request_id} profile_id={profile_id} detail={detail}")
        if profile_id is not None and await state.is_charged(request_id):
            refund_payload = {
                "request_id": request_id,
                "profile_id": profile_id,
                "cost": payload.get("cost", 0),
            }
            refund_ai_qa_credits_task.apply_async(  # pyrefly: ignore[not-callable]
                args=[refund_payload],
                queue="ai_coach",
                routing_key="ai_coach",
            )
    status = str(payload.get("status") or "success").lower()
    if status == "success" and marked_failed:
        fallback_error = f"delivery_failed:{type(exc).__name__}"
        await _notify_ai_answer_error(
            profile_id=profile_id,
            request_id=request_id,
            error=fallback_error,
            dispatch=True,
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


async def _notify_ai_answer_error(
    *,
    profile_id: int | None,
    request_id: str,
    error: str,
    dispatch: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": "error",
        "request_id": request_id,
        "error": error,
        "force": True,
    }
    if profile_id is not None:
        payload["profile_id"] = profile_id
    if dispatch:
        notify_ai_answer_ready_task.apply_async(  # pyrefly: ignore[not-callable]
            args=[payload],
            queue="ai_coach",
            routing_key="ai_coach",
        )
    return payload


async def _handle_ai_answer_failure_impl(payload: dict[str, Any], detail: str) -> None:
    profile_id = _resolve_profile_id(payload)
    request_id = str(payload.get("request_id", ""))
    state = AiQuestionState.create()
    if request_id and await state.is_failed(request_id):
        logger.debug(f"event=ask_ai_failure_skip request_id={request_id} reason=already_failed")
        return
    marked_failed = await state.mark_failed(request_id, detail)
    if marked_failed:
        logger.error(f"event=ask_ai_gave_up request_id={request_id} profile_id={profile_id} detail={detail}")
        if profile_id is not None and await state.is_charged(request_id):
            refund_payload = {
                "request_id": request_id,
                "profile_id": profile_id,
                "cost": payload.get("cost", 0),
            }
            refund_ai_qa_credits_task.apply_async(  # pyrefly: ignore[not-callable]
                args=[refund_payload],
                queue="ai_coach",
                routing_key="ai_coach",
            )
    else:
        logger.debug(f"event=ask_ai_failure_skip request_id={request_id} reason=mark_failed_skipped")

    reason = detail or "task_failed"
    if marked_failed:
        await _notify_ai_answer_error(
            profile_id=profile_id,
            request_id=request_id,
            error=reason,
            dispatch=True,
        )


async def _ask_ai_question_impl(payload: dict[str, Any], task: Task) -> dict[str, Any] | None:
    profile_id = _resolve_profile_id(payload)
    request_id = str(payload.get("request_id", ""))
    if profile_id is None:
        logger.error(f"event=ask_ai_missing_profile request_id={request_id}")
        return await _notify_ai_answer_error(
            profile_id=None,
            request_id=request_id,
            error="missing_profile",
        )
    language_raw = payload.get("language", settings.DEFAULT_LANG)
    language = str(language_raw or settings.DEFAULT_LANG)
    prompt_raw = payload.get("prompt", "")
    prompt = str(prompt_raw)
    raw_attachments = payload.get("attachments") or []
    attachments: list[dict[str, str]] = []
    for item in raw_attachments:
        if not isinstance(item, dict):
            continue
        mime_val = str(item.get("mime") or "").strip()
        data_val = str(item.get("data_base64") or "").strip()
        if not mime_val or not data_val:
            continue
        attachments.append({"mime": mime_val, "data_base64": data_val})
    attempt = getattr(task.request, "retries", 0)

    cost = int(payload["cost"])

    state = AiQuestionState.create()
    if not await _claim_answer_request(request_id, state, attempt=attempt):
        logger.debug(f"event=ask_ai_duplicate request_id={request_id} profile_id={profile_id}")
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
                f"event=ask_ai_charge_failed profile_id={profile_id} request_id={request_id} "
                f"status={exc.status} reason={exc.reason}"
            )
            if not exc.retryable:
                await state.unmark_charged(request_id)
            raise
        except Exception:
            logger.error(f"event=ask_ai_charge_failed profile_id={profile_id} request_id={request_id}")
            raise
        balance = profile.credits if profile is not None else None
        logger.info(
            f"event=ask_ai_charged request_id={request_id} profile_id={profile_id} cost={cost} balance={balance}"
        )
    else:
        logger.warning(f"event=ask_ai_charge_skipped request_id={request_id} profile_id={profile_id}")

        logger.debug(
            (
                f"event=ask_ai_started profile_id={profile_id} request_id={request_id} "
                f"attempt={attempt} attachments={len(attachments)}"
            )
        )

    response: Any | None = None
    try:
        response = await APIService.ai_coach.ask(
            prompt,
            profile_id=profile_id,
            language=language,
            request_id=request_id or None,
            attachments=attachments or None,
        )
    except APIClientHTTPError as exc:
        logger.error(
            f"event=ask_ai_failed profile_id={profile_id} request_id={request_id} attempt={attempt} "
            f"status={exc.status} retryable={exc.retryable} reason={exc.reason}"
        )
        if not exc.retryable:
            return await _notify_ai_answer_error(
                profile_id=profile_id,
                request_id=request_id,
                error=exc.reason or f"http_{exc.status}",
            )
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error(
            f"event=ask_ai_failed profile_id={profile_id} request_id={request_id} attempt={attempt} error={exc}"
        )
        if attempt >= getattr(task, "max_retries", 0):
            return await _notify_ai_answer_error(
                profile_id=profile_id,
                request_id=request_id,
                error=str(exc),
            )

    if response is None:
        logger.error(f"event=ask_ai_empty_response profile_id={profile_id} request_id={request_id}")
        return await _notify_ai_answer_error(
            profile_id=profile_id,
            request_id=request_id,
            error="empty_response",
        )

    qa_response = response if isinstance(response, QAResponse) else QAResponse.model_validate(response)
    sources = list(qa_response.sources)
    kb_used = any(src != "general_knowledge" for src in sources) if sources else False
    if sources:
        logger.info(
            "event=ask_ai_sources request_id={} profile_id={} count={}",
            request_id,
            profile_id,
            len(sources),
        )
        if settings.AI_COACH_LOG_PAYLOADS:
            sources_label = " | ".join(sources)
            if len(sources_label) > 300:
                sources_label = sources_label[:297] + "..."
            logger.debug(
                "event=ask_ai_sources_payload request_id={} profile_id={} sources={}",
                request_id,
                profile_id,
                sources_label,
            )
    notify_payload: dict[str, Any] = {
        "profile_id": profile_id,
        "status": "success",
        "request_id": request_id,
        "answer": qa_response.answer,
        "cost": cost,
    }
    if qa_response.blocks:
        notify_payload["blocks"] = [
            block.model_dump(mode="json") if hasattr(block, "model_dump") else dict(block)
            for block in qa_response.blocks
            if block
        ]
    if sources:
        notify_payload["sources"] = sources

    answer_len = len(qa_response.answer or "")
    logger.info(
        "event=ask_ai_completed profile_id={} request_id={} answer_len={} kb_used={}",
        profile_id,
        request_id,
        answer_len,
        str(kb_used).lower(),
    )
    return notify_payload


@app.task(
    bind=True,
    queue="ai_coach",
    routing_key="ai_coach",
    autoretry_for=(APIClientTransportError,),
    retry_backoff=settings.AI_QA_RETRY_BACKOFF_S,
    retry_jitter=True,
    max_retries=settings.AI_QA_MAX_RETRIES,
    acks_late=True,
    task_acks_on_failure_or_timeout=False,
    soft_time_limit=AI_QA_SOFT_TIME_LIMIT,
    time_limit=AI_QA_TIME_LIMIT,
)
def ask_ai_question(self, payload: dict[str, Any]) -> dict[str, Any] | None:  # pyrefly: ignore[valid-type]
    try:
        notify_payload = async_to_sync(_ask_ai_question_impl)(payload, self)
    except APIClientHTTPError as exc:
        retries = int(getattr(self.request, "retries", 0))
        max_retries = int(getattr(self, "max_retries", 0) or 0)
        if exc.retryable and retries < max_retries:
            logger.warning(
                f"event=ask_ai_retry request_id={payload.get('request_id', '')} status={exc.status} attempt={retries}"
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
    soft_time_limit=AI_QA_NOTIFY_SOFT_LIMIT,
    time_limit=AI_QA_NOTIFY_TIME_LIMIT,
)
def notify_ai_answer_ready_task(self, payload: dict[str, Any]) -> None:  # pyrefly: ignore[valid-type]
    if not isinstance(payload, dict):
        logger.error(f"event=ask_ai_notify_invalid_payload payload_type={type(payload)!r}")
        return
    try:
        async_to_sync(_notify_ai_answer_ready)(payload)
    except Exception as exc:  # noqa: BLE001
        async_to_sync(_handle_notify_answer_failure)(payload, exc)
        raise


@app.task(
    bind=True,
    queue="ai_coach",
    routing_key="ai_coach",
    acks_late=True,
    task_acks_on_failure_or_timeout=False,
    soft_time_limit=AI_QA_NOTIFY_SOFT_LIMIT,
    time_limit=AI_QA_NOTIFY_TIME_LIMIT,
)
def handle_ai_question_failure(self, payload: Any, *exc_info: Any) -> None:  # pyrefly: ignore[valid-type]
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
    logger.warning(f"event=ask_ai_failure_payload shape={type(payload).__name__} preview={preview}")
    async_to_sync(_handle_ai_answer_failure_impl)(safe_payload, detail)
