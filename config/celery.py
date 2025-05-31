from celery import Celery
from celery.schedules import crontab
from config.env_settings import Settings

celery_config = {
    "broker_url": Settings.REDIS_URL,
    "result_backend": Settings.REDIS_URL,
    "timezone": Settings.TIME_ZONE,
    "task_serializer": "json",
    "accept_content": ["json"],
    "task_acks_late": True,
    "worker_max_tasks_per_child": 100,
    "task_time_limit": 600,
    "worker_pool": "asyncio",
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
celery_app.autodiscover_tasks(["core"])

__all__ = ("celery_app",)
