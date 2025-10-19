from __future__ import annotations

from datetime import datetime
import inspect
from typing import Any, Optional

from zoneinfo import ZoneInfo

from openai import AsyncOpenAI  # pyrefly: ignore[import-error]
from pydantic_ai.settings import ModelSettings  # pyrefly: ignore[import-error]
from pydantic import BaseModel
from loguru import logger  # pyrefly: ignore[import-error]

from config.app_settings import settings
from core.enums import WorkoutType
from core.schemas import Program, Subscription
from core.schemas import QAResponse
from core.enums import CoachType

from .base import AgentDeps
from .prompts import (
    COACH_SYSTEM_PROMPT,
    UPDATE_WORKOUT,
    GENERATE_WORKOUT,
    COACH_INSTRUCTIONS,
    agent_instructions,
)

from .tools import toolset
from ..schemas import ProgramPayload
from pydantic_ai import Agent, RunContext  # pyrefly: ignore[import-error]
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart  # pyrefly: ignore[import-error]
from pydantic_ai.models.openai import OpenAIChatModel  # pyrefly: ignore[import-error]
from ai_coach.types import CoachMode, MessageRole
from ai_coach.agent.knowledge.knowledge_base import KnowledgeBase


class ProgramAdapter:
    """Utility to convert agent payloads to API models."""

    @staticmethod
    def to_domain(payload: ProgramPayload) -> Program:
        data = payload.model_dump(exclude={"schema_version"})
        coach_type = getattr(payload, "_coach_type_raw", data.get("coach_type"))
        if isinstance(coach_type, str):
            normalized = coach_type.lower()
            mapping = {
                "ai": CoachType.ai_coach,
                "ai_coach": CoachType.ai_coach,
                "human": CoachType.human,
            }
            data["coach_type"] = mapping.get(normalized, CoachType.ai_coach)
        if data.get("split_number") is None:
            data["split_number"] = len(getattr(payload, "exercises_by_day", []))
        return Program.model_validate(data)


