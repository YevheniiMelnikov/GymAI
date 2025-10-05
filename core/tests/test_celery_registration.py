from __future__ import annotations

from config.celery import celery_app
from core.celery_signals import REQUIRED_TASK_NAMES


def test_ai_coach_tasks_registered() -> None:
    for task_name in REQUIRED_TASK_NAMES:
        assert task_name in celery_app.tasks
