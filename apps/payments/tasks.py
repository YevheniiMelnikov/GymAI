from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

import httpx


from loguru import logger

from config.app_settings import settings
from core.celery_app import app
from core.internal_http import build_internal_auth_headers, internal_request_timeout


def _internal_headers() -> dict[str, str]:
    return build_internal_auth_headers(
        internal_api_key=settings.INTERNAL_API_KEY,
        fallback_api_key=settings.API_KEY,
    )


def _internal_url(path: str) -> str:
    base = settings.BOT_INTERNAL_URL.rstrip("/")
    suffix = path if path.startswith("/") else f"/{path}"
    return f"{base}{suffix}"


async def _post_internal_json(path: str, payload: dict[str, Any]) -> None:
    url = _internal_url(path)
    headers = _internal_headers()
    timeout = internal_request_timeout(settings)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()


def _retryable_call(
    task: Any,
    description: str,
    coro_factory: Callable[[], Awaitable[None]],
) -> None:
    try:
        asyncio.run(coro_factory())
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code if exc.response is not None else None
        logger.warning(f"bot_call_failed status={status} description={description} error={exc}")
        raise task.retry(exc=exc)
    except httpx.TransportError as exc:
        logger.warning(f"bot_call_transport_error description={description} error={exc}")
        raise task.retry(exc=exc)


@app.task(bind=True, max_retries=3, retry_backoff=30, retry_backoff_max=300)  # pyrefly: ignore[not-callable]
def process_payment_webhook(
    self,
    order_id: str,
    status: str,
    err_description: str = "",
) -> None:
    payload: dict[str, Any] = {
        "order_id": order_id,
        "status": status,
        "err_description": err_description,
    }

    def runner() -> Awaitable[None]:
        return _post_internal_json("/internal/payments/process/", payload)

    _retryable_call(self, f"payment_webhook order_id={order_id}", runner)


@app.task(bind=True, max_retries=3, retry_backoff=30, retry_backoff_max=300)  # pyrefly: ignore[not-callable]
def send_payment_message(self, client_profile_id: int, text: str) -> None:
    payload: dict[str, Any] = {"client_id": client_profile_id, "text": text}

    def runner() -> Awaitable[None]:
        return _post_internal_json("/internal/payments/send_message/", payload)

    _retryable_call(self, f"payment_message client_profile_id={client_profile_id}", runner)


@app.task(bind=True, max_retries=3, retry_backoff=30, retry_backoff_max=300)  # pyrefly: ignore[not-callable]
def send_client_request(
    self,
    coach_profile_id: int,
    client_profile_id: int,
    data: dict[str, Any],
) -> None:
    payload: dict[str, Any] = {
        "coach_id": coach_profile_id,
        "client_id": client_profile_id,
        "data": data,
    }

    def runner() -> Awaitable[None]:
        return _post_internal_json("/internal/payments/client_request/", payload)

    description = f"client_request client_profile_id={client_profile_id} coach_profile_id={coach_profile_id}"
    _retryable_call(self, description, runner)


__all__ = [
    "process_payment_webhook",
    "send_payment_message",
    "send_client_request",
]
