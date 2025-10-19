"""Celery task package for GymBot core domain."""

from core.ai_coach.tasks.plans import (
    ai_coach_echo,
    ai_coach_worker_report,
    generate_ai_workout_plan,
    handle_ai_plan_failure,
    notify_ai_plan_ready_task,
    refresh_external_knowledge,
    update_ai_workout_plan,
)
from core.ai_coach.tasks.qa import (
    ask_ai_question,
    handle_ai_question_failure,
    notify_ai_answer_ready_task,
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
    "ask_ai_question",
    "generate_ai_workout_plan",
    "handle_ai_plan_failure",
    "handle_ai_question_failure",
    "notify_ai_plan_ready_task",
    "notify_ai_answer_ready_task",
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
