from datetime import datetime, timedelta

from celery import Celery
from celery.schedules import crontab, schedule
from kombu import Exchange, Queue

from config.app_settings import settings


def beat_nowfun() -> datetime:
    """Return current UTC time offset by the knowledge refresh start delay."""
    return datetime.utcnow() + timedelta(seconds=settings.KNOWLEDGE_REFRESH_START_DELAY)


def knowledge_refresh_now() -> datetime:
    """Backward-compat alias for old pickled beat schedules."""
    return beat_nowfun()


dead_letter_exchange = Exchange("critical.dlx", type="topic", durable=True)
critical_exchange = Exchange("critical", type="direct", durable=True)
default_exchange = Exchange("default", type="direct", durable=True)
maintenance_exchange = Exchange("maintenance", type="direct", durable=True)

celery_config = {
    "broker_url": settings.RABBITMQ_URL,
    "result_backend": settings.REDIS_URL,
    "timezone": settings.TIME_ZONE,
    "task_serializer": "json",
    "accept_content": ["json"],
    "task_acks_late": True,
    "worker_max_tasks_per_child": 100,
    "worker_prefetch_multiplier": 1,
    "task_time_limit": 600,
    "worker_pool": "threads",
    "broker_connection_retry_on_startup": True,
    "broker_heartbeat": 30,
    "beat_schedule_filename": "/app/celerybeat-schedule",
    "task_default_queue": "default",
    "task_default_exchange": "default",
    "task_default_exchange_type": "direct",
    "task_default_routing_key": "default",
    "task_default_delivery_mode": "persistent",
    "task_queues": (
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
    ),
    "task_routes": {
        "core.tasks.charge_due_subscriptions": {
            "queue": "critical",
            "routing_key": "critical",
        },
        "core.tasks.deactivate_expired_subscriptions": {
            "queue": "critical",
            "routing_key": "critical",
        },
        "core.tasks.warn_low_credits": {
            "queue": "critical",
            "routing_key": "critical",
        },
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
    },
    "beat_schedule": {
        "pg_backup": {
            "task": "core.tasks.pg_backup",
            "schedule": crontab(hour=2, minute=0),
            "options": {"queue": "maintenance"},
        },
        "redis_backup": {
            "task": "core.tasks.redis_backup",
            "schedule": crontab(hour=2, minute=1),
            "options": {"queue": "maintenance"},
        },
        "cleanup_backups": {
            "task": "core.tasks.cleanup_backups",
            "schedule": crontab(hour=2, minute=2),
            "options": {"queue": "maintenance"},
        },
        "deactivate_subs": {
            "task": "core.tasks.deactivate_expired_subscriptions",
            "schedule": crontab(hour=1, minute=0),
            "options": {"queue": "critical"},
        },
        "warn_low_credits": {
            "task": "core.tasks.warn_low_credits",
            "schedule": crontab(hour=0, minute=0),
            "options": {"queue": "critical"},
        },
        "charge_due_subscriptions": {
            "task": "core.tasks.charge_due_subscriptions",
            "schedule": crontab(hour=0, minute=30),
            "options": {"queue": "critical"},
        },
        "export-coach-payouts-monthly": {
            "task": "core.tasks.export_coach_payouts",
            "schedule": crontab(day_of_month=1, hour=8, minute=0),
            "options": {"queue": "maintenance"},
        },
        "send_daily_survey": {
            "task": "core.tasks.send_daily_survey",
            "schedule": crontab(hour=9, minute=0),
            "options": {"queue": "maintenance"},
        },
        "refresh_external_knowledge": {
            "task": "core.tasks.refresh_external_knowledge",
            "schedule": schedule(
                run_every=timedelta(seconds=settings.KNOWLEDGE_REFRESH_INTERVAL),
                nowfun=beat_nowfun,
            ),
            "options": {"queue": "maintenance"},
        },
        "prune_cognee": {
            "task": "core.tasks.prune_cognee",
            "schedule": crontab(hour=2, minute=10),
            "options": {"queue": "maintenance"},
        },
    },
}

celery_app = Celery("gym_bot", config_source=celery_config)
celery_app.autodiscover_tasks(["core", "apps.payments"])

__all__ = ("celery_app",)
