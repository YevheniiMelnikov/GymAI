from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator

from config.app_settings import settings
from core.schemas import DayExercises, Program, QAResponse, Subscription

from .base import AgentDeps
from .tools import (
    tool_attach_gifs,
    tool_create_subscription,
    tool_get_client_context,
    tool_get_program_history,
    tool_save_program,
    tool_search_knowledge,
)

try:  # pragma: no cover - optional dependency
    from pydantic_ai import Agent, RunContext
    from pydantic_ai.models.openai import OpenAIChatModel
except Exception:  # pragma: no cover - optional dependency
    Agent = None  # type: ignore[assignment]
    RunContext = Any  # type: ignore[assignment]
    OpenAIChatModel = None  # type: ignore[assignment]


SYSTEM_PROMPT_PATH = Path(__file__).with_name("prompts") / "coach_system_prompt.txt"


class ProgramPayload(Program):
    """Program schema used by the agent (allows schema_version)."""

    schema_version: str | None = Field(
        default=None,
        description="Internal schema version used by the agent; dropped before save",
    )

    @model_validator(mode="after")
    def _validate_invariants(self) -> "ProgramPayload":
        if not self.exercises_by_day:
            raise ValueError("exercises_by_day must not be empty")
        for day in self.exercises_by_day:
            if not day.exercises:
                raise ValueError("day exercises must not be empty")
            for ex in day.exercises:
                if not (ex.name and ex.sets and ex.reps):
                    raise ValueError("exercise must have name, sets and reps")
        if self.split_number is None:
            self.split_number = len(self.exercises_by_day)
        return self


class SubscriptionPayload(BaseModel):
    """Subscription schema produced by the agent."""

    workout_days: list[str]
    exercises: list[DayExercises]
    wishes: str | None = None
    schema_version: str | None = None

    @model_validator(mode="after")
    def _check(self) -> "SubscriptionPayload":
        if not self.workout_days:
            raise ValueError("workout_days must not be empty")
        if not self.exercises:
            raise ValueError("exercises must not be empty")
        return self


UpdatedProgramPayload = ProgramPayload


class ProgramAdapter:
    """Utility to convert agent payloads to API models."""

    @staticmethod
    def to_domain(payload: ProgramPayload) -> Program:
        data = payload.model_dump(exclude={"schema_version"})
        return Program.model_validate(data)


class CoachAgent:
    """PydanticAI wrapper for program generation."""

    _agent: Any | None = None

    @classmethod
    def _get_agent(cls) -> Any:
        if Agent is None or OpenAIChatModel is None:
            raise RuntimeError("pydantic_ai package is required")
        if cls._agent is None:
            model = OpenAIChatModel(
                settings.LLM_MODEL,
                api_key=settings.LLM_API_KEY,
                base_url=settings.LLM_API_URL,
                timeout=settings.COACH_AGENT_TIMEOUT,
            )
            cls._agent = Agent(
                model=model,
                deps_type=AgentDeps,
                tools=[
                    tool_get_client_context,
                    tool_search_knowledge,
                    tool_get_program_history,
                    tool_attach_gifs,
                    tool_save_program,
                    tool_create_subscription,
                ],
                result_type=ProgramPayload,
                retries=settings.COACH_AGENT_RETRIES,
            )

            @cls._agent.system_prompt
            async def coach_sys(ctx: RunContext[AgentDeps]) -> str:  # pragma: no cover - runtime config
                lang = ctx.deps.locale or settings.DEFAULT_LANG
                prompt = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
                return prompt.format(locale=lang)

        return cls._agent

    @classmethod
    async def generate_program(cls, prompt: str, deps: AgentDeps) -> Program:
        agent = cls._get_agent()
        user_prompt = f"MODE: program\n{prompt}".strip()
        result: Program = await agent.run(user_prompt, deps=deps, result_type=Program)
        return result

    @classmethod
    async def generate_subscription(
        cls,
        prompt: str,
        period: str,
        workout_days: list[str],
        deps: AgentDeps,
        wishes: str | None = None,
    ) -> Subscription:
        agent = cls._get_agent()
        extra = (
            "\nMODE: subscription"
            + f"\nPeriod: {period}"
            + f"\nWorkout days: {', '.join(workout_days)}"
            + f"\nWishes: {wishes or ''}"
        )
        user_prompt = (prompt + extra).strip()
        result: Subscription = await agent.run(
            user_prompt,
            deps=deps,
            result_type=Subscription,
        )
        return result

    @classmethod
    async def update_program(cls, prompt: str, expected_workout: str, feedback: str, deps: AgentDeps) -> Program:
        agent = cls._get_agent()
        extra = "\nMODE: update" + f"\n--- Expected Workout ---\n{expected_workout}" + f"\n--- Feedback ---\n{feedback}"
        user_prompt = (prompt + extra).strip()
        result: Program = await agent.run(user_prompt, deps=deps, result_type=Program)
        return result

    @classmethod
    async def answer_question(cls, prompt: str, deps: AgentDeps) -> QAResponse:
        agent = cls._get_agent()
        user_prompt = f"MODE: ask_ai\n{prompt}"
        result: QAResponse = await agent.run(
            user_prompt,
            deps=deps,
            result_type=QAResponse,
            temperature=0.3,
            max_output_tokens=256,
        )
        return result
