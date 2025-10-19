import json
import inspect
from datetime import datetime
from typing import Any, Optional, Sequence, TypeVar

from zoneinfo import ZoneInfo

from openai import AsyncOpenAI  # pyrefly: ignore[import-error]
from pydantic_ai.settings import ModelSettings  # pyrefly: ignore[import-error]
from pydantic import BaseModel
from loguru import logger  # pyrefly: ignore[import-error]
from pydantic_ai.exceptions import UnexpectedModelBehavior  # pyrefly: ignore[import-error]

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
from ai_coach.exceptions import AgentExecutionAborted


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


TOutput = TypeVar("TOutput", bound=BaseModel)


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
        expected: type[TOutput],
    ) -> TOutput:
        value = getattr(raw, "output", raw)
        if isinstance(value, expected):
            return value
        if not issubclass(expected, BaseModel):
            raise TypeError(f"Unsupported output type: {expected!r}")
        return expected.model_validate(value)

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
        if output_type is Program:
            normalized = cls._normalize_output(raw_result, Program)
        else:
            normalized = cls._normalize_output(raw_result, Subscription)
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
        if output_type is Program:
            return cls._normalize_output(raw_result, Program)
        return cls._normalize_output(raw_result, Subscription)

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
        prefetched_knowledge: list[str] = []
        try:
            prefetched_knowledge = await KnowledgeBase.search(prompt, deps.client_id, 6)
        except Exception as exc:  # noqa: BLE001 - prefetch should not block main flow
            logger.warning(f"agent.ask knowledge_prefetch_failed client_id={deps.client_id} error={exc}")
        entries_count = sum(1 for item in prefetched_knowledge if (item or "").strip())
        deps.knowledge_base_empty = entries_count == 0
        logger.debug(
            (
                f"agent.ask knowledge_prefetch client_id={deps.client_id} entries={entries_count} "
                f"kb_empty={deps.knowledge_base_empty}"
            )
        )
        try:
            raw_result = await agent.run(
                user_prompt,
                deps=deps,
                output_type=QAResponse,
                model_settings=ModelSettings(temperature=0.3, max_tokens=256),
                message_history=history,
            )
        except UnexpectedModelBehavior as exc:
            reason = "knowledge_base_empty" if deps.knowledge_base_empty else "model_empty_response"
            detail = str(exc)
            logger.info(f"agent.ask aborted client_id={deps.client_id} reason={reason} detail={detail}")
            if reason == "model_empty_response":
                fallback = await cls._fallback_answer_question(
                    prompt,
                    deps,
                    history,
                    prefetched_knowledge=prefetched_knowledge,
                )
                if fallback is not None:
                    return fallback
            message = (
                "AI coach knowledge base returned no data"
                if reason == "knowledge_base_empty"
                else "AI coach returned an empty model response"
            )
            raise AgentExecutionAborted(message, reason=reason) from exc
        return cls._normalize_output(raw_result, QAResponse)

    @classmethod
    async def _fallback_answer_question(
        cls,
        prompt: str,
        deps: AgentDeps,
        history: list[ModelMessage],
        *,
        prefetched_knowledge: Sequence[str] | None = None,
    ) -> QAResponse | None:
        if deps.fallback_used:
            logger.debug(f"agent.ask fallback skipped client_id={deps.client_id} reason=already_used")
            return None
        deps.fallback_used = True
        logger.warning(
            f"agent.ask fallback_invoked client_id={deps.client_id} reason=model_empty_response history={len(history)}"
        )
        agent = cls._get_agent()
        model = getattr(agent, "model", None)
        client: AsyncOpenAI | None = getattr(model, "client", None)
        if client is None:
            logger.warning(f"agent.ask fallback aborted client_id={deps.client_id} reason=missing_client")
            return None
        knowledge: Sequence[str]
        if prefetched_knowledge is not None:
            knowledge = prefetched_knowledge
        else:
            try:
                knowledge = await KnowledgeBase.search(prompt, deps.client_id, 6)
            except Exception as exc:  # noqa: BLE001 - log and continue with empty knowledge
                logger.warning(f"agent.ask fallback knowledge_failed client_id={deps.client_id} error={exc}")
                knowledge = []
        entries: list[str] = []
        entry_ids: list[str] = []
        for idx, raw in enumerate(knowledge, start=1):
            text = str(raw or "").strip()
            if not text:
                continue
            entry_id = f"KB-{idx}"
            entry_ids.append(entry_id)
            entries.append(f"{entry_id}: {text}")
        if entry_ids:
            deps.knowledge_base_empty = False
        language = cls._lang(deps)
        knowledge_section = "\n\n".join(entries) if entries else "No knowledge entries were retrieved."
        system_prompt = (
            "You are a professional fitness coach. Use the provided knowledge entries when available. "
            "Answer in the client's language and keep the tone concise and helpful. "
            "Return JSON with keys 'answer' and 'sources' when structured output is supported. "
            "If no knowledge entries are available, rely on professional expertise "
            "and use ['general_knowledge'] as sources."
        )
        user_prompt = (
            f"Client language: {language}\n"
            f"Client question: {prompt}\n"
            "Knowledge entries:\n"
            f"{knowledge_section}\n"
            "Return a helpful answer and list the sources used (or ['general_knowledge'] when none are available)."
        )
        supports_json = cls._supports_json_object(model)
        attempt_modes = [True, False] if supports_json else [False]
        answer: str = ""
        sources: list[str] = []
        for index, as_json in enumerate(attempt_modes):
            second_attempt = index > 0
            try:
                response = await cls._run_fallback_completion(
                    client,
                    system_prompt,
                    user_prompt,
                    use_json=as_json,
                )
            except Exception as exc:  # noqa: BLE001
                mode = "json" if as_json else "text"
                logger.warning(
                    f"agent.ask fallback completion_failed client_id={deps.client_id} mode={mode} error={exc}"
                )
                continue
            content = cls._extract_choice_content(response)
            if not content:
                logger.warning(
                    f"agent.ask fallback empty_content client_id={deps.client_id} second_attempt={second_attempt}"
                )
                continue
            answer, sources = cls._parse_fallback_content(
                content,
                entry_ids,
                expects_json=as_json,
                client_id=deps.client_id,
            )
            if answer:
                logger.info(
                    (
                        f"agent.ask fallback_success client_id={deps.client_id} answer_len={len(answer)} "
                        f"sources={len(sources)} kb_empty={not entry_ids} second_attempt={second_attempt}"
                    )
                )
                if not entry_ids:
                    deps.knowledge_base_empty = True
                return QAResponse(answer=answer, sources=sources)
        logger.warning(f"agent.ask fallback missing_answer client_id={deps.client_id} kb_empty={not entry_ids}")
        if not entry_ids:
            deps.knowledge_base_empty = True
        return None

    @staticmethod
    def _supports_json_object(model: Any) -> bool:
        model_name = getattr(model, "model_name", None) or getattr(model, "name", None)
        if not model_name:
            return False
        normalized = str(model_name).lower()
        return normalized.startswith(("gpt-", "o3-", "o1-"))

    @staticmethod
    async def _run_fallback_completion(
        client: AsyncOpenAI,
        system_prompt: str,
        user_prompt: str,
        *,
        use_json: bool,
    ) -> Any:
        kwargs: dict[str, Any] = {
            "model": settings.AGENT_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.25,
            "max_tokens": 450,
        }
        if use_json:
            kwargs["response_format"] = {"type": "json_object"}
        return await client.chat.completions.create(**kwargs)  # pyrefly: ignore[no-untyped-call]

    @staticmethod
    def _extract_choice_content(response: Any) -> str:
        choices = getattr(response, "choices", None)
        if not choices:
            return ""
        message = getattr(choices[0], "message", None)
        return getattr(message, "content", "") or ""

    @staticmethod
    def _parse_fallback_content(
        content: str,
        entry_ids: Sequence[str],
        *,
        expects_json: bool,
        client_id: int,
    ) -> tuple[str, list[str]]:
        normalized_entries = [item for item in entry_ids if item]
        if expects_json:
            try:
                payload = json.loads(content)
            except json.JSONDecodeError as exc:  # pragma: no cover - defensive guard
                logger.warning(f"agent.ask fallback invalid_json client_id={client_id} error={exc}")
                return "", []
            answer = str(payload.get("answer", "")).strip()
            sources_payload = payload.get("sources", [])
            normalized_sources: list[str] = []
            if isinstance(sources_payload, Sequence) and not isinstance(sources_payload, (str, bytes)):
                for item in sources_payload:
                    text = str(item).strip()
                    if text:
                        normalized_sources.append(text)
            if not normalized_sources:
                normalized_sources = list(normalized_entries) if normalized_entries else ["general_knowledge"]
            return answer, normalized_sources
        answer = content.strip()
        if not answer:
            return "", []
        default_sources = list(normalized_entries) if normalized_entries else ["general_knowledge"]
        return answer, default_sources
