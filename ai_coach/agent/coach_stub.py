"""Lightweight fallback when pydantic_ai is unavailable."""

from __future__ import annotations

from typing import Any

from core.enums import CoachType, WorkoutType
from core.schemas import Program, QAResponse, Subscription
from pydantic_ai.settings import ModelSettings


class ProgramAdapter:
    """Minimal adapter to mirror real implementation."""

    @staticmethod
    def to_domain(payload: Any) -> Program:
        data = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload)
        data.pop("schema_version", None)
        if data.get("coach_type") == "ai":
            data["coach_type"] = CoachType.ai
        return Program(**data)


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
        agent = cls._get_agent()
        prompt = f"MODE: ask_ai\n{prompt}"
        return await agent.run(prompt, deps, QAResponse, ModelSettings())

    @classmethod
    def _get_agent(cls) -> Any:  # pragma: no cover - stub
        raise RuntimeError("pydantic_ai package is required")
