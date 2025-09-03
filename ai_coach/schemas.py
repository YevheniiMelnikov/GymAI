from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel


class MessageRole(str, Enum):
    """Role of a chat message."""

    CLIENT = "client"
    AI_COACH = "ai_coach"


class AskRequest(BaseModel):
    client_id: int
    prompt: str
    language: str | None = None
    mode: Literal["program", "subscription", "update", "ask_ai"] = "program"
    period: str | None = None
    workout_days: list[str] | None = None
    expected_workout: str | None = None
    feedback: str | None = None
    request_id: str | None = None


class MessageRequest(BaseModel):
    text: str
    client_id: int


@dataclass
class CogneeUser:
    id: Any
    tenant_id: Any | None = None
    roles: list[str] | None = None
