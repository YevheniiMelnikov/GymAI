from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, field_validator, model_validator

from ai_coach.types import CoachMode
from core.schemas import (
    DayExercises,
    DietMeal,
    Exercise,
    NutritionTotals,
    Program,
    QAResponseBlock,
)
from core.enums import WorkoutPlanType, WorkoutLocation


class AICoachRequest(BaseModel):
    profile_id: int
    prompt: str | None = None
    language: str | None = None
    mode: CoachMode = CoachMode.program
    period: str | None = None
    split_number: int | None = None
    feedback: str | None = None
    wishes: str | None = None
    workout_location: WorkoutLocation | None = None
    plan_type: WorkoutPlanType | None = None
    request_id: str | None = None
    instructions: str | None = None  # User-provided custom instructions
    attachments: list[dict[str, str]] | None = None
    diet_allergies: str | None = None
    diet_products: list[str] | None = None

    def __init__(self, **data: Any) -> None:
        mode = data.get("mode")
        if isinstance(mode, str):
            data["mode"] = CoachMode(mode)
        super().__init__(**data)

    @field_validator("split_number")
    @classmethod
    def _validate_split_number(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if value < 1 or value > 7:
            raise ValueError("split_number must be between 1 and 7")
        return value

    @field_validator("workout_location", mode="before")
    @staticmethod
    def _normalize_workout_location(value: str | WorkoutLocation | None) -> WorkoutLocation | None:
        if value is None or isinstance(value, WorkoutLocation):
            return value
        return WorkoutLocation(value.lower())

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

    @model_validator(mode="after")
    def _validate(self) -> "ProgramPayload":
        if not self.exercises_by_day:
            raise ValueError("exercises_by_day must not be empty")
        for raw_day in self.exercises_by_day:
            day = raw_day if isinstance(raw_day, DayExercises) else DayExercises.model_validate(raw_day)
            if not day.exercises:
                raise ValueError("day exercises must not be empty")
            for raw_ex in day.exercises:
                if isinstance(raw_ex, Exercise):
                    name, sets, reps = raw_ex.name, raw_ex.sets, raw_ex.reps
                else:
                    name = raw_ex.get("name")
                    sets = raw_ex.get("sets")
                    reps = raw_ex.get("reps")
                if not (name and sets and reps):
                    raise ValueError("exercise must have name, sets and reps")
        if self.split_number is None:
            self.split_number = len(self.exercises_by_day)
        return self


class AgentExerciseSetDetailOutput(BaseModel):
    reps: int
    weight: float
    weight_unit: str | None
    model_config = {"extra": "ignore"}


class AgentExerciseOutput(BaseModel):
    name: str
    sets: str | int
    reps: str | int
    weight: str | None
    set_id: int | None
    gif_key: str | None
    drop_set: bool
    superset_id: int | None
    superset_order: int | None
    sets_detail: list[AgentExerciseSetDetailOutput] | None
    model_config = {"extra": "ignore"}


class AgentDayExercisesOutput(BaseModel):
    day: str
    exercises: list[AgentExerciseOutput]
    model_config = {"extra": "ignore"}


class AgentProgramOutput(BaseModel):
    id: int
    profile: int
    exercises_by_day: list[AgentDayExercisesOutput]
    created_at: float
    split_number: int | None
    workout_location: str | None
    wishes: str | None
    schema_version: str | None = None
    model_config = {"extra": "ignore"}


class AgentSubscriptionOutput(BaseModel):
    id: int
    profile: int
    enabled: bool
    price: int
    workout_location: str
    wishes: str
    period: str
    split_number: int
    exercises: list[AgentDayExercisesOutput]
    payment_date: str
    schema_version: str | None = None
    model_config = {"extra": "ignore"}


class AgentDietPlanOutput(BaseModel):
    id: int | None
    meals: list[DietMeal]
    totals: NutritionTotals
    notes: list[str]
    schema_version: str | None
    model_config = {"extra": "ignore"}


class AgentQAResponseOutput(BaseModel):
    answer: str
    sources: list[str]
    blocks: list[QAResponseBlock] | None = None
    model_config = {"extra": "ignore"}


class SubscriptionPayload(BaseModel):
    """Subscription schema produced by the agent."""

    split_number: int
    exercises: list[DayExercises]
    wishes: str | None = None
    schema_version: str | None = None

    @model_validator(mode="after")
    def _validate(self) -> "SubscriptionPayload":
        if self.split_number < 1 or self.split_number > 7:
            raise ValueError("split_number must be between 1 and 7")
        if not self.exercises:
            raise ValueError("exercises must not be empty")
        return self


UpdatedProgramPayload = ProgramPayload
