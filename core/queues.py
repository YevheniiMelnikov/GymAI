from __future__ import annotations

from typing import Final

from kombu import Connection, Queue
from loguru import logger

from core.celery_app import CELERY_QUEUES, app, default_exchange

_ai_coach_queue: Queue | None = next(
    (queue for queue in CELERY_QUEUES if queue.name == "ai_coach"),
    None,
)
if _ai_coach_queue is None:  # pragma: no cover - hard failure during startup
    raise RuntimeError("ai_coach queue is not defined in CELERY_QUEUES")

AI_COACH_QUEUE: Final[Queue] = _ai_coach_queue


def ensure_ai_coach_queue() -> None:
    broker_url_obj = getattr(app.conf, "broker_url", None)
    broker_url: str | None = str(broker_url_obj) if broker_url_obj else None
    if not broker_url:
        logger.warning("ensure_ai_coach_queue: broker URL is not configured")
        return
    try:
        with Connection(broker_url) as connection:
            bound_queue = AI_COACH_QUEUE(connection)
            bound_queue.declare()
            logger.info(
                f"ensure_ai_coach_queue: declared queue={AI_COACH_QUEUE.name} "
                f"exchange={default_exchange.name} routing_key={AI_COACH_QUEUE.routing_key}"
            )
    except Exception as exc:  # pragma: no cover - connectivity issues
        logger.opt(exception=exc).error("ensure_ai_coach_queue: declare failed for broker=%s", broker_url)


__all__ = ["AI_COACH_QUEUE", "ensure_ai_coach_queue"]
