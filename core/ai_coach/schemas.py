from __future__ import annotations

from pydantic import BaseModel
from core.schemas import DayExercises


class ProgramRequest(BaseModel):
    workout_type: str
    wishes: str


class ProgramResponse(BaseModel):
    days: list[DayExercises]


class SubscriptionRequest(BaseModel):
    workout_type: str
    wishes: str
    period: str
    days: int


class SubscriptionResponse(BaseModel):
    workout_days: list[str]
    exercises: list[DayExercises]


class AskAIRequest(BaseModel):
    question: str

