from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class JudgeScore(BaseModel):
    profile_alignment: int = Field(ge=0, le=5)
    safety: int = Field(ge=0, le=5)
    usefulness: int = Field(ge=0, le=5)
    faithfulness_to_kb: int = Field(ge=0, le=5)
    comment: str


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    question: str
    tags: list[str]
    expectations: dict[str, Any]


@dataclass(frozen=True)
class EvalCaseResult:
    case_id: str
    question: str
    passed: bool
    failures: list[str]
    score: JudgeScore | None
    answer_preview: str
    answer: str
    sources: list[str]
    error: str | None


@dataclass(frozen=True)
class EvalRunMeta:
    started_at: datetime
    duration_s: float
    ai_coach_url: str
    agent_model: str
    agent_temperature: str
    judge_model: str
    judge_temperature: str
    profile_id: int | None
    tg_id: int | None
    cases_total: int
    git_commit: str | None
    run_error: str | None = None
    warnings: list[str] | None = None
