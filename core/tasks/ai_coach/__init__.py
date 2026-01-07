"""Celery tasks for AI Coach centralized under core.tasks.ai_coach."""

import asyncio  # noqa: F401

import httpx  # needed for tests
from typing import Any

from . import workout_plans as plans_module
from core.ai_coach.state.plan import AiPlanState
from .maintenance import (  # noqa: F401
    ai_coach_echo,
    ai_coach_worker_report,
    cleanup_profile_knowledge,
    memify_profile_datasets,
    prune_knowledge_base,
    refresh_external_knowledge,
    sync_profile_knowledge,
)
from .workout_plans import (  # noqa: F401
    _generate_ai_workout_plan_impl,
    _update_ai_workout_plan_impl,
    generate_ai_workout_plan,
    handle_ai_plan_failure,
    notify_ai_plan_ready_task,
    update_ai_workout_plan,
)
from .replace_exercise import (  # noqa: F401
    enqueue_exercise_replace_task,
    enqueue_subscription_exercise_replace_task,
    replace_exercise_task,
    replace_subscription_exercise_task,
)
from .ask_ai import (  # noqa: F401
    ask_ai_question,
    _claim_answer_request,
    _handle_ai_answer_failure_impl,
    _notify_ai_answer_error,
    handle_ai_question_failure,
    notify_ai_answer_ready_task,
)
from .diet import (  # noqa: F401
    generate_ai_diet_plan,
    handle_ai_diet_failure,
    notify_ai_diet_ready_task,
    refund_ai_diet_credits_task,
)


async def _notify_ai_plan_ready(payload: dict[str, Any]) -> None:
    return await plans_module._notify_ai_plan_ready(payload)


async def _claim_plan_request(request_id: str, action: str, *, attempt: int) -> bool:
    return await plans_module._claim_plan_request(request_id, action, attempt=attempt)


plans = plans_module
__ai_plan_state__ = AiPlanState
logger = plans_module.logger


__all__ = (
    "_claim_answer_request",
    "_claim_plan_request",
    "_generate_ai_workout_plan_impl",
    "_handle_ai_answer_failure_impl",
    "_notify_ai_answer_error",
    "_notify_ai_plan_ready",
    "_update_ai_workout_plan_impl",
    "AiPlanState",
    "ask_ai_question",
    "generate_ai_workout_plan",
    "handle_ai_plan_failure",
    "handle_ai_question_failure",
    "notify_ai_answer_ready_task",
    "notify_ai_diet_ready_task",
    "notify_ai_plan_ready_task",
    "plans",
    "update_ai_workout_plan",
    "ai_coach_echo",
    "ai_coach_worker_report",
    "httpx",
    "prune_knowledge_base",
    "refresh_external_knowledge",
    "cleanup_profile_knowledge",
    "sync_profile_knowledge",
    "memify_profile_datasets",
    "replace_exercise_task",
    "enqueue_exercise_replace_task",
    "replace_subscription_exercise_task",
    "enqueue_subscription_exercise_replace_task",
    "generate_ai_diet_plan",
    "handle_ai_diet_failure",
    "refund_ai_diet_credits_task",
)
