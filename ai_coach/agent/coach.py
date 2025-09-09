from __future__ import annotations

import os
from datetime import date
from typing import Any

from pydantic_ai.settings import ModelSettings

from config.app_settings import settings
from core.enums import WorkoutType
from core.schemas import Program, QAResponse, Subscription

from .base import AgentDeps
from .prompts import (
    COACH_SYSTEM_PROMPT,
    UPDATE_WORKOUT,
    GENERATE_WORKOUT,
    COACH_INSTRUCTIONS,
)

from .tools import toolset
from ..schemas import ProgramPayload

from pydantic_ai import Agent, RunContext
from pydantic_ai.models.openai import OpenAIChatModel


class ProgramAdapter:
    """Utility to convert agent payloads to API models."""

    @staticmethod
    def to_domain(payload: ProgramPayload) -> Program:
        data = payload.model_dump(exclude={"schema_version"})
        return Program.model_validate(data)


class CoachAgent:
    """PydanticAI wrapper for program generation."""

    _agent: Any | None = None

    @staticmethod
    def _lang(deps: AgentDeps) -> str:
        return deps.locale or settings.DEFAULT_LANG

    @classmethod
    def _init_agent(cls) -> Any:
        if Agent is None or OpenAIChatModel is None:
            raise RuntimeError("pydantic_ai package is required")

        os.environ.setdefault("OPENAI_API_KEY", settings.LLM_API_KEY)
        os.environ.setdefault("OPENAI_BASE_URL", settings.LLM_API_URL)

        model = OpenAIChatModel(
            model_name=settings.LLM_MODEL,
            provider=settings.LLM_PROVIDER,
            settings=ModelSettings(
                timeout=float(settings.COACH_AGENT_TIMEOUT),
            ),
        )
        cls._agent = Agent(
            model=model,
            deps_type=AgentDeps,
            toolsets=[toolset],
            retries=settings.COACH_AGENT_RETRIES,
            system_prompt=COACH_SYSTEM_PROMPT,
        )

        @cls._agent.system_prompt
        async def coach_sys(
            ctx: RunContext[AgentDeps],  # pyrefly: ignore[unsupported-operation]
        ) -> str:  # pragma: no cover - runtime config
            lang = ctx.deps.locale or settings.DEFAULT_LANG
            client_name = ctx.deps.client_name or "the client"
            return f"Client's name: {client_name}\nClient's language: {lang}"

        return cls._agent

    @classmethod
    def _get_agent(cls) -> Any:
        if cls._agent is None:
            return cls._init_agent()
        return cls._agent

    @classmethod
    async def generate_workout_plan(
        cls,
        prompt: str | None,
        deps: AgentDeps,
        *,
        workout_type: WorkoutType | None = None,
        period: str | None = None,
        workout_days: list[str] | None = None,
        wishes: str | None = None,
        result_type: type[Program] | type[Subscription],
    ) -> Program | Subscription:
        agent = cls._get_agent()
        today = date.today().isoformat()
        context_lines: list[str] = []
        if workout_type:
            context_lines.append(f"Workout type: {workout_type.value}")
        if prompt:
            context_lines.append(prompt)
        if period:
            context_lines.append(f"Period: {period}")
        if workout_days:
            context_lines.append(f"Workout days: {', '.join(workout_days)}")
        if wishes:
            context_lines.append(f"Wishes: {wishes}")
        mode = "program" if result_type is Program else "subscription"
        formatted = GENERATE_WORKOUT.format(
            current_date=today,
            request_context="\n".join(context_lines),
            workout_rules=COACH_INSTRUCTIONS,
            language=cls._lang(deps),
        )
        user_prompt = f"MODE: {mode}\n{formatted}"
        result: Program | Subscription = await agent.run(user_prompt, deps=deps, result_type=result_type)
        return result

    @classmethod
    async def update_workout_plan(
        cls,
        prompt: str | None,
        expected_workout: str,
        feedback: str,
        deps: AgentDeps,
        *,
        workout_type: WorkoutType | None = None,
        result_type: type[Program] | type[Subscription] = Subscription,
    ) -> Program | Subscription:
        agent = cls._get_agent()
        context_lines: list[str] = []
        if workout_type:
            context_lines.append(f"Workout type: {workout_type.value}")
        if prompt:
            context_lines.append(prompt)
        formatted = UPDATE_WORKOUT.format(
            expected_workout=expected_workout,
            feedback=feedback,
            context="\n".join(context_lines),
            language=cls._lang(deps),
        )
        user_prompt = f"MODE: update\n{formatted}\nRules:\n{COACH_INSTRUCTIONS}"
        result: Program | Subscription = await agent.run(user_prompt, deps=deps, result_type=result_type)
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
