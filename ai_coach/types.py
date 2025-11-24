from enum import Enum
from typing import TYPE_CHECKING, NotRequired, TypedDict

from core.enums import WorkoutPlanType, WorkoutType

if TYPE_CHECKING:  # pragma: no cover - runtime import avoidance
    from ai_coach.agent import AgentDeps


class CoachMode(str, Enum):
    """Supported modes for /ask endpoint."""

    program = "program"
    subscription = "subscription"
    update = "update"
    ask_ai = "ask_ai"


class MessageRole(str, Enum):
    """Role of a chat message."""

    CLIENT = "client"
    AI_COACH = "ai_coach"


class AskCtx(TypedDict):
    """Context passed to dispatch functions."""

    prompt: str | None
    profile_id: int
    period: str
    workout_days: list[str]
    expected_workout: str
    feedback: str
    wishes: str
    language: str
    workout_type: WorkoutType | None
    plan_type: WorkoutPlanType | None
    instructions: NotRequired[str | None]
    deps: NotRequired["AgentDeps"]
