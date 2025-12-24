"""Celery task package for GymBot core domain."""

from core.tasks.ai_coach import (
    ai_coach_echo,
    ai_coach_worker_report,
    ask_ai_question,
    generate_ai_workout_plan,
    handle_ai_plan_failure,
    handle_ai_question_failure,
    handle_ai_diet_failure,
    generate_ai_diet_plan,
    notify_ai_answer_ready_task,
    notify_ai_diet_ready_task,
    notify_ai_plan_ready_task,
    prune_knowledge_base,
    replace_exercise_task,
    refresh_external_knowledge,
    update_ai_workout_plan,
)
from core.tasks.backups import cleanup_backups, neo4j_backup, pg_backup, qdrant_backup, redis_backup
from core.tasks.billing import (
    charge_due_subscriptions,
    deactivate_expired_subscriptions,
    warn_low_credits,
)
from core.tasks.bot_calls import (
    send_daily_survey,
)

__all__ = [
    "ai_coach_echo",
    "ai_coach_worker_report",
    "ask_ai_question",
    "generate_ai_diet_plan",
    "generate_ai_workout_plan",
    "handle_ai_plan_failure",
    "handle_ai_question_failure",
    "handle_ai_diet_failure",
    "notify_ai_plan_ready_task",
    "notify_ai_answer_ready_task",
    "notify_ai_diet_ready_task",
    "refresh_external_knowledge",
    "update_ai_workout_plan",
    "prune_knowledge_base",
    "replace_exercise_task",
    "cleanup_backups",
    "neo4j_backup",
    "pg_backup",
    "qdrant_backup",
    "redis_backup",
    "charge_due_subscriptions",
    "deactivate_expired_subscriptions",
    "warn_low_credits",
    "send_daily_survey",
]
