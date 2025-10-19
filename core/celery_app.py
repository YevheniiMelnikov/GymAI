import os
from urllib.parse import urlsplit, urlunsplit

from celery import Celery
from kombu import Exchange, Queue

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
    env_value = os.getenv("CELERY_BROKER_URL")
    if env_value is not None:
        return env_value
    return settings.RABBITMQ_URL


dead_letter_exchange: Exchange = Exchange("critical.dlx", type="topic", durable=True)
critical_exchange: Exchange = Exchange("critical", type="direct", durable=True)
default_exchange: Exchange = Exchange("default", type="direct", durable=True)
maintenance_exchange: Exchange = Exchange("maintenance", type="direct", durable=True)

CELERY_QUEUES: tuple[Queue, ...] = (
    Queue("default", default_exchange, routing_key="default", durable=True),
    Queue(
        "critical",
        critical_exchange,
        routing_key="critical",
        durable=True,
        queue_arguments={
            "x-dead-letter-exchange": dead_letter_exchange.name,
            "x-message-ttl": 600_000,
            "x-max-priority": 10,
        },
    ),
    Queue("maintenance", maintenance_exchange, routing_key="maintenance", durable=True),
    Queue("critical.dlq", dead_letter_exchange, routing_key="#", durable=True),
    Queue("ai_coach", default_exchange, routing_key="ai_coach", durable=True),
)

CRITICAL_TASK_ROUTES: dict[str, dict[str, str]] = {
    "core.tasks.billing.charge_due_subscriptions": {"queue": "critical", "routing_key": "critical"},
    "core.tasks.billing.deactivate_expired_subscriptions": {
        "queue": "critical",
        "routing_key": "critical",
    },
    "core.tasks.billing.warn_low_credits": {"queue": "critical", "routing_key": "critical"},
    "apps.payments.tasks.process_payment_webhook": {
        "queue": "critical",
        "routing_key": "critical",
    },
    "apps.payments.tasks.send_payment_message": {
        "queue": "critical",
        "routing_key": "critical",
    },
    "apps.payments.tasks.send_client_request": {
        "queue": "critical",
        "routing_key": "critical",
    },
}

AI_COACH_TASK_ROUTES: dict[str, dict[str, str]] = {
    "core.tasks.ai_coach.generate_ai_workout_plan": {
        "queue": "ai_coach",
        "routing_key": "ai_coach",
    },
    "core.tasks.ai_coach.update_ai_workout_plan": {
        "queue": "ai_coach",
        "routing_key": "ai_coach",
    },
    "core.tasks.ai_coach.ai_coach_echo": {"queue": "ai_coach", "routing_key": "ai_coach"},
    "core.tasks.ai_coach.ai_coach_worker_report": {
        "queue": "ai_coach",
        "routing_key": "ai_coach",
    },
}

CELERY_TASK_ROUTES: dict[str, dict[str, str]] = {
    **CRITICAL_TASK_ROUTES,
    **AI_COACH_TASK_ROUTES,
}

CELERY_INCLUDE: tuple[str, ...] = (
    "core.tasks.backups",
    "core.tasks.billing",
    "core.tasks.bot_calls",
    "core.tasks.ai_coach",
    "apps.payments.tasks",
)

app = Celery("gymbot", broker=_broker_url(), backend=_redis_backend_url())
app_conf = getattr(app, "conf", None)
if app_conf is None:
    raise RuntimeError("Celery configuration is not available")
app_conf.update(
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
    task_default_queue="default",
    task_default_exchange="default",
    task_default_exchange_type="direct",
    task_default_delivery_mode="persistent",
    task_create_missing_queues=True,
    task_queues=CELERY_QUEUES,
    task_routes=CELERY_TASK_ROUTES,
    include=list(CELERY_INCLUDE),
)

__all__ = [
    "app",
    "CELERY_QUEUES",
    "CELERY_TASK_ROUTES",
    "CELERY_INCLUDE",
    "default_exchange",
]
