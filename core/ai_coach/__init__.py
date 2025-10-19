"""AI coach domain utilities."""

from .fallback import FALLBACK_WORKOUT_DAYS, fallback_plan
from .models import AskAiPreparationResult
from .payloads import (
    AiAttachmentPayload,
    AiPlanBasePayload,
    AiPlanGenerationPayload,
    AiPlanUpdatePayload,
    AiQuestionPayload,
)
from .state import (
    AI_QUESTION_CHARGED_KEY,
    AI_QUESTION_CLAIM_KEY,
    AI_QUESTION_DELIVERED_KEY,
    AI_QUESTION_FAILED_KEY,
    AI_QUESTION_TASK_CLAIM_KEY,
    AiQuestionState,
)

__all__ = [
    "AskAiPreparationResult",
    "AiAttachmentPayload",
    "AiPlanBasePayload",
    "AiPlanGenerationPayload",
    "AiPlanUpdatePayload",
    "AiQuestionPayload",
    "AiQuestionState",
    "AI_QUESTION_CHARGED_KEY",
    "AI_QUESTION_CLAIM_KEY",
    "AI_QUESTION_DELIVERED_KEY",
    "AI_QUESTION_FAILED_KEY",
    "AI_QUESTION_TASK_CLAIM_KEY",
    "FALLBACK_WORKOUT_DAYS",
    "fallback_plan",
]
