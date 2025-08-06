from pydantic import BaseModel
from core.schemas import DayExercises


class ProgramResponse(BaseModel):
    days: list[DayExercises]


class SubscriptionResponse(BaseModel):
    workout_days: list[str]
    exercises: list[DayExercises]
