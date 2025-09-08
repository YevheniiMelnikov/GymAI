from __future__ import annotations

from pathlib import Path
from typing import Any

from config.app_settings import settings
from core.schemas import Program, QAResponse, Subscription

from .base import AgentDeps
from .tools import get_all_tools
from ..schemas import ProgramPayload

try:  # pragma: no cover - optional dependency
    from pydantic_ai import Agent, RunContext
    from pydantic_ai.models.openai import OpenAIChatModel
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
    SYSTEM_PROMPT_PATH = Path(__file__).with_name("prompts") / "coach_system_prompt.txt"

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
                tools=get_all_tools(),
                result_type=ProgramPayload,
                retries=settings.COACH_AGENT_RETRIES,
            )

            @cls._agent.system_prompt
            async def coach_sys(ctx: RunContext[AgentDeps]) -> str:  # pragma: no cover - runtime config
                lang = ctx.deps.locale or settings.DEFAULT_LANG
                prompt = cls.SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
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
