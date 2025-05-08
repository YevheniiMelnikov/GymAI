from celery import Celery
from celery.schedules import crontab
from config.env_settings import Settings

celery_app = Celery("project")

celery_app.conf.update(
    broker_url=Settings.REDIS_URL,
    result_backend=Settings.REDIS_URL,
    timezone=Settings.TIME_ZONE,
    task_serializer="json",
    accept_content=["json"],
    task_acks_late=True,
    worker_max_tasks_per_child=100,
    task_time_limit=600,
    beat_schedule={
        "pg_backup": {
            "task": "project.tasks.pg_backup",
            "schedule": crontab(hour=2, minute=0),
            "options": {"queue": "maintenance"},
        },
        "redis_backup": {
            "task": "project.tasks.redis_backup",
            "schedule": crontab(hour=2, minute=1),
            "options": {"queue": "maintenance"},
        },
        "cleanup_backups": {
            "task": "project.tasks.cleanup_backups",
            "schedule": crontab(hour=2, minute=2),
            "options": {"queue": "maintenance"},
        },
        "deactivate_subs": {
            "task": "project.tasks.deactivate_expired_subscriptions",
            "schedule": crontab(hour=1, minute=0),
        },
    },
)

celery_app.autodiscover_tasks(["project"])
