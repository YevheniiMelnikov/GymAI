"""HTTP helpers for recording metrics events via the Django API."""

from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
import orjson
from loguru import logger

from config.app_settings import settings
from core.internal_http import build_internal_hmac_auth_headers, internal_request_timeout


def _metrics_url() -> str:
    base_url = (settings.API_URL or "").rstrip("/") + "/"
    return urljoin(base_url, "internal/metrics/event/")


async def emit_metrics_event(event_type: str, *, source: str, source_id: str) -> None:
    if not settings.INTERNAL_API_KEY:
        logger.warning("metrics_event_skipped reason=missing_internal_api_key")
        return
    api_url = str(settings.API_URL or "").strip()
    if not api_url:
        logger.warning("metrics_event_skipped reason=missing_api_url")
        return
    parsed = urlsplit(api_url if "://" in api_url else f"http://{api_url}")
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        logger.warning("metrics_event_skipped reason=invalid_api_url value={}", api_url)
        return
    if not source_id:
        logger.warning("metrics_event_skipped reason=missing_source_id")
        return
    payload: dict[str, Any] = {"event_type": event_type}
    payload["source"] = source
    payload["source_id"] = source_id
    body = orjson.dumps(payload)
    headers = build_internal_hmac_auth_headers(
        key_id=settings.INTERNAL_KEY_ID,
        secret_key=settings.INTERNAL_API_KEY,
        body=body,
    )
    headers["Content-Type"] = "application/json"
    url = _metrics_url()
    timeout = internal_request_timeout(settings)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, content=body, headers=headers)
            response.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"metrics_event_failed type={event_type} error={exc}")
