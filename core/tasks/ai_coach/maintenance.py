"""Maintenance and diagnostic Celery tasks for the AI coach service."""

import asyncio
from typing import Any

import httpx
from loguru import logger

from config.app_settings import settings
from core.celery_app import app
from core.internal_http import build_internal_hmac_auth_headers, resolve_hmac_credentials
from core.services import APIService
from core.utils.redis_lock import get_redis_client, redis_try_lock

__all__ = [
    "ai_coach_echo",
    "ai_coach_worker_report",
    "refresh_external_knowledge",
    "prune_knowledge_base",
]


def _ai_coach_path(path: str) -> str:
    base_url = settings.AI_COACH_URL.rstrip("/")
    if not base_url:
        raise RuntimeError("AI_COACH_URL is not configured")
    return f"{base_url}/{path.lstrip('/')}"


@app.task(bind=True, queue="ai_coach", routing_key="ai_coach")
def ai_coach_echo(self, payload: dict[str, Any]) -> dict[str, Any]:  # pyrefly: ignore[valid-type]
    descriptor: str
    if isinstance(payload, dict):
        descriptor = ",".join(sorted(str(key) for key in payload.keys()))
    else:
        descriptor = type(payload).__name__
    logger.info(f"ai_coach_echo task_id={self.request.id} payload_descriptor={descriptor}")
    return {"ok": True, "echo": payload}


@app.task(bind=True, queue="ai_coach", routing_key="ai_coach")
def ai_coach_worker_report(self) -> dict[str, Any]:  # pyrefly: ignore[valid-type]
    broker_url = str(getattr(app.conf, "broker_url", ""))
    backend_url = str(getattr(app.conf, "result_backend", ""))
    hostname = getattr(self.request, "hostname", None)
    logger.info(
        "ai_coach_worker_report hostname={} broker={} backend={}",
        hostname,
        broker_url,
        backend_url,
    )
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
def refresh_external_knowledge(self) -> None:  # pyrefly: ignore[valid-type]
    """Refresh external knowledge and rebuild Cognee index."""
    logger.info("refresh_external_knowledge triggered")

    async def _dedupe_window(window_s: int = 30) -> bool:
        redis = get_redis_client()
        ok = await redis.set("dedupe:refresh_external_knowledge", "1", nx=True, ex=window_s)
        return bool(ok)

    async def _impl() -> None:
        if not await _dedupe_window(30):
            logger.info("refresh_external_knowledge skipped: dedupe window active")
            return

        async with redis_try_lock("locks:refresh_external_knowledge", ttl_ms=180_000, wait=False) as got:
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


@app.task(
    bind=True,
    autoretry_for=(httpx.HTTPError,),
    retry_backoff=180,
    retry_jitter=True,
    max_retries=3,
)
def prune_knowledge_base(self) -> None:  # pyrefly: ignore[valid-type]
    """Trigger Cognee prune on the AI coach service."""
    logger.info("prune_knowledge_base started")
    timeout = settings.AI_COACH_TIMEOUT
    payload: dict[str, Any] = {}
    body = b"{}"  # raw body used for HMAC; keep in sync with actual request content
    creds = resolve_hmac_credentials(settings, prefer_ai_coach=True)
    if creds:
        url = _ai_coach_path("internal/knowledge/prune/")
        key_id, secret_key = creds
        headers = build_internal_hmac_auth_headers(
            key_id=key_id,
            secret_key=secret_key,
            body=body,
        )
        headers.setdefault("Content-Type", "application/json")
        request_kwargs: dict[str, Any] = {"headers": headers, "content": body}
    else:
        url = _ai_coach_path("knowledge/prune/")
        basic_user = settings.AI_COACH_REFRESH_USER
        basic_pass = settings.AI_COACH_REFRESH_PASSWORD
        request_kwargs = {"json": payload, "auth": (basic_user, basic_pass)}
    try:
        resp = httpx.post(url, timeout=timeout, **request_kwargs)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning(f"AI coach call failed for prune_knowledge_base: {exc}")
        raise self.retry(exc=exc)
    logger.info("prune_knowledge_base completed")
