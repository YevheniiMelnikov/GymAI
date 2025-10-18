from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


class QAResponse(BaseModel):
    answer: str
    sources: List[str] = Field(default_factory=list)
