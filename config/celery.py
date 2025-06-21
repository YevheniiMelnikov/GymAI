from celery import Celery
from celery.schedules import crontab
from config.env_settings import settings

celery_config = {
    "broker_url": settings.REDIS_URL,
    "result_backend": settings.REDIS_URL,
    "timezone": settings.TIME_ZONE,
    "task_serializer": "json",
    "accept_content": ["json"],
    "task_acks_late": True,
    "worker_max_tasks_per_child": 100,
    "task_time_limit": 600,
    "worker_pool": "threads",
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
        },
        "warn_low_credits": {
            "task": "core.tasks.warn_low_credits",
            "schedule": crontab(hour=0, minute=0),
        },
        "charge_due_subscriptions": {
            "task": "core.tasks.charge_due_subscriptions",
            "schedule": crontab(hour=0, minute=30),
        },
        "unclosed-payments-monthly": {
            "task": "core.tasks.process_unclosed_payments",
            "schedule": crontab(day_of_month=1, hour=8, minute=0),
            "options": {"queue": "maintenance"},
        },
        "send_daily_survey": {
            "task": "core.tasks.send_daily_survey",
            "schedule": crontab(hour=9, minute=0),
            "options": {"queue": "maintenance"},
        },
    },
}

celery_app = Celery("gym_bot", config_source=celery_config)
celery_app.autodiscover_tasks(["core", "apps.payments"])

__all__ = ("celery_app",)
