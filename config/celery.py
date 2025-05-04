from celery.schedules import crontab

from config.env_settings import Settings

broker_url = Settings.REDIS_URL
result_backend = Settings.REDIS_URL
beat_schedule = {
    "pg_backup": {"task": "project.tasks.pg_backup", "schedule": crontab(hour=2, minute=0)},
    "redis_backup": {"task": "project.tasks.redis_backup", "schedule": crontab(hour=2, minute=1)},
    "cleanup_backups": {"task": "project.tasks.cleanup_backups", "schedule": crontab(hour=2, minute=2)},
    "deactivate_subs": {"task": "project.tasks.deactivate_subscriptions", "schedule": crontab(hour=1, minute=0)},
}
timezone = Settings.TIME_ZONE
task_serializer = "json"
accept_content = ["json"]
