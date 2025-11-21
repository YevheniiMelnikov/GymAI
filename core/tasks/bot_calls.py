"""Celery tasks that proxy calls to the bot service."""

import httpx
from loguru import logger

from config.app_settings import settings
from core.celery_app import app
from core.internal_http import build_internal_hmac_auth_headers, internal_request_timeout

__all__ = [
    "send_daily_survey",
]


def _bot_request_path(path: str) -> str:
    base_url = settings.BOT_INTERNAL_URL.rstrip("/")
    return f"{base_url}{path}"


def _bot_headers(body: bytes = b"") -> dict[str, str]:
    return build_internal_hmac_auth_headers(
        key_id=settings.INTERNAL_KEY_ID,
        secret_key=settings.INTERNAL_API_KEY,
        body=body,
    )


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
