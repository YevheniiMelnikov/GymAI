"""Celery tasks that proxy calls to the bot service."""

from __future__ import annotations

import httpx
from loguru import logger

from config.app_settings import settings
from core.celery_app import app
from core.internal_http import build_internal_auth_headers, internal_request_timeout

__all__ = [
    "export_coach_payouts",
    "send_daily_survey",
    "send_workout_result",
    "prune_cognee",
]


def _bot_request_path(path: str) -> str:
    base_url = settings.BOT_INTERNAL_URL.rstrip("/")
    return f"{base_url}{path}"


def _bot_headers() -> dict[str, str]:
    return build_internal_auth_headers(
        internal_api_key=settings.INTERNAL_API_KEY,
        fallback_api_key=settings.API_KEY,
    )


@app.task(
    bind=True,
    autoretry_for=(httpx.HTTPError,),
    retry_backoff=180,
    retry_jitter=True,
    max_retries=3,
)  # pyrefly: ignore[not-callable]
def export_coach_payouts(self) -> None:
    logger.info("export_coach_payouts started")
    url = _bot_request_path("/internal/tasks/export_coach_payouts/")
    headers = _bot_headers()
    timeout = internal_request_timeout(settings)

    try:
        resp = httpx.post(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning(f"Bot call failed for coach payouts: {exc}")
        raise self.retry(exc=exc)
    logger.info("export_coach_payouts completed")


@app.task(
    bind=True,
    autoretry_for=(httpx.HTTPError,),
    retry_backoff=180,
    retry_jitter=True,
    max_retries=3,
)  # pyrefly: ignore[not-callable]
def send_daily_survey(self) -> None:
    url = _bot_request_path("/internal/tasks/send_daily_survey/")
    headers = _bot_headers()
    timeout = internal_request_timeout(settings)

    try:
        resp = httpx.post(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning(f"Bot call failed for daily survey: {exc!s}")
        raise self.retry(exc=exc)


@app.task(
    bind=True,
    autoretry_for=(httpx.HTTPError,),
    retry_backoff=180,
    retry_jitter=True,
    max_retries=3,
)  # pyrefly: ignore[not-callable]
def send_workout_result(self, coach_profile_id: int, client_profile_id: int, text: str) -> None:
    """Forward workout survey results to the appropriate recipient."""
    url = _bot_request_path("/internal/tasks/send_workout_result/")
    headers = _bot_headers()
    timeout = internal_request_timeout(settings)
    payload = {
        "coach_id": coach_profile_id,
        "client_id": client_profile_id,
        "text": text,
    }

    try:
        resp = httpx.post(url, json=payload, timeout=timeout, headers=headers)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning(f"Bot call failed for workout result: {exc!s}")
        raise self.retry(exc=exc)


@app.task(
    bind=True,
    autoretry_for=(httpx.HTTPError,),
    retry_backoff=180,
    retry_jitter=True,
    max_retries=3,
)  # pyrefly: ignore[not-callable]
def prune_cognee(self) -> None:
    """Remove cached Cognee data storage."""
    logger.info("prune_cognee started")
    url = _bot_request_path("/internal/tasks/prune_cognee/")
    headers = _bot_headers()
    timeout = internal_request_timeout(settings)

    try:
        resp = httpx.post(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning(f"Bot call failed for prune_cognee: {exc}")
        raise self.retry(exc=exc)
    logger.info("prune_cognee completed")
