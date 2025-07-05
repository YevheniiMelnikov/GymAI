from core.ai_coach.base import BaseAICoach

from typing import Type

AI_COACH: Type[BaseAICoach] | None = None


def set_ai_coach(coach: Type[BaseAICoach]) -> None:
    global AI_COACH
    AI_COACH = coach


def get_ai_coach() -> Type[BaseAICoach]:
    if AI_COACH is None:
        raise RuntimeError("AI coach is not initialized")
    return AI_COACH
