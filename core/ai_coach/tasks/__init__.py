"""AI coach Celery task exports."""

from .plans import (
    ai_coach_echo,
    ai_coach_worker_report,
    generate_ai_workout_plan,
    handle_ai_plan_failure,
    notify_ai_plan_ready_task,
    refresh_external_knowledge,
    update_ai_workout_plan,
)
from .qa import ask_ai_question, handle_ai_question_failure, notify_ai_answer_ready_task

__all__ = [
    "ai_coach_echo",
    "ai_coach_worker_report",
    "generate_ai_workout_plan",
    "handle_ai_plan_failure",
    "notify_ai_plan_ready_task",
    "refresh_external_knowledge",
    "update_ai_workout_plan",
    "ask_ai_question",
    "handle_ai_question_failure",
    "notify_ai_answer_ready_task",
]
