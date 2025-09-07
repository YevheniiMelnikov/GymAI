from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from ai_coach.types import CoachMode


class AskRequest(BaseModel):
    client_id: int
    prompt: str
    language: str | None = None
    mode: CoachMode = CoachMode.program
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
