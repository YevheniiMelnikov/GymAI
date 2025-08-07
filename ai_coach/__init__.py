from __future__ import annotations

from typing import Type

from .base_coach import BaseAICoach
from .gdrive_knowledge_loader import GDriveDocumentLoader

__all__ = ["GDriveDocumentLoader"]
AI_COACH: Type[BaseAICoach] | None = None


def set_ai_coach(coach: Type[BaseAICoach]) -> None:
    global AI_COACH
    AI_COACH = coach


def get_ai_coach() -> Type[BaseAICoach]:
    if AI_COACH is None:
        raise RuntimeError("AI coach is not initialized")
    return AI_COACH
