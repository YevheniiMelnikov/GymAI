from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError, field_validator, model_validator

from ai_coach.types import CoachMode
from core.schemas import Program, DayExercises
from core.enums import WorkoutPlanType, WorkoutType


class AICoachRequest(BaseModel):
    client_id: int
    prompt: str | None = None
    language: str | None = None
    mode: CoachMode = CoachMode.program
    period: str | None = None
    workout_days: list[str] | None = None
    expected_workout: str | None = None
    feedback: str | None = None
    wishes: str | None = None
    workout_type: WorkoutType | None = None
    plan_type: WorkoutPlanType | None = None
    request_id: str | None = None
    instructions: str | None = None  # User-provided custom instructions

    def __init__(self, **data: Any) -> None:
        mode = data.get("mode")
        if isinstance(mode, str):
            data["mode"] = CoachMode(mode)
        super().__init__(**data)

    @field_validator("workout_type", mode="before")
    @staticmethod
    def _normalize_workout_type(value: str | WorkoutType | None) -> WorkoutType | None:
        if value is None or isinstance(value, WorkoutType):
            return value
        return WorkoutType(value.lower())

    @model_validator(mode="after")
    def _validate_update_plan_type(self) -> "AICoachRequest":
        if self.mode is CoachMode.update and self.plan_type is None:
            raise ValueError("plan_type is required for update mode")
        return self


@dataclass
class CogneeUser:
    id: Any
    tenant_id: Any | None = None
    roles: list[str] | None = None


class ProgramPayload(Program):
    """Program schema used by the agent (allows schema_version)."""

    schema_version: str | None = None

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)
        if not getattr(self, "exercises_by_day", []):
            raise ValidationError("exercises_by_day must not be empty")
        for day in getattr(self, "exercises_by_day", []):
            exercises = day.get("exercises", []) if isinstance(day, dict) else getattr(day, "exercises", [])
            if not exercises:
                raise ValidationError("day exercises must not be empty")
            for ex in exercises:
                getter = ex.get if isinstance(ex, dict) else lambda k, d=None: getattr(ex, k, d)
                if not all(getter(attr) for attr in ("name", "sets", "reps")):
                    raise ValidationError("exercise must have name, sets and reps")
        if getattr(self, "split_number", None) is None:
            self.split_number = len(getattr(self, "exercises_by_day", []))


class SubscriptionPayload(BaseModel):
    """Subscription schema produced by the agent."""

    workout_days: list[str]
    exercises: list[DayExercises]
    wishes: str | None = None
    schema_version: str | None = None

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)
        if not getattr(self, "workout_days", []):
            raise ValidationError("workout_days must not be empty")
        if not getattr(self, "exercises", []):
            raise ValidationError("exercises must not be empty")


UpdatedProgramPayload = ProgramPayload
