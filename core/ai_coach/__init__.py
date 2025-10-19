"""AI coach domain utilities."""

from .models import AskAiPreparationResult
from .payloads import (
    AiAttachmentPayload,
    AiPlanBasePayload,
    AiPlanGenerationPayload,
    AiPlanUpdatePayload,
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
from .state.plan import AiPlanState

__all__ = [
    "AskAiPreparationResult",
    "AiAttachmentPayload",
    "AiPlanBasePayload",
    "AiPlanGenerationPayload",
    "AiPlanUpdatePayload",
    "AiQuestionPayload",
    "AiQuestionState",
    "AiPlanState",
    "AI_QUESTION_CHARGED_KEY",
    "AI_QUESTION_CLAIM_KEY",
    "AI_QUESTION_DELIVERED_KEY",
    "AI_QUESTION_FAILED_KEY",
    "AI_QUESTION_TASK_CLAIM_KEY",
]
