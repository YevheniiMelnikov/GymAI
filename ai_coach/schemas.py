from __future__ import annotations

from enum import Enum

# pydantic is optional for tests; provide a minimal stub if missing
try:  # pragma: no cover - exercised indirectly in tests
    from pydantic import BaseModel
except Exception:  # pragma: no cover
    class BaseModel:  # type: ignore[override]
        def __init__(self, **data):
            for k, v in data.items():
                setattr(self, k, v)


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
