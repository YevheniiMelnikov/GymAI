"""Lightweight fallback when pydantic_ai is unavailable."""

from __future__ import annotations

from typing import Any

from core.enums import WorkoutType
from core.schemas import Program, QAResponse, Subscription


class ProgramAdapter:
    """Minimal adapter to mirror real implementation."""

    @staticmethod
    def to_domain(payload: Any) -> Program:
        return Program.model_validate(payload)


class CoachAgent:
    """Placeholder for tests without heavy dependencies."""

    @classmethod
    async def generate_workout_plan(
        cls,
        prompt: str | None,
        deps: Any,
        *,
        workout_type: WorkoutType | None = None,
        period: str | None = None,
        workout_days: list[str] | None = None,
        wishes: str | None = None,
        output_type: type[Program] | type[Subscription] = Program,
        instructions: str | None = None,
    ) -> Program | Subscription:
        raise RuntimeError("pydantic_ai package is required")

    @classmethod
    async def update_workout_plan(
        cls,
        prompt: str | None,
        expected_workout: str,
        feedback: str,
        deps: Any,
        *,
        workout_type: WorkoutType | None = None,
        output_type: type[Program] | type[Subscription] = Program,
        instructions: str | None = None,
    ) -> Program | Subscription:
        raise RuntimeError("pydantic_ai package is required")

    @classmethod
    async def answer_question(cls, prompt: str, deps: Any) -> QAResponse:
        raise RuntimeError("pydantic_ai package is required")
