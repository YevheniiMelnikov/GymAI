from dataclasses import asdict, dataclass
from typing import Any

from pydantic import BaseModel

from ai_coach.types import CoachMode
from core.schemas import DayExercises, Exercise
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

    def __init__(self, **data: Any) -> None:  # pragma: no cover - simple validation
        super().__init__(**data)
        if isinstance(self.workout_type, str):
            self.workout_type = WorkoutType(self.workout_type.lower())
        if isinstance(self.mode, str):
            self.mode = CoachMode(self.mode)
        if self.mode is CoachMode.update and self.plan_type is None:
            raise ValueError("plan_type is required for update mode")


@dataclass
class CogneeUser:
    id: Any
    tenant_id: Any | None = None
    roles: list[str] | None = None


@dataclass
class ProgramPayload:
    """Program schema used by the agent (allows schema_version)."""

    id: int
    client_profile: int
    exercises_by_day: list[DayExercises]
    created_at: float
    split_number: int | None = None
    workout_type: str | None = None
    wishes: str | None = None
    coach_type: CoachType = CoachType.human
    schema_version: str | None = None

    def __post_init__(self) -> None:
        if not self.exercises_by_day:
            raise ValueError("exercises_by_day must not be empty")
        days: list[DayExercises] = []
        for day in self.exercises_by_day:
            if isinstance(day, dict):
                ex_list = [Exercise(**e) if isinstance(e, dict) else e for e in day.get("exercises", [])]
                day_obj = DayExercises(day=day.get("day", ""), exercises=ex_list)
            else:
                day_obj = day
            if not day_obj.exercises:
                raise ValueError("day exercises must not be empty")
            for ex in day_obj.exercises:
                if not (ex.name and ex.sets and ex.reps):
                    raise ValueError("exercise must have name, sets and reps")
            days.append(day_obj)
        self.exercises_by_day = days
        if self.split_number is None:
            self.split_number = len(self.exercises_by_day)

    def model_dump(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SubscriptionPayload:
    """Subscription schema produced by the agent."""

    workout_days: list[str]
    exercises: list[DayExercises]
    wishes: str | None = None
    schema_version: str | None = None

    def __post_init__(self) -> None:
        if not self.workout_days:
            raise ValueError("workout_days must not be empty")
        if not self.exercises:
            raise ValueError("exercises must not be empty")

    def model_dump(self) -> dict[str, Any]:
        return asdict(self)


UpdatedProgramPayload = ProgramPayload
