from __future__ import annotations

from enum import Enum

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
