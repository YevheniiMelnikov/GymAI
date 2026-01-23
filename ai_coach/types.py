from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, NotRequired, TypedDict

from core.enums import WorkoutPlanType, WorkoutLocation

if TYPE_CHECKING:
    from ai_coach.agent import AgentDeps


class CoachMode(str, Enum):
    """Supported modes for coach endpoints."""

    program = "program"
    subscription = "subscription"
    update = "update"
    ask_ai = "ask_ai"
    diet = "diet"


class MessageRole(str, Enum):
    """Role of a chat message."""

    CLIENT = "client"
    AI_COACH = "ai_coach"


class AskCtx(TypedDict):
    """Context passed to dispatch functions."""

    prompt: str | None
    profile_id: int
    attachments: NotRequired[list[dict[str, str]] | None]
    period: str
    split_number: int
    feedback: str
    wishes: str
    language: str
    workout_location: WorkoutLocation | None
    plan_type: WorkoutPlanType | None
    diet_allergies: NotRequired[str | None]
    diet_products: NotRequired[list[str]]
    profile_context: NotRequired[str | None]
    instructions: NotRequired[str | None]
    deps: NotRequired["AgentDeps"]
