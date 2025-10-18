from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class AiAnswerNotify(BaseModel):
    request_id: str
    status: str = "success"
    client_id: int
    client_profile_id: Optional[int] = None
    answer: Optional[str] = None
    sources: List[str] = Field(default_factory=list)
    error: Optional[str] = None

    @field_validator("status", mode="before")
    @classmethod
    def _normalize_status(cls, value: str) -> str:
        return (value or "success").lower()
