from __future__ import annotations

import os
from urllib.parse import urlsplit, urlunsplit

from celery import Celery

from config.app_settings import settings


def _redis_backend_url() -> str:
    override = os.getenv("CELERY_RESULT_BACKEND")
    if override:
        return override
    parsed = urlsplit(settings.REDIS_URL)
    path = parsed.path or ""
    if path in {"", "/"}:
        path = "/1"
    return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment))


def _broker_url() -> str:
    return os.getenv("CELERY_BROKER_URL") or settings.RABBITMQ_URL


app = Celery("gymbot", broker=_broker_url(), backend=_redis_backend_url())
app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_track_started=True,
    broker_connection_retry_on_startup=True,
    worker_disable_rate_limits=True,
    task_soft_time_limit=900,
    task_time_limit=960,
    task_routes={
        "core.tasks.generate_ai_workout_plan": {"queue": "ai_coach"},
        "core.tasks.update_ai_workout_plan": {"queue": "ai_coach"},
    },
)

__all__ = ["app"]
