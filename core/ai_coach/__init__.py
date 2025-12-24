"""AI coach domain utilities."""

from .models import AskAiPreparationResult
from .payloads import (
    AiAttachmentPayload,
    AiPlanBasePayload,
    AiPlanGenerationPayload,
    AiPlanUpdatePayload,
    AiDietPlanPayload,
    AiQuestionPayload,
)
from .state.ask_ai import (
    AI_QUESTION_CHARGED_KEY,
    AI_QUESTION_CLAIM_KEY,
    AI_QUESTION_DELIVERED_KEY,
    AI_QUESTION_FAILED_KEY,
    AI_QUESTION_TASK_CLAIM_KEY,
    AiQuestionState,
)
from .state.diet import (
    AI_DIET_CHARGED_KEY,
    AI_DIET_CLAIM_KEY,
    AI_DIET_DELIVERED_KEY,
    AI_DIET_FAILED_KEY,
    AI_DIET_TASK_CLAIM_KEY,
    AiDietState,
)
from .state.plan import AiPlanState

__all__ = [
    "AskAiPreparationResult",
    "AiAttachmentPayload",
    "AiPlanBasePayload",
    "AiPlanGenerationPayload",
    "AiPlanUpdatePayload",
    "AiDietPlanPayload",
    "AiQuestionPayload",
    "AiQuestionState",
    "AiDietState",
    "AiPlanState",
    "AI_QUESTION_CHARGED_KEY",
    "AI_QUESTION_CLAIM_KEY",
    "AI_QUESTION_DELIVERED_KEY",
    "AI_QUESTION_FAILED_KEY",
    "AI_QUESTION_TASK_CLAIM_KEY",
    "AI_DIET_CHARGED_KEY",
    "AI_DIET_CLAIM_KEY",
    "AI_DIET_DELIVERED_KEY",
    "AI_DIET_FAILED_KEY",
    "AI_DIET_TASK_CLAIM_KEY",
]
