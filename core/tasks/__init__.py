"""Celery task package for GymBot core domain."""

from __future__ import annotations

from core.tasks.ai_coach import (
    ai_coach_echo,
    ai_coach_worker_report,
    generate_ai_workout_plan,
    handle_ai_plan_failure,
    notify_ai_plan_ready_task,
    refresh_external_knowledge,
    update_ai_workout_plan,
)
from core.tasks.backups import cleanup_backups, pg_backup, redis_backup
from core.tasks.billing import (
    charge_due_subscriptions,
    deactivate_expired_subscriptions,
    warn_low_credits,
)
from core.tasks.bot_calls import (
    export_coach_payouts,
    prune_cognee,
    send_daily_survey,
    send_workout_result,
)

__all__ = [
    "ai_coach_echo",
    "ai_coach_worker_report",
    "generate_ai_workout_plan",
    "handle_ai_plan_failure",
    "notify_ai_plan_ready_task",
    "refresh_external_knowledge",
    "update_ai_workout_plan",
    "cleanup_backups",
    "pg_backup",
    "redis_backup",
    "charge_due_subscriptions",
    "deactivate_expired_subscriptions",
    "warn_low_credits",
    "export_coach_payouts",
    "prune_cognee",
    "send_daily_survey",
    "send_workout_result",
]
