"""Lightweight fallback when pydantic_ai is unavailable."""

from __future__ import annotations

from typing import Any

from core.enums import CoachType, WorkoutType
from core.schemas import Program, QAResponse, Subscription
from ai_coach.model_settings import ModelSettings


class ProgramAdapter:
    """Minimal adapter to mirror real implementation."""

    @staticmethod
    def to_domain(payload: Any) -> Program:
        data = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload)
        data.pop("schema_version", None)
        if data.get("coach_type") == "ai":
            data["coach_type"] = CoachType.ai
        program = Program(**data)
        if program.split_number is None:
            program.split_number = len(program.exercises_by_day)
        return program


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
        agent = cls._get_agent()
        mode = "subscription" if output_type is Subscription else "program"
        parts = [f"MODE: {mode}", "WORKOUT PROGRAM RULES"]
        if workout_type:
            parts.append(f"Workout type: {workout_type.value}")
        if instructions:
            parts.append(instructions)
        if prompt:
            parts.append(prompt)
        full_prompt = "\n".join(parts)
        history = cls._message_history(deps.client_id)
        return await agent.run(full_prompt, deps, output_type, history)

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
        agent = cls._get_agent()
        parts = [
            "MODE: update",
            "WORKOUT PROGRAM RULES",
            f"Client Feedback: {feedback}",
            f"Expected Workout: {expected_workout}",
        ]
        if workout_type:
            parts.append(f"Workout type: {workout_type.value}")
        if instructions:
            parts.append(instructions)
        if prompt:
            parts.append(prompt)
        full_prompt = "\n".join(parts)
        history = cls._message_history(deps.client_id)
        return await agent.run(full_prompt, deps, output_type, history)

    @classmethod
    async def answer_question(cls, prompt: str, deps: Any) -> QAResponse:
        agent = cls._get_agent()
        prompt = f"MODE: ask_ai\n{prompt}"
        history = cls._message_history(deps.client_id)
        return await agent.run(prompt, deps, QAResponse, ModelSettings(), history)

    @classmethod
    def _get_agent(cls) -> Any:  # pragma: no cover - stub
        raise RuntimeError("pydantic_ai package is required")

    @staticmethod
    def _message_history(client_id: int) -> list[Any]:
        return []
