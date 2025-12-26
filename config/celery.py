from datetime import UTC, datetime, timedelta


import importlib
import os
import sys

from celery.schedules import crontab, schedule

from config.app_settings import settings
from core.celery_app import CELERY_INCLUDE, CELERY_QUEUES, CELERY_TASK_ROUTES, app
from core.celery_signals import setup_celery_signals


def beat_nowfun() -> datetime:
    """Return current UTC time offset by the knowledge refresh start delay."""
    return datetime.now(tz=UTC) + timedelta(seconds=settings.KNOWLEDGE_REFRESH_START_DELAY)


def knowledge_refresh_now() -> datetime:
    """Backward-compat alias for old pickled beat schedules."""
    return beat_nowfun()


beat_schedule = {
    "pg_backup": {
        "task": "core.tasks.backups.pg_backup",
        "schedule": crontab(hour=2, minute=0),
        "options": {"queue": "maintenance"},
    },
    "redis_backup": {
        "task": "core.tasks.backups.redis_backup",
        "schedule": crontab(hour=2, minute=1),
        "options": {"queue": "maintenance"},
    },
    "cleanup_backups": {
        "task": "core.tasks.backups.cleanup_backups",
        "schedule": crontab(hour=2, minute=2),
        "options": {"queue": "maintenance"},
    },
    "deactivate_subs": {
        "task": "core.tasks.billing.deactivate_expired_subscriptions",
        "schedule": crontab(hour=1, minute=0),
        "options": {"queue": "critical"},
    },
    "warn_low_credits": {
        "task": "core.tasks.billing.warn_low_credits",
        "schedule": crontab(hour=0, minute=0),
        "options": {"queue": "critical"},
    },
    "charge_due_subscriptions": {
        "task": "core.tasks.billing.charge_due_subscriptions",
        "schedule": crontab(hour=0, minute=30),
        "options": {"queue": "critical"},
    },
    "refresh_external_knowledge": {
        "task": "core.tasks.ai_coach.refresh_external_knowledge",
        "schedule": schedule(
            run_every=timedelta(seconds=settings.KNOWLEDGE_REFRESH_INTERVAL),
            nowfun=beat_nowfun,
        ),
        "options": {"queue": "maintenance"},
    },
    "prune_knowledge_base": {
        "task": "core.tasks.ai_coach.prune_knowledge_base",
        "schedule": crontab(hour=2, minute=10),
        "options": {"queue": "maintenance"},
    },
    "collect_weekly_metrics": {
        "task": "core.tasks.metrics.collect_weekly_metrics",
        "schedule": crontab(day_of_week="mon", hour=3, minute=0),
        "options": {"queue": "maintenance"},
    },
    "send_weekly_survey": {
        "task": "core.tasks.bot_calls.send_weekly_survey",
        "schedule": crontab(day_of_week="sun", hour=10, minute=0),
        "options": {"queue": "maintenance"},
    },
}

if settings.ENABLE_KB_BACKUPS:
    beat_schedule.update(
        {
            "neo4j_backup": {
                "task": "core.tasks.backups.neo4j_backup",
                "schedule": crontab(hour=2, minute=3),
                "options": {"queue": "maintenance"},
            },
            "qdrant_backup": {
                "task": "core.tasks.backups.qdrant_backup",
                "schedule": crontab(hour=2, minute=4),
                "options": {"queue": "maintenance"},
            },
        }
    )

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
    "task_queues": CELERY_QUEUES,
    "task_routes": CELERY_TASK_ROUTES,
    "beat_schedule": beat_schedule,
}

celery_app = app
celery_conf = getattr(celery_app, "conf", None)
if celery_conf is None:
    raise RuntimeError("Celery app configuration is not available")
celery_conf.update(celery_config)
celery_conf.setdefault("include", list(CELERY_INCLUDE))

celery_app.autodiscover_tasks(["core", "apps.payments"])
if os.getenv("PYTEST_CURRENT_TEST") or "pytest" in sys.modules:
    for module_name in CELERY_INCLUDE:
        importlib.import_module(module_name)
setup_celery_signals()

__all__ = ("celery_app",)
