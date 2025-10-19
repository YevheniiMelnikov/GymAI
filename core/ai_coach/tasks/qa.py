"""Celery tasks for Ask AI question flow."""

import asyncio
from typing import Any

import httpx
from celery import Task
from loguru import logger

from config.app_settings import settings
from core.ai_coach import AiQuestionState
from core.celery_app import app
from core.internal_http import build_internal_auth_headers, internal_request_timeout
from core.schemas import QAResponse
from core.services import APIService
from core.services.internal.api_client import APIClientHTTPError, APIClientTransportError

__all__ = [
    "ask_ai_question",
    "notify_ai_answer_ready_task",
    "handle_ai_question_failure",
]

AI_QA_SOFT_TIME_LIMIT = settings.AI_COACH_TIMEOUT
AI_QA_TIME_LIMIT = AI_QA_SOFT_TIME_LIMIT + 30
AI_QA_NOTIFY_SOFT_LIMIT = settings.AI_PLAN_NOTIFY_TIMEOUT
AI_QA_NOTIFY_TIME_LIMIT = AI_QA_NOTIFY_SOFT_LIMIT + 30


async def _claim_answer_request(request_id: str, *, attempt: int) -> bool:
    if not request_id or attempt > 0:
        return True
    state = AiQuestionState.create()
    claimed = await state.claim_task(request_id, ttl_s=settings.AI_QA_DEDUP_TTL)
    if not claimed:
        logger.debug(f"event=ask_ai_request_duplicate request_id={request_id}")
    return claimed


async def _notify_ai_answer_ready(payload: dict[str, Any]) -> None:
    base_url: str = settings.BOT_INTERNAL_URL.rstrip("/")
    url: str = f"{base_url}/internal/tasks/ai_answer_ready/"
    headers = build_internal_auth_headers(
        internal_api_key=settings.INTERNAL_API_KEY,
        fallback_api_key=settings.API_KEY,
    )
    timeout = internal_request_timeout(settings)
    request_id = str(payload.get("request_id", ""))
    status = str(payload.get("status", "success"))
    state = AiQuestionState.create()
    if request_id:
        if status == "success" and await state.is_delivered(request_id):
            logger.debug(f"event=ask_ai_notify_skip request_id={request_id} status=delivered")
            return
        if status != "success" and await state.is_failed(request_id):
            logger.debug(f"event=ask_ai_notify_skip request_id={request_id} status=failed")
            return
    logger.info(f"event=ask_ai_notify_start request_id={request_id} status={status}")
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response: httpx.Response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response is not None else None
        logger.error(f"event=ask_ai_notify_http_error request_id={request_id} status={status} code={status_code}")
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
    client_id = payload.get("client_id")
    detail = f"{type(exc).__name__}: {exc!s}"
    state = AiQuestionState.create()
    await state.mark_failed(request_id, detail)
    logger.error(f"event=ask_ai_notify_gave_up request_id={request_id} client_id={client_id} detail={detail}")


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
    client_id: int,
    client_profile_id: int | None,
    request_id: str,
    error: str,
) -> None:
    payload: dict[str, Any] = {
        "client_id": client_id,
        "status": "error",
        "request_id": request_id,
        "error": error,
    }
    if client_profile_id is not None and client_profile_id > 0:
        payload["client_profile_id"] = client_profile_id
    notify_ai_answer_ready_task.apply_async(
        args=[payload],
        queue="ai_coach",
        routing_key="ai_coach",
    )


async def _handle_ai_answer_failure_impl(payload: dict[str, Any], detail: str) -> None:
    client_id = int(payload.get("client_id", 0))
    request_id = str(payload.get("request_id", ""))
    client_profile_raw = payload.get("client_profile_id")
    try:
        client_profile_id = int(client_profile_raw) if client_profile_raw is not None else None
    except (TypeError, ValueError):
        client_profile_id = None
    reason = detail or "task_failed"
    await _notify_ai_answer_error(
        client_id=client_id,
        client_profile_id=client_profile_id,
        request_id=request_id,
        error=reason,
    )
    if request_id:
        state = AiQuestionState.create()
        await state.mark_failed(request_id, reason)


