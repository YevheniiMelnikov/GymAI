from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from pydantic import BaseModel


class MessageRole(str, Enum):
    """Role of a chat message."""

    CLIENT = "client"
    AI_COACH = "ai_coach"


class AskRequest(BaseModel):
    prompt: str
    client_id: int
    language: str | None = None
    request_id: str | None = None


class MessageRequest(BaseModel):
    text: str
    client_id: int


@dataclass
class CogneeUser:
    id: Any
    tenant_id: Any | None = None
    roles: list[str] | None = None