class CoachAgent:
    """PydanticAI wrapper for program generation."""

    _agent: Optional[Agent] = None

    @staticmethod
    def _lang(deps: AgentDeps) -> str:
        language: str = deps.locale or getattr(settings, "DEFAULT_LANG", "en")
        return language

    @classmethod
    def _init_agent(cls) -> Any:
        if Agent is None or OpenAIChatModel is None:
            raise RuntimeError("pydantic_ai package is required")

        provider_config: Any = settings.AGENT_PROVIDER
        if isinstance(provider_config, str):
            provider_name: str | None = provider_config.strip().lower()
        else:
            provider_name = None

        provider: Any = provider_config
        client_override: AsyncOpenAI | None = None

        if provider_name == "openrouter":
            try:
                from pydantic_ai.providers.openrouter import OpenRouterProvider  # pyrefly: ignore[import-error]
            except Exception as exc:  # pragma: no cover - optional dependency
                raise RuntimeError("OpenRouter provider is not available") from exc

            api_key: str = settings.LLM_API_KEY
            if not api_key:
                raise RuntimeError("LLM_API_KEY must be configured when using the OpenRouter provider")
            provider = OpenRouterProvider(api_key=api_key)
        else:
            if settings.LLM_API_KEY or settings.LLM_API_URL:
                client_override = AsyncOpenAI(
                    api_key=settings.LLM_API_KEY or None,
                    base_url=settings.LLM_API_URL or None,
                )

        model = OpenAIChatModel(
            model_name=settings.AGENT_MODEL,
            provider=provider,
            settings=ModelSettings(
                timeout=float(settings.COACH_AGENT_TIMEOUT),
            ),
        )

        if client_override is not None:
            model.client = client_override

        cls._agent = Agent(
            model=model,
            deps_type=AgentDeps,
            toolsets=[toolset],
            retries=settings.COACH_AGENT_RETRIES,
            system_prompt=COACH_SYSTEM_PROMPT,
        )  # pyrefly: ignore[no-matching-overload]

        @cls._agent.system_prompt  # pyrefly: ignore[no-matching-overload]
        async def coach_sys(ctx: RunContext[AgentDeps]) -> str:  # pyrefly: ignore[unsupported-operation]
            lang = ctx.deps.locale or settings.DEFAULT_LANG
            client_name = ctx.deps.client_name or "the client"
            return f"Client's name: {client_name}\nClient's language: {lang}"

        @cls._agent.instructions  # pyrefly: ignore[no-matching-overload]
        def agent_instr(ctx: RunContext[AgentDeps]) -> str:  # pragma: no cover - runtime config
            mode = ctx.deps.mode.value if ctx.deps.mode else "ask_ai"
            return agent_instructions(mode)

        return cls._agent

    @classmethod
    def _get_agent(cls) -> Any:
        if cls._agent is None:
            return cls._init_agent()
        return cls._agent

    @staticmethod
    def _normalize_output(
        raw: Any,
        expected: type[Program] | type[Subscription] | type[QAResponse],
    ) -> Program | Subscription | QAResponse:
        value = getattr(raw, "output", raw)
        if isinstance(value, expected):
            return value
        if issubclass(expected, BaseModel):
            return expected.model_validate(value)
        return expected(**value)

    @staticmethod
    async def _message_history(client_id: int) -> list[ModelMessage]:
        """Prepare past messages for the agent."""
        raw = await KnowledgeBase.get_message_history(client_id)
        history: list[ModelMessage] = []
        for item in raw:
            if item.startswith(f"{MessageRole.CLIENT.value}:"):
                text = item.split(":", 1)[1]
                history.append(ModelRequest.user_text_prompt(text.strip()))
            elif item.startswith(f"{MessageRole.AI_COACH.value}:"):
                text = item.split(":", 1)[1]
                history.append(ModelResponse(parts=[TextPart(content=text.strip())]))
        return history

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
        output_type: type[Program] | type[Subscription],
        instructions: str | None = None,
    ) -> Program | Subscription:
        deps.mode = CoachMode.program if output_type is Program else CoachMode.subscription
        if deps.mode in (CoachMode.program, CoachMode.subscription):
            deps.max_run_seconds = 0.0
            deps.max_tool_calls = 8 if deps.mode is CoachMode.program else 6
        agent = cls._get_agent()
        today = datetime.now(ZoneInfo(settings.TIME_ZONE)).date().isoformat()
        context_lines: list[str] = []
        if workout_type:
            context_lines.append(f"Workout type: {workout_type.value}")
        if prompt:
            context_lines.append(prompt)
        if period:
            context_lines.append(f"Period: {period}")
        effective_days = workout_days or ["Пн", "Ср", "Пт", "Сб"]
        if effective_days:
            context_lines.append(f"Workout days: {', '.join(effective_days)}")
        if wishes:
            context_lines.append(f"Wishes: {wishes}")
        mode = "program" if output_type is Program else "subscription"
        rules = "\n".join(filter(None, [COACH_INSTRUCTIONS, instructions]))
        formatted = GENERATE_WORKOUT.format(
            current_date=today,
            request_context="\n".join(context_lines),
            workout_rules=rules,
            language=cls._lang(deps),
        )
        user_prompt = f"MODE: {mode}\n{formatted}"
        history = cls._message_history(deps.client_id)
        if inspect.isawaitable(history):
            history = await history
        raw_result = await agent.run(
            user_prompt,
            deps=deps,
            output_type=output_type,
            message_history=history,
            model_settings=ModelSettings(response_format={"type": "json_object"}, temperature=0.2),
        )
        normalized = cls._normalize_output(raw_result, output_type)
        logger.debug(
            "agent.done client_id=%s mode=%s tools_called=%s",
            deps.client_id,
            deps.mode.value if deps.mode else "unknown",
            sorted(deps.called_tools),
        )
        return normalized

    @classmethod
    async def update_workout_plan(
        cls,
        prompt: str | None,
        expected_workout: str,
        feedback: str,
        deps: AgentDeps,
        *,
        workout_type: WorkoutType | None = None,
        output_type: type[Program] | type[Subscription] = Subscription,
        instructions: str | None = None,
    ) -> Program | Subscription:
        agent = cls._get_agent()
        deps.mode = CoachMode.update
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
        rules = "\n".join(filter(None, [COACH_INSTRUCTIONS, instructions]))
        user_prompt = f"MODE: update\n{formatted}\nRules:\n{rules}"
        history = cls._message_history(deps.client_id)
        if inspect.isawaitable(history):
            history = await history
        raw_result = await agent.run(
            user_prompt,
            deps=deps,
            output_type=output_type,
            message_history=history,
            model_settings=ModelSettings(response_format={"type": "json_object"}, temperature=0.2),
        )
        return cls._normalize_output(raw_result, output_type)

    @classmethod
    async def answer_question(
        cls,
        prompt: str,
        deps: AgentDeps,
    ) -> QAResponse:
        agent = cls._get_agent()
        deps.mode = CoachMode.ask_ai
        user_prompt = f"MODE: ask_ai\n{prompt}"
        history = cls._message_history(deps.client_id)
        if inspect.isawaitable(history):
            history = await history
        raw_result = await agent.run(
            user_prompt,
            deps=deps,
            output_type=QAResponse,
            model_settings=ModelSettings(temperature=0.3, max_tokens=256),
            message_history=history,
        )
        return cls._normalize_output(raw_result, QAResponse)