async def _ask_ai_question_impl(payload: dict[str, Any], task: Task) -> dict[str, Any] | None:
    client_id = int(payload["client_id"])
    client_profile_id_raw = payload.get("client_profile_id")
    try:
        client_profile_id = int(client_profile_id_raw) if client_profile_id_raw is not None else 0
    except (TypeError, ValueError):
        request_hint = payload.get("request_id", "")
        logger.warning(
            f"event=ask_ai_invalid_profile client_id={client_id} "
            f"raw={client_profile_id_raw!r} request_id={request_hint}"
        )
        client_profile_id = 0

    request_id = str(payload.get("request_id", ""))
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

    if not await _claim_answer_request(request_id, attempt=attempt):
        logger.info(f"event=ask_ai_duplicate request_id={request_id} client_id={client_id}")
        return None

    logger.info(
        (
            f"event=ask_ai_started client_id={client_id} request_id={request_id} "
            f"attempt={attempt} attachments={len(attachments)}"
        )
    )

    try:
        response = await APIService.ai_coach.ask(
            prompt,
            client_id=client_id,
            language=language,
            request_id=request_id or None,
            attachments=attachments or None,
        )
    except APIClientHTTPError as exc:
        logger.error(
            f"event=ask_ai_failed client_id={client_id} request_id={request_id} attempt={attempt} "
            f"status={exc.status} retryable={exc.retryable} reason={exc.reason}"
        )
        if not exc.retryable:
            await _notify_ai_answer_error(
                client_id=client_id,
                client_profile_id=client_profile_id or None,
                request_id=request_id,
                error=exc.reason or f"http_{exc.status}",
            )
            return None
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error(f"event=ask_ai_failed client_id={client_id} request_id={request_id} attempt={attempt} error={exc}")
        if attempt >= getattr(task, "max_retries", 0):
            await _notify_ai_answer_error(
                client_id=client_id,
                client_profile_id=client_profile_id or None,
                request_id=request_id,
                error=str(exc),
            )
        raise

    if response is None:
        logger.error(f"event=ask_ai_empty_response client_id={client_id} request_id={request_id}")
        await _notify_ai_answer_error(
            client_id=client_id,
            client_profile_id=client_profile_id or None,
            request_id=request_id,
            error="empty_response",
        )
        return None

    qa_response = response if isinstance(response, QAResponse) else QAResponse.model_validate(response)
    sources = list(qa_response.sources)
    if sources:
        logger.info(
            "event=ask_ai_sources request_id={} client_id={} count={} sources={}",
            request_id,
            client_id,
            len(sources),
            " | ".join(sources),
        )
    notify_payload: dict[str, Any] = {
        "client_id": client_id,
        "client_profile_id": client_profile_id,
        "status": "success",
        "request_id": request_id,
        "answer": qa_response.answer,
    }
    if sources:
        notify_payload["sources"] = sources

    logger.info(f"event=ask_ai_completed client_id={client_id} request_id={request_id}")
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
        notify_payload = asyncio.run(_ask_ai_question_impl(payload, self))
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
    acks_late=True,
    task_acks_on_failure_or_timeout=False,
    soft_time_limit=AI_QA_NOTIFY_SOFT_LIMIT,
    time_limit=AI_QA_NOTIFY_TIME_LIMIT,
)
def notify_ai_answer_ready_task(self, payload: dict[str, Any]) -> None:  # pyrefly: ignore[valid-type]
    try:
        asyncio.run(_notify_ai_answer_ready(payload))
    except Exception as exc:  # noqa: BLE001
        asyncio.run(_handle_notify_answer_failure(payload, exc))
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
def handle_ai_question_failure(self, payload: dict[str, Any], *exc_info: Any) -> None:  # pyrefly: ignore[valid-type]
    detail = _extract_failure_detail(exc_info)
    asyncio.run(_handle_ai_answer_failure_impl(payload, detail))
