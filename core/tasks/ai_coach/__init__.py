"""Celery tasks for AI Coach centralized under core.tasks.ai_coach."""

import asyncio  # noqa: F401

from core.ai_coach.state.plan import AiPlanState  # noqa: F401
from . import plans as _plans

from .maintenance import (  # noqa: F401
    ai_coach_echo,
    ai_coach_worker_report,
    prune_knowledge_base,
    refresh_external_knowledge,
)
from .plans import (  # noqa: F401
    _generate_ai_workout_plan_impl,
    _update_ai_workout_plan_impl,
    generate_ai_workout_plan,
    handle_ai_plan_failure,
    notify_ai_plan_ready_task,
    update_ai_workout_plan,
)
from .qa import (  # noqa: F401
    ask_ai_question,
    _claim_answer_request,
    _handle_ai_answer_failure_impl,
    _notify_ai_answer_error,
    handle_ai_question_failure,
    notify_ai_answer_ready_task,
)

__all__ = (
    "_claim_answer_request",
    "_generate_ai_workout_plan_impl",
    "_handle_ai_answer_failure_impl",
    "_notify_ai_answer_error",
    "_update_ai_workout_plan_impl",
    "generate_ai_workout_plan",
    "handle_ai_plan_failure",
    "notify_ai_plan_ready_task",
    "update_ai_workout_plan",
    "ask_ai_question",
    "handle_ai_question_failure",
    "notify_ai_answer_ready_task",
    "ai_coach_echo",
    "ai_coach_worker_report",
    "refresh_external_knowledge",
    "prune_knowledge_base",
    "AiPlanState",
)

httpx = _plans.httpx
logger = _plans.logger
