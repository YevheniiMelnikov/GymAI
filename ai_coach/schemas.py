from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from ai_coach.types import CoachMode
from core.schemas import Program, DayExercises
from core.enums import CoachType, WorkoutPlanType, WorkoutType


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

    schema_version: str | None = Field(
        default=None,
        description="Internal schema version used by the agent; dropped before save",
    )

    @field_validator("coach_type", mode="before")
    @staticmethod
    def _map_coach_type(value: str | CoachType | None) -> CoachType | str | None:
        if value == "ai":
            return CoachType.ai
        return value

    @model_validator(mode="after")
    def _validate_invariants(self) -> "ProgramPayload":
        if not self.exercises_by_day:
            raise ValueError("exercises_by_day must not be empty")
        for day in self.exercises_by_day:
            if not day.exercises:
                raise ValueError("day exercises must not be empty")
            for ex in day.exercises:
                if not (ex.name and ex.sets and ex.reps):
                    raise ValueError("exercise must have name, sets and reps")
        if self.split_number is None:
            self.split_number = len(self.exercises_by_day)
        return self


class SubscriptionPayload(BaseModel):
    """Subscription schema produced by the agent."""

    workout_days: list[str]
    exercises: list[DayExercises]
    wishes: str | None = None
    schema_version: str | None = None

    @model_validator(mode="after")
    def _check(self) -> "SubscriptionPayload":
        if not self.workout_days:
            raise ValueError("workout_days must not be empty")
        if not self.exercises:
            raise ValueError("exercises must not be empty")
        return self


UpdatedProgramPayload = ProgramPayload
