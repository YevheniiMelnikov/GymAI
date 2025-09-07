from enum import Enum
from typing import TYPE_CHECKING, NotRequired, TypedDict

if TYPE_CHECKING:  # pragma: no cover - runtime import avoidance
    from ai_coach.coach_agent import AgentDeps


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

    prompt: str
    client_id: int
    period: str
    workout_days: list[str]
    expected_workout: str
    feedback: str
    language: str
    deps: NotRequired["AgentDeps"]
