from __future__ import annotations

from datetime import date
from typing import Any

from config.app_settings import settings
from core.schemas import Program, QAResponse, Subscription

from .base import AgentDeps
from .prompts import (
    COACH_SYSTEM_PROMPT,
    UPDATE_WORKOUT_PROMPT,
    WORKOUT_PLAN_PROMPT,
    WORKOUT_RULES,
)
from .tools import toolset
from ..schemas import ProgramPayload

try:  # pragma: no cover - optional dependency
    from pydantic_ai import Agent, RunContext  # pyrefly: ignore[import-error]
    from pydantic_ai.models.openai import OpenAIChatModel  # pyrefly: ignore[import-error]
except Exception:  # pragma: no cover - optional dependency
    Agent = None  # type: ignore[assignment]
    RunContext = Any  # type: ignore[assignment]
    OpenAIChatModel = None  # type: ignore[assignment]


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
                tools=toolset,
                retries=settings.COACH_AGENT_RETRIES,
            )

            @cls._agent.system_prompt
            async def coach_sys(
                ctx: RunContext[AgentDeps],  # pyrefly: ignore[unsupported-operation]
            ) -> str:  # pragma: no cover - runtime config
                lang = ctx.deps.locale or settings.DEFAULT_LANG
                client_name = ctx.deps.client_name or "the client"
                return COACH_SYSTEM_PROMPT.format(locale=lang, client_name=client_name)

        return cls._agent

    @classmethod
    async def generate_program(cls, prompt: str, deps: AgentDeps) -> Program:
        agent = cls._get_agent()
        request_context = prompt
        formatted = WORKOUT_PLAN_PROMPT.format(
            current_date=date.today().isoformat(),
            request_context=request_context,
            workout_rules=WORKOUT_RULES,
            language=deps.locale or settings.DEFAULT_LANG,
        )
        user_prompt = f"MODE: program\n{formatted}".strip()
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
        request_parts = [prompt, f"Period: {period}", f"Workout days: {', '.join(workout_days)}"]
        if wishes:
            request_parts.append(f"Wishes: {wishes}")
        request_context = "\n".join(request_parts)
        formatted = WORKOUT_PLAN_PROMPT.format(
            current_date=date.today().isoformat(),
            request_context=request_context,
            workout_rules=WORKOUT_RULES,
            language=deps.locale or settings.DEFAULT_LANG,
        )
        user_prompt = f"MODE: subscription\n{formatted}".strip()
        result: Subscription = await agent.run(
            user_prompt,
            deps=deps,
            result_type=Subscription,
        )
        return result

    @classmethod
    async def update_program(cls, prompt: str, expected_workout: str, feedback: str, deps: AgentDeps) -> Program:
        agent = cls._get_agent()
        formatted = UPDATE_WORKOUT_PROMPT.format(
            expected_workout=expected_workout,
            feedback=feedback,
            context=prompt,
            language=deps.locale or settings.DEFAULT_LANG,
        )
        user_prompt = ("MODE: update\n" + formatted + "\nRules:\n" + WORKOUT_RULES).strip()
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
