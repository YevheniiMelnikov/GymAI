import json
import inspect
import os
from datetime import datetime
from functools import wraps
from time import perf_counter
from typing import Any, Awaitable, Callable, ClassVar, Iterable, Mapping, Optional, Sequence, TypeVar, cast

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
from ai_coach.exceptions import AgentExecutionAborted

from .base import AgentDeps
from .prompts import (
    COACH_SYSTEM_PROMPT,
    UPDATE_WORKOUT,
    GENERATE_WORKOUT,
    COACH_INSTRUCTIONS,
    ASK_AI_USER_PROMPT,
    agent_instructions,
)

from .tools import toolset
from ..schemas import ProgramPayload
from pydantic_ai import Agent, RunContext  # pyrefly: ignore[import-error]
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart  # pyrefly: ignore[import-error]
from pydantic_ai.models.openai import OpenAIChatModel  # pyrefly: ignore[import-error]
from ai_coach.types import CoachMode, MessageRole
from ai_coach.agent.knowledge.knowledge_base import KnowledgeBase, KnowledgeSnippet
from ai_coach.agent.knowledge.context import current_kb, get_or_create_kb
from ai_coach.agent.utils import resolve_language_name


def _kb() -> KnowledgeBase:
    existing = current_kb()
    if existing is not None:
        return existing
    return get_or_create_kb()


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
    _completion_client: ClassVar[AsyncOpenAI | None] = None
    _completion_model_name: ClassVar[str | None] = None

    _LANGUAGE_CODE_ALIASES: ClassVar[dict[str, str]] = {
        "ua": "uk",
        "ua-ua": "uk",
        "uk-ua": "uk",
        "ukrainian": "uk",
        "eng": "en",
        "en-us": "en",
        "english": "en",
        "ru-ru": "ru",
        "rus": "ru",
        "russian": "ru",
    }  # TODO: REMOVE

    @classmethod
    def _language_context(cls, deps: AgentDeps) -> tuple[str, str]:
        default_lang: str = getattr(settings, "DEFAULT_LANG", "en") or "en"
        raw_locale = (deps.locale or default_lang).strip()
        if not raw_locale:
            raw_locale = default_lang
        normalized = raw_locale.replace("_", "-").lower()
        code = cls._LANGUAGE_CODE_ALIASES.get(normalized)
        if code is None and "-" in normalized:
            primary = normalized.split("-", 1)[0]
            code = cls._LANGUAGE_CODE_ALIASES.get(primary, primary)
        if code is None:
            code = cls._LANGUAGE_CODE_ALIASES.get(normalized, normalized)
        if not code:
            code = default_lang.lower()
        if len(code) != 2 or not code.isalpha():
            fallback = cls._LANGUAGE_CODE_ALIASES.get(default_lang.lower(), default_lang.lower())
            code = fallback if len(fallback) == 2 and fallback.isalpha() else "en"
        code = code.lower()
        descriptor = resolve_language_name(code)
        display = f"{descriptor} ({code})" if descriptor != code else code
        return code, display

    @classmethod
    def _lang(cls, deps: AgentDeps) -> str:
        code, _ = cls._language_context(deps)
        return code

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
        cls._ensure_llm_logging(cls._agent)

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
        kb = _kb()
        raw = await kb.get_message_history(client_id)
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
        client, model_name = cls._get_completion_client()
        cls._ensure_llm_logging(client, model_name)
        deps.mode = CoachMode.ask_ai
        _, language_label = cls._language_context(deps)
        history = await cls._message_history(deps.client_id)
        kb = _kb()
        prefetched_knowledge: list[KnowledgeSnippet] = []
        try:
            entry_ids, entries, entry_datasets, prefetched_knowledge = await cls._collect_kb_entries(
                kb,
                deps.client_id,
                prompt,
                request_id=deps.request_rid,
                limit=6,
            )
        except Exception as exc:  # noqa: BLE001 - prefetch should not block main flow
            logger.warning(f"agent.ask knowledge_prefetch_failed client_id={deps.client_id} error={exc}")
            entry_ids, entries, entry_datasets = [], [], []
        source_aliases = cls._unique_sources(entry_datasets) if entry_ids else []
        kb_used = bool(entry_ids)
        deps.knowledge_base_empty = not kb_used
        deps.kb_used = kb_used
        if kb_used:
            logger.debug(
                "agent.ask knowledge_ready client_id={} entries={} sources={}".format(
                    deps.client_id,
                    len(entry_ids),
                    ",".join(source_aliases),
                )
            )
        else:
            logger.debug(f"agent.ask knowledge_empty client_id={deps.client_id}")

        knowledge_section = cls._format_knowledge_entries(entry_ids, entries) if kb_used else ""
        system_prompt = COACH_SYSTEM_PROMPT
        user_prompt = ASK_AI_USER_PROMPT.format(
            language=language_label,
            question=prompt,
            knowledge=knowledge_section,
        )

        async def _general_answer() -> QAResponse:
            plain_prompt = ASK_AI_USER_PROMPT.format(
                language=language_label,
                question=prompt,
                knowledge="",
            )
            plain = await cls._complete_with_retries(
                client,
                system_prompt,
                plain_prompt,
                [],
                client_id=deps.client_id,
                max_tokens=settings.AI_COACH_FIRST_PASS_MAX_TOKENS,
                model=model_name,
            )
            if plain is None:
                direct_prompt = (
                    f"Client language: {language_label}\n"
                    f"Client question: {prompt}\n"
                    "Respond with practical fitness advice."
                )
                plain = await cls._complete_with_retries(
                    client,
                    system_prompt,
                    direct_prompt,
                    [],
                    client_id=deps.client_id,
                    max_tokens=settings.AI_COACH_FIRST_PASS_MAX_TOKENS,
                    model=model_name,
                )
            if plain is None:
                logger.warning(
                    "agent.ask general_fallback_failed client_id={} reason=llm_unavailable".format(deps.client_id)
                )
                raise AgentExecutionAborted("ask_ai_unavailable", reason="ask_ai_unavailable")
            try:
                normalized = cls._enforce_fitness_domain(
                    prompt,
                    plain,
                    language_label,
                    [],
                    [],
                    [],
                    deps.client_id,
                    deps=deps,
                )
            except AgentExecutionAborted:
                logger.warning(
                    "agent.ask general_fallback_failed client_id={} reason=empty_llm_response".format(deps.client_id)
                )
                raise AgentExecutionAborted("ask_ai_unavailable", reason="ask_ai_unavailable")
            normalized.sources = ["general_knowledge"]
            return normalized

        try:
            primary = await cls._complete_with_retries(
                client,
                system_prompt,
                user_prompt,
                entry_ids,
                client_id=deps.client_id,
                max_tokens=settings.AI_COACH_FIRST_PASS_MAX_TOKENS,
                model=model_name,
            )
        except AgentExecutionAborted as exc:
            logger.info(f"agent.ask completion_aborted client_id={deps.client_id} reason={exc.reason}")
            if exc.reason == "knowledge_base_empty":
                deps.knowledge_base_empty = True
            fallback = await cls._fallback_answer_question(
                prompt,
                deps,
                history,
                prefetched_knowledge=prefetched_knowledge,
            )
            if fallback is not None:
                if not fallback.sources:
                    fallback.sources = source_aliases if kb_used else ["general_knowledge"]
                return fallback
            if entry_ids:
                snippets_for_summary = (
                    prefetched_knowledge
                    if prefetched_knowledge is not None and len(prefetched_knowledge) >= len(entry_ids)
                    else None
                )
                summary = cls._kb_summary_from_entries(
                    prompt,
                    entry_ids,
                    entries,
                    datasets=entry_datasets,
                    snippets=snippets_for_summary,
                    client_id=deps.client_id,
                    language=language_label,
                )
                return cls._enforce_fitness_domain(
                    prompt,
                    summary,
                    language_label,
                    entry_ids,
                    entries,
                    entry_datasets,
                    deps.client_id,
                    deps=deps,
                )
            return await _general_answer()

        if primary is not None:
            primary = cls._enforce_fitness_domain(
                prompt,
                primary,
                language_label,
                entry_ids,
                entries,
                entry_datasets,
                deps.client_id,
                deps=deps,
            )
            primary.sources = source_aliases if kb_used else ["general_knowledge"]
            logger.info(
                "agent.ask.done client_id={} answer_len={} sources={} kb_used={}".format(
                    deps.client_id,
                    len(primary.answer),
                    ",".join(primary.sources),
                    kb_used,
                )
            )
            return primary

        fallback = await cls._fallback_answer_question(
            prompt,
            deps,
            history,
            prefetched_knowledge=prefetched_knowledge,
        )
        if fallback is not None:
            return fallback
        if entry_ids:
            snippets_for_summary = (
                prefetched_knowledge
                if prefetched_knowledge is not None and len(prefetched_knowledge) >= len(entry_ids)
                else None
            )
            summary = cls._kb_summary_from_entries(
                prompt,
                entry_ids,
                entries,
                datasets=entry_datasets,
                snippets=snippets_for_summary,
                client_id=deps.client_id,
                language=language_label,
            )
        return cls._enforce_fitness_domain(
            prompt,
            summary,
            language_label,
            entry_ids,
            entries,
            entry_datasets,
            deps.client_id,
            deps=deps,
        )
        return await _general_answer()

    @classmethod
    async def _fallback_answer_question(
        cls,
        prompt: str,
        deps: AgentDeps,
        history: list[ModelMessage],
        *,
        prefetched_knowledge: Sequence[KnowledgeSnippet] | None = None,
    ) -> QAResponse | None:
        if deps.fallback_used:
            logger.debug(f"agent.ask fallback skipped client_id={deps.client_id} reason=already_used")
            return None
        deps.fallback_used = True
        logger.warning(
            f"agent.ask fallback_invoked client_id={deps.client_id} reason=model_empty_response history={len(history)}"
        )
        client, model_name = cls._get_completion_client()
        cls._ensure_llm_logging(client, model_name)
        knowledge: Sequence[KnowledgeSnippet]
        kb = _kb()
        if prefetched_knowledge is not None:
            knowledge = prefetched_knowledge
        else:
            try:
                knowledge = await kb.search(
                    prompt,
                    deps.client_id,
                    6,
                    request_id=deps.request_rid,
                )
            except Exception as exc:  # noqa: BLE001 - log and continue with empty knowledge
                logger.warning(f"agent.ask fallback knowledge_failed client_id={deps.client_id} error={exc}")
                knowledge = []
        entry_ids, entries, entry_datasets = cls._build_knowledge_entries(knowledge)
        entry_ids, entries, entry_datasets = cls._filter_entries_for_prompt(prompt, entry_ids, entries, entry_datasets)
        entry_datasets = [
            kb.dataset_service.alias_for_dataset(dataset) if dataset else "" for dataset in entry_datasets
        ]
        deps.knowledge_base_empty = len(entry_ids) == 0
        deps.kb_used = not deps.knowledge_base_empty
        _, language_label = cls._language_context(deps)
        knowledge_section = cls._format_knowledge_entries(entry_ids, entries)
        system_prompt = COACH_SYSTEM_PROMPT
        user_prompt = ASK_AI_USER_PROMPT.format(
            language=language_label,
            question=prompt,
            knowledge=knowledge_section,
        )
        response = await cls._complete_with_retries(
            client,
            system_prompt,
            user_prompt,
            entry_ids,
            client_id=deps.client_id,
            max_tokens=settings.AI_COACH_FIRST_PASS_MAX_TOKENS,
            model=model_name,
        )
        if response is not None:
            result = cls._enforce_fitness_domain(
                prompt,
                response,
                language_label,
                entry_ids,
                entries,
                entry_datasets,
                deps.client_id,
                deps=deps,
            )
            result.sources = cls._unique_sources(entry_datasets)
            logger.info(
                (
                    f"agent.ask fallback_success client_id={deps.client_id} answer_len={len(result.answer)} "
                    f"sources={','.join(result.sources)} kb_empty={deps.knowledge_base_empty}"
                )
            )
            return result
        if entry_ids:
            snippets_for_summary = knowledge if knowledge is not None and len(knowledge) >= len(entry_ids) else None
            summary = cls._kb_summary_from_entries(
                prompt,
                entry_ids,
                entries,
                datasets=entry_datasets,
                snippets=snippets_for_summary,
                client_id=deps.client_id,
                language=language_label,
            )
            result = cls._enforce_fitness_domain(
                prompt,
                summary,
                language_label,
                entry_ids,
                entries,
                entry_datasets,
                deps.client_id,
                deps=deps,
            )
            result.sources = cls._unique_sources(entry_datasets)
            return result
        deps.knowledge_base_empty = True
        logger.warning(f"agent.ask fallback missing_answer client_id={deps.client_id} kb_empty=True")
        return None

    @staticmethod
    def _build_knowledge_entries(
        raw_entries: Sequence[KnowledgeSnippet | str],
        *,
        default_dataset: str | None = None,
    ) -> tuple[list[str], list[str], list[str]]:
        entry_ids: list[str] = []
        entries: list[str] = []
        datasets: list[str] = []
        for index, raw in enumerate(raw_entries, start=1):
            if isinstance(raw, KnowledgeSnippet):
                if not raw.is_content():
                    continue
                text = raw.text.strip()
                dataset = (raw.dataset or "").strip() if raw.dataset else ""
            else:
                text = str(raw or "").strip()
                dataset = default_dataset or ""
            if not text:
                continue
            entry_id = f"KB-{index}"
            entry_ids.append(entry_id)
            entries.append(text)
            datasets.append(dataset)
        return entry_ids, entries, datasets

    @staticmethod
    def _unique_sources(datasets: Iterable[str]) -> list[str]:
        unique: list[str] = []
        seen: set[str] = set()
        for raw in datasets:
            alias = (raw or "").strip()
            if not alias or alias in seen:
                continue
            seen.add(alias)
            unique.append(alias)

        def _order(value: str) -> tuple[int, str]:
            if value.startswith("kb_client_"):
                return (0, value)
            if value.startswith("kb_chat_"):
                return (1, value)
            if value == settings.COGNEE_GLOBAL_DATASET:
                return (2, value)
            return (3, value)

        unique.sort(key=_order)
        return unique

    @classmethod
    async def _collect_kb_entries(
        cls,
        kb: KnowledgeBase,
        client_id: int,
        query: str,
        *,
        request_id: str | None,
        limit: int = 6,
    ) -> tuple[list[str], list[str], list[str], list[KnowledgeSnippet]]:
        actor = await kb.dataset_service.get_cognee_user()
        candidate_datasets = [
            kb.dataset_service.dataset_name(client_id),
            kb.dataset_service.chat_dataset_name(client_id),
            kb.GLOBAL_DATASET,
        ]
        unique_datasets: list[str] = []
        seen: set[str] = set()
        for dataset in candidate_datasets:
            alias = kb.dataset_service.alias_for_dataset(dataset)
            if alias in seen:
                continue
            seen.add(alias)
            unique_datasets.append(alias)
        for dataset in unique_datasets:
            try:
                await kb.projection_service.ensure_dataset_projected(dataset, actor, timeout_s=2.0)
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"knowledge_projection_skip dataset={dataset} detail={exc}")

        snippets = await kb.search(query, client_id, limit, request_id=request_id)
        entry_ids, entries, datasets = cls._build_knowledge_entries(snippets)
        entry_ids, entries, datasets = cls._filter_entries_for_prompt(query, entry_ids, entries, datasets)
        dataset_aliases = [kb.dataset_service.alias_for_dataset(dataset) if dataset else "" for dataset in datasets]
        if entry_ids:
            return entry_ids, entries, dataset_aliases, list(snippets)
        try:
            fallback_raw = await kb.fallback_entries(client_id, limit=limit)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"agent.ask fallback_entries_failed client_id={client_id} detail={exc}")
            fallback_raw = []
        fallback_snippets = [
            KnowledgeSnippet(text=text, dataset=dataset, kind="document") for text, dataset in fallback_raw
        ]
        fallback_ids, fallback_entries, fallback_datasets = cls._build_knowledge_entries(fallback_snippets)
        fallback_ids, fallback_entries, fallback_datasets = cls._filter_entries_for_prompt(
            query, fallback_ids, fallback_entries, fallback_datasets
        )
        alias_fallbacks = [
            kb.dataset_service.alias_for_dataset(dataset) if dataset else "" for dataset in fallback_datasets
        ]
        return fallback_ids, fallback_entries, alias_fallbacks, list(snippets)

    @staticmethod
    def _filter_entries_for_prompt(
        prompt: str,
        entry_ids: Sequence[str],
        entries: Sequence[str],
        datasets: Sequence[str],
    ) -> tuple[list[str], list[str], list[str]]:
        if not entry_ids or not entries:
            return list(entry_ids), list(entries), list(datasets)
        return list(entry_ids), list(entries), list(datasets)

    @classmethod
    def _format_knowledge_entries(cls, entry_ids: Sequence[str], entries: Sequence[str]) -> str:
        if not entry_ids or not entries:
            return ""
        formatted: list[str] = []
        for entry_id, text in zip(entry_ids, entries, strict=False):
            snippet = cls._truncate_text(text, 500)
            formatted.append(f"{entry_id}: {snippet}")
        return "\n\n".join(formatted)

    @classmethod
    async def _complete_with_retries(
        cls,
        client: AsyncOpenAI,
        system_prompt: str,
        user_prompt: str,
        entry_ids: Sequence[str],
        *,
        client_id: int,
        max_tokens: int,
        model: str | None = None,
        continuation_attempt: int = 0,
        continuation_context: str | None = None,
    ) -> QAResponse | None:
        max_attempts = 2 if settings.AI_COACH_EMPTY_COMPLETION_RETRY else 1
        model_id = model or settings.AGENT_MODEL
        full_content = ""
        final_finish_reason = "unknown"

        for attempt in range(max_attempts):
            if attempt > 0:
                logger.info(
                    ("llm.retry client_id={} model={} max_tokens={} attempt={} json_modes=0").format(
                        client_id, model_id, attempt, 0
                    )
                )
            current_user_prompt = user_prompt
            if continuation_attempt > 0:
                previous = continuation_context if continuation_context is not None else full_content
                if previous:
                    snippet = cls._truncate_text(previous, 1200)
                    current_user_prompt = (
                        f"{user_prompt}\n\n"
                        "Continue the previous answer from where it stopped. "
                        "Do not repeat the text below; only add the missing continuation.\n"
                        f"Already sent to the client:\n{snippet}"
                    )

            try:
                response = await cls._run_completion(
                    client,
                    system_prompt,
                    current_user_prompt,
                    model=model_id,
                    max_tokens=max_tokens,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    ("agent.ask completion_failed client_id={} model={} attempt={} error={}").format(
                        client_id, model_id, attempt, exc
                    )
                )
                continue
            meta = cls._llm_response_metadata(response)
            content = cls._extract_choice_content(response, client_id=client_id)
            full_content += content
            final_finish_reason = meta.get("finish_reason") or "unknown"

            if final_finish_reason == "length" and continuation_attempt == 0:
                logger.info(
                    ("llm.continuation_needed client_id={} model={} max_tokens={} current_len={}").format(
                        client_id, model_id, max_tokens, len(full_content)
                    )
                )
                # Make a single continuation attempt
                continuation_response = await cls._complete_with_retries(
                    client,
                    system_prompt,
                    user_prompt,  # Pass original user_prompt for context
                    entry_ids,
                    client_id=client_id,
                    max_tokens=getattr(settings, "AI_COACH_CONTINUATION_MAX_TOKENS", 600),
                    model=model,
                    continuation_attempt=1,
                    continuation_context=full_content,
                )
                if continuation_response and continuation_response.answer:
                    full_content += continuation_response.answer
                    final_finish_reason = (
                        cls._llm_response_metadata(continuation_response).get("finish_reason") or "stop"
                    )
                break  # Break after continuation attempt
            else:
                break  # Break if not length or already a continuation

        if full_content:
            raw_text = full_content.strip()
            answer, sources = cls._parse_fallback_content(
                full_content,
                entry_ids,
                client_id=client_id,
            )
            if not answer.strip() and raw_text:
                logger.debug(
                    "llm.partial_content_used client_id={} reason={} model={} preserved_len={}".format(
                        client_id,
                        final_finish_reason,
                        model_id,
                        len(raw_text),
                    )
                )
                answer = raw_text
                sources = list(entry_ids) or ["general_knowledge"]
            if answer.strip():
                normalized_sources = list(sources) if sources else list(entry_ids) or ["general_knowledge"]
                return QAResponse(answer=answer, sources=normalized_sources)
        log_message = ("llm.response.empty client_id={} reason={} model={} final_content_len={}").format(
            client_id,
            final_finish_reason,
            model_id,
            len(full_content),
        )
        log_fn = logger.info if final_finish_reason == "length" else logger.warning
        log_fn(log_message)
        return None

    @classmethod
    def _kb_summary_from_entries(
        cls,
        prompt: str,
        entry_ids: Sequence[str],
        entries: Sequence[str],
        *,
        datasets: Sequence[str] | None,
        snippets: Sequence[KnowledgeSnippet] | None,
        client_id: int,
        language: str,
    ) -> QAResponse:
        if not entry_ids or not entries:
            raise AgentExecutionAborted("Knowledge base empty", reason="knowledge_base_empty")
        kb = _kb()
        client_dataset = kb.dataset_service.dataset_name(client_id)
        index_map = {entry_id: idx for idx, entry_id in enumerate(entry_ids)}
        annotated: list[tuple[str, str, str]] = []
        for idx, text in enumerate(entries):
            cleaned = text.strip()
            if not cleaned:
                continue
            dataset = ""
            if datasets is not None and idx < len(datasets):
                dataset = datasets[idx] or ""
            elif snippets is not None and idx < len(snippets):
                dataset = snippets[idx].dataset or ""
            source = entry_ids[idx] if idx < len(entry_ids) else f"KB-{idx + 1}"
            annotated.append((dataset, source, cleaned))
        if not annotated:
            raise AgentExecutionAborted("Knowledge base empty", reason="knowledge_base_empty")
        annotated.sort(key=lambda item: (0 if item[0] == client_dataset else 1, index_map.get(item[1], 0)))
        selected = annotated[:3]
        summary_lines: list[str] = []
        for dataset, source, text in selected:
            summary_lines.append(f"- {cls._shorten_for_summary(text)}")
        intro = "Ось що я знайшов у нотатках тренувань:"
        outro = "Якщо потрібні деталі або коригування, дай знати — я підкажу далі."
        answer = "\n".join([intro, *summary_lines, "", outro]).strip()
        logger.info("agent.ask kb_fallback_summary client_id={} used_snippets={}".format(client_id, len(selected)))
        source_aliases = cls._unique_sources(dataset or "" for dataset, _, _ in selected)
        sources = source_aliases or [source for _, source, _ in selected] or ["general_knowledge"]
        return QAResponse(answer=answer, sources=sources)

    @staticmethod
    def _shorten_for_summary(text: str, *, limit: int = 280) -> str:
        cleaned = " ".join(text.split())
        if len(cleaned) <= limit:
            return cleaned
        truncated = cleaned[: limit + 1]
        last_space = truncated.rfind(" ")
        if last_space > 0:
            truncated = truncated[:last_space]
        return f"{truncated.rstrip()}..."

    @staticmethod
    def _truncate_text(text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        truncated = text[: limit + 1]
        last_space = truncated.rfind(" ")
        if last_space > 0:
            truncated = truncated[:last_space]
        return f"{truncated.rstrip()}..."

    @classmethod
    def _collect_text_fragments(cls, value: Any) -> list[str]:
        fragments: list[str] = []
        cls._append_text_fragment(value, fragments)
        return fragments

    @classmethod
    def _append_text_fragment(cls, value: Any, fragments: list[str]) -> None:
        if value is None:
            return
        if isinstance(value, (bytes, bytearray)):
            text = value.decode("utf-8", "ignore").strip()
            if text:
                fragments.append(text)
            return
        if isinstance(value, str):
            text = value.strip()
            if text:
                fragments.append(text)
            return
        if hasattr(value, "text") and not isinstance(value, (str, bytes)):
            cls._append_text_fragment(getattr(value, "text"), fragments)
            return
        if hasattr(value, "content") and not isinstance(value, (str, bytes)):
            cls._append_text_fragment(getattr(value, "content"), fragments)
            return
        if isinstance(value, Mapping):
            for key in ("text", "content", "value", "message"):
                if key in value:
                    cls._append_text_fragment(value[key], fragments)
            return
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            for item in value:
                cls._append_text_fragment(item, fragments)
            return

    @staticmethod
    def _extract_message_content(content: Any) -> str:
        fragments = CoachAgent._collect_text_fragments(content)
        if fragments:
            return "\n".join(fragments)
        if hasattr(content, "model_dump"):
            try:
                dumped = content.model_dump()
            except Exception:  # noqa: BLE001
                dumped = None
            if dumped:
                fragments = CoachAgent._collect_text_fragments(dumped)
                if fragments:
                    return "\n".join(fragments)
        return ""

    @staticmethod
    def _model_identifier(model: Any) -> str:
        model_name = getattr(model, "model_name", None) or getattr(model, "name", None)
        if not model_name:
            return settings.AGENT_MODEL
        return str(model_name)

    @classmethod
    def _get_completion_client(cls) -> tuple[AsyncOpenAI, str]:
        if cls._completion_client is not None and cls._completion_model_name is not None:
            return cls._completion_client, cls._completion_model_name

        agent = cls._get_agent()
        model = getattr(agent, "model", None)
        client = getattr(model, "client", None)
        if isinstance(client, AsyncOpenAI):
            cls._completion_client = client
            cls._completion_model_name = cls._model_identifier(model)
            return client, cls._completion_model_name

        cls._completion_client = AsyncOpenAI(
            api_key=settings.LLM_API_KEY or None,
            base_url=settings.LLM_API_URL or None,
        )
        cls._completion_model_name = settings.AGENT_MODEL
        return cls._completion_client, cls._completion_model_name

    @classmethod
    def _ensure_llm_logging(cls, target: Any, model_id: str | None = None) -> None:
        client: AsyncOpenAI | None
        if isinstance(target, AsyncOpenAI):
            client = target
        else:
            client = getattr(target, "client", None)
        if not isinstance(client, AsyncOpenAI):
            return
        if getattr(client, "_gymbot_wrapped", False):
            return
        chat = getattr(client, "chat", None)
        completions = getattr(chat, "completions", None)
        if completions is None:
            return
        original_create = getattr(completions, "create", None)
        if not callable(original_create):
            return
        typed_create = cast(Callable[..., Awaitable[Any]], original_create)

        resolved_model = model_id or settings.AGENT_MODEL

        @wraps(typed_create)
        async def wrapped_create(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401 - external signature
            start = perf_counter()
            request_meta = cls._llm_request_metadata(kwargs)
            logger.debug(
                (
                    "llm.request model={} json_format={} stream={} messages={} system_len={} user_len={} "
                    "temperature={} max_tokens={} tool_choice={}"
                ).format(
                    resolved_model,
                    request_meta["json_format"],
                    request_meta["stream"],
                    request_meta["messages"],
                    request_meta["system_len"],
                    request_meta["user_len"],
                    request_meta["temperature"],
                    request_meta["max_tokens"],
                    request_meta["tool_choice"],
                )
            )
            try:
                response = await typed_create(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                latency = (perf_counter() - start) * 1000.0
                logger.warning(f"llm.response.error model={resolved_model} latency_ms={latency:.0f} error={exc}")
                raise
            latency = (perf_counter() - start) * 1000.0
            response_meta = cls._llm_response_metadata(response)
            logger.debug(
                (
                    "llm.response model={} choices={} finish_reason={} content_len={} "
                    "has_tool_calls={} prompt_tokens={} completion_tokens={} total_tokens={} "
                    "latency_ms={:.0f} preview={}"
                ).format(
                    resolved_model,
                    response_meta["choices"],
                    response_meta["finish_reason"],
                    response_meta["content_len"],
                    response_meta["has_tool_calls"],
                    response_meta["prompt_tokens"],
                    response_meta["completion_tokens"],
                    response_meta["total_tokens"],
                    latency,
                    response_meta["preview"],
                )
            )
            if os.getenv("LOG_LLM_RAW", "").lower() in {"1", "true", "yes"}:
                raw_snapshot, raw_keys = cls._raw_choice_snapshot(response)
                logger.debug(
                    "llm.response.raw model={} raw_first_200={} raw_keys={}".format(
                        resolved_model,
                        raw_snapshot or "",
                        raw_keys or "na",
                    )
                )
            return response

        completions.create = wrapped_create  # pyrefly: ignore[attr-defined]
        setattr(client, "_gymbot_wrapped", True)

    @staticmethod
    def _llm_request_metadata(kwargs: dict[str, Any]) -> dict[str, Any]:
        messages = kwargs.get("messages") or []
        system_len = 0
        user_len = 0
        total_messages = 0
        for message in messages:
            role = str(message.get("role", "")).lower()
            content = message.get("content", "")
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                text = "".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
            else:
                text = str(content)
            total_messages += 1
            length = len(text.strip())
            if role == "system":
                system_len += length
            elif role == "user":
                user_len += length
        temperature = kwargs.get("temperature")
        max_tokens = kwargs.get("max_tokens")
        tool_choice = kwargs.get("tool_choice")
        return {
            "json_format": "response_format" in kwargs,
            "stream": bool(kwargs.get("stream", False)),
            "messages": total_messages,
            "system_len": system_len,
            "user_len": user_len,
            "temperature": temperature if temperature is not None else "na",
            "max_tokens": max_tokens if max_tokens is not None else "na",
            "tool_choice": tool_choice if tool_choice is not None else "na",
        }

    @staticmethod
    def _llm_response_metadata(response: Any) -> dict[str, Any]:
        choices = getattr(response, "choices", None) or []
        first_choice = choices[0] if choices else None
        message = getattr(first_choice, "message", None)
        if message is None and isinstance(first_choice, Mapping):
            message = first_choice.get("message")
        if isinstance(message, Mapping):
            tool_calls = message.get("tool_calls")
        else:
            tool_calls = getattr(message, "tool_calls", None)
        usage = getattr(response, "usage", None)
        prompt_tokens = getattr(usage, "prompt_tokens", None)
        completion_tokens = getattr(usage, "completion_tokens", None)
        total_tokens = getattr(usage, "total_tokens", None)
        if isinstance(first_choice, Mapping):
            finish_reason = str(first_choice.get("finish_reason", "") or "")
        else:
            finish_reason = getattr(first_choice, "finish_reason", "") if first_choice else ""
        preview = CoachAgent._message_preview(message) if message is not None else ""
        extracted_text = CoachAgent._extract_choice_content(response, client_id=None)
        return {
            "choices": len(choices),
            "finish_reason": finish_reason or "",
            "content_len": len(extracted_text),
            "has_tool_calls": bool(tool_calls),
            "prompt_tokens": prompt_tokens if prompt_tokens is not None else "na",
            "completion_tokens": completion_tokens if completion_tokens is not None else "na",
            "total_tokens": total_tokens if total_tokens is not None else "na",
            "preview": preview,
        }

    @staticmethod
    async def _run_completion(
        client: AsyncOpenAI,
        system_prompt: str,
        user_prompt: str,
        *,
        model: str,
        max_tokens: int,
    ) -> Any:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.25,
            "max_tokens": max_tokens,
            "tool_choice": "none",
            "stream": False,
        }
        return await client.chat.completions.create(**kwargs)  # pyrefly: ignore[no-untyped-call]

    @staticmethod
    def _choice_payload(choice: Any) -> dict[str, Any]:
        if isinstance(choice, Mapping):
            return dict(choice)
        model_dump = getattr(choice, "model_dump", None)
        if callable(model_dump):
            try:
                dumped = model_dump()
            except Exception:  # noqa: BLE001 - diagnostics only
                dumped = None
            if isinstance(dumped, Mapping):
                return dict(dumped)
        model_dump_json = getattr(choice, "model_dump_json", None)
        if callable(model_dump_json):
            try:
                dumped_json = model_dump_json()
            except Exception:  # noqa: BLE001 - diagnostics only
                dumped_json = None
            if isinstance(dumped_json, str):
                try:
                    payload = json.loads(dumped_json)
                except json.JSONDecodeError:
                    payload = None
                if isinstance(payload, Mapping):
                    return dict(payload)
        return {}

    @classmethod
    def _coerce_text_candidate(cls, candidate: Any) -> str:
        if candidate is None:
            return ""
        if isinstance(candidate, str):
            return candidate.strip()
        if isinstance(candidate, Mapping):
            primary = candidate.get("content")
            text = cls._coerce_text_candidate(primary)
            if text:
                return text
            return cls._coerce_text_candidate(candidate.get("text"))
        if isinstance(candidate, Sequence) and not isinstance(candidate, (str, bytes)):
            return cls._extract_message_content(candidate)
        content_attr = getattr(candidate, "content", None)
        if content_attr is not None:
            text = cls._coerce_text_candidate(content_attr)
            if text:
                return text
        text_attr = getattr(candidate, "text", None)
        if isinstance(text_attr, str):
            return text_attr.strip()
        if text_attr is not None:
            text = cls._coerce_text_candidate(text_attr)
            if text:
                return text
        model_dump = getattr(candidate, "model_dump", None)
        if callable(model_dump):
            try:
                dumped = model_dump()
            except Exception:  # noqa: BLE001 - diagnostics only
                dumped = None
            if isinstance(dumped, Mapping):
                return cls._coerce_text_candidate(dumped.get("content") or dumped.get("text"))
        return cls._extract_message_content(candidate)

    @classmethod
    def _extract_text_from_choice(cls, payload: Mapping[str, Any]) -> str:
        if not isinstance(payload, Mapping):
            return ""
        message = payload.get("message")
        fragments = cls._collect_text_fragments(message)
        if fragments:
            return "\n".join(fragments)
        for key in ("content", "text"):
            candidate = payload.get(key)
            fragments = cls._collect_text_fragments(candidate)
            if fragments:
                return "\n".join(fragments)
        return ""

    @classmethod
    def _raw_choice_snapshot(cls, source: Any) -> tuple[str, str]:
        choice: Any = source
        if hasattr(source, "choices"):
            choices = getattr(source, "choices", None)
            if not choices:
                return "", ""
            choice = choices[0]
        payload = cls._choice_payload(choice)
        raw_keys = ",".join(sorted(payload.keys())) if payload else ""
        if payload:
            try:
                raw_repr = json.dumps(payload, ensure_ascii=False, default=str)
            except TypeError:
                raw_repr = str(payload)
        else:
            raw_repr = str(choice)
        snapshot = (raw_repr or "")[:200]
        return snapshot, raw_keys

    @classmethod
    def _extract_choice_content(cls, response: Any, *, client_id: int | None = None) -> str:
        choices = getattr(response, "choices", None)
        if not choices:
            if client_id is not None:
                logger.debug(f"llm.parse client_id={client_id} empty=True reason=no_choices")
            return ""
        first_choice = choices[0]
        raw_snapshot, raw_keys = cls._raw_choice_snapshot(first_choice)
        payload = cls._choice_payload(first_choice)
        extracted = cls._extract_text_from_choice(payload)
        message_obj: Any = (
            payload.get("message") if isinstance(payload, Mapping) else getattr(first_choice, "message", None)
        )
        tool_calls: Any | None = None
        if message_obj is None and isinstance(first_choice, Mapping):
            message_obj = first_choice.get("message")
        if message_obj is None:
            message_obj = getattr(first_choice, "message", None)
        if isinstance(message_obj, Mapping):
            tool_calls = message_obj.get("tool_calls")
        else:
            tool_calls = getattr(message_obj, "tool_calls", None)
        if extracted:
            if client_id is not None:
                logger.debug(f"llm.parse client_id={client_id} empty=False reason=message_content")
            return extracted
        if message_obj is None and isinstance(first_choice, Mapping):
            fallback_text = first_choice.get("content") or first_choice.get("text")
            if isinstance(fallback_text, str) and fallback_text.strip():
                if client_id is not None:
                    logger.debug("llm.parse client_id={} empty=False reason=choice_text".format(client_id))
                return fallback_text.strip()
        if isinstance(message_obj, Mapping):
            content = message_obj.get("content", "") or ""
        else:
            content = getattr(message_obj, "content", "") or ""
        secondary = cls._extract_message_content(content)
        if secondary:
            if client_id is not None:
                logger.debug(f"llm.parse client_id={client_id} empty=False reason=message_content")
            return secondary
        if tool_calls:
            for call in tool_calls:
                function = getattr(call, "function", None)
                arguments = getattr(function, "arguments", None)
                normalized = CoachAgent._normalize_tool_call_arguments(arguments)
                if normalized:
                    if client_id is not None:
                        logger.debug("llm.parse client_id={} empty=False reason=tool_call".format(client_id))
                    return normalized
        if raw_snapshot.strip() and client_id is not None:
            logger.debug(
                "llm.parse_mismatch client_id={} raw_first_200={} raw_keys={}".format(
                    client_id,
                    raw_snapshot,
                    raw_keys or "na",
                )
            )
        finish_reason = ""
        if choices:
            finish_reason = str(getattr(choices[0], "finish_reason", "") or "")
        if not extracted and client_id is not None and finish_reason == "length":
            logger.warning(
                "llm.parse empty_content client_id={} finish_reason=length keys={} snapshot={}".format(
                    client_id,
                    raw_keys or "na",
                    raw_snapshot,
                )
            )
        if client_id is not None:
            preview = CoachAgent._message_preview(message_obj)
            logger.debug(
                "llm.parse client_id={} empty=True reason=no_content finish_reason={} {}".format(
                    client_id,
                    finish_reason,
                    preview,
                )
            )
        return ""

    @staticmethod
    def _normalize_tool_call_arguments(arguments: Any) -> str:
        if arguments is None:
            return ""
        if isinstance(arguments, (bytes, bytearray)):
            raw_text = arguments.decode("utf-8", "ignore")
        elif isinstance(arguments, str):
            raw_text = arguments
        elif hasattr(arguments, "model_dump_json"):
            raw_text = arguments.model_dump_json()  # type: ignore[no-untyped-call]
        elif hasattr(arguments, "model_dump"):
            raw_text = json.dumps(arguments.model_dump())  # type: ignore[no-untyped-call]
        elif isinstance(arguments, dict):
            raw_text = json.dumps(arguments)
        else:
            raw_text = str(arguments)
        text = raw_text.strip()
        if not text:
            return ""
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return text
        if isinstance(payload, dict):
            answer = str(payload.get("answer", "")).strip()
            raw_sources = payload.get("sources", [])
            sources: list[str] = []
            if isinstance(raw_sources, Sequence) and not isinstance(raw_sources, (str, bytes)):
                for item in raw_sources:
                    text_item = str(item).strip()
                    if text_item:
                        sources.append(text_item)
            sanitized = {"answer": answer, "sources": sources}
            return json.dumps(sanitized)
        return text

    @staticmethod
    def _message_preview(message: Any) -> str:
        if message is None:
            return "message=None"
        content = getattr(message, "content", None)
        preview_text = ""
        if isinstance(content, str):
            preview_text = content.strip()
        elif isinstance(content, Sequence) and not isinstance(content, (str, bytes)):
            parts = [str(item) for item in content if item]
            preview_text = " ".join(parts).strip()
        elif content:
            preview_text = str(content).strip()
        preview_text = preview_text.replace("\n", " ")
        if len(preview_text) > 120:
            preview_text = f"{preview_text[:117]}..."
        tool_calls = getattr(message, "tool_calls", None)
        tool_summary = "tool_calls=0"
        if isinstance(tool_calls, Sequence) and not isinstance(tool_calls, (str, bytes)):
            names: list[str] = []
            for call in tool_calls:
                function = getattr(call, "function", None)
                name = getattr(function, "name", None)
                if name:
                    names.append(str(name))
            joined = ", ".join(names[:3])
            tool_summary = f"tool_calls={len(tool_calls)}[{joined}]" if joined else f"tool_calls={len(tool_calls)}"
        elif tool_calls:
            tool_summary = "tool_calls=1"
        preview_part = f"content_preview={preview_text!r}" if preview_text else "content_preview=''"
        return f"{preview_part} {tool_summary}"

    @staticmethod
    def _parse_fallback_content(
        content: str,
        entry_ids: Sequence[str],
        *,
        client_id: int,
    ) -> tuple[str, list[str]]:
        normalized_entries = [item for item in entry_ids if item]
        default_sources = list(normalized_entries) if normalized_entries else ["general_knowledge"]
        text = content.strip()
        if not text:
            return "", []
        should_parse_json = text.lstrip().startswith("{")
        if should_parse_json:
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:  # pragma: no cover - defensive guard
                logger.warning(f"agent.ask fallback invalid_json client_id={client_id} error={exc}")
                should_parse_json = False
            else:
                answer = str(payload.get("answer", "")).strip()
                sources_payload = payload.get("sources", [])
                normalized_sources: list[str] = []
                if isinstance(sources_payload, Sequence) and not isinstance(sources_payload, (str, bytes)):
                    for item in sources_payload:
                        text_item = str(item).strip()
                        if text_item:
                            normalized_sources.append(text_item)
                if normalized_sources:
                    valid = {entry for entry in normalized_entries}
                    normalized_sources = [item for item in normalized_sources if item in valid]
                else:
                    normalized_sources = list(normalized_entries)
                candidate_sources = normalized_sources or default_sources
                if answer:
                    return answer, candidate_sources
                fallback_keys = ("response", "result", "text", "content", "message")
                for key in fallback_keys:
                    candidate = payload.get(key)
                    candidate_text = str(candidate).strip() if isinstance(candidate, str) else ""
                    if candidate_text:
                        logger.debug(
                            "agent.ask fallback_json_field client_id={} field={} len={}".format(
                                client_id,
                                key,
                                len(candidate_text),
                            )
                        )
                        return candidate_text, candidate_sources
        return text, default_sources

    @classmethod
    def _enforce_fitness_domain(
        cls,
        prompt: str,
        response: QAResponse,
        language: str,
        entry_ids: Sequence[str],
        entries: Sequence[str],
        datasets: Sequence[str] | None,
        client_id: int,
        deps: AgentDeps | None = None,
    ) -> QAResponse:
        answer = response.answer.strip()
        if not answer:
            if entry_ids and entries:
                if deps is not None:
                    deps.fallback_used = True
                summary = cls._kb_summary_from_entries(
                    prompt,
                    entry_ids,
                    entries,
                    datasets=datasets,
                    snippets=None,
                    client_id=client_id,
                    language=language,
                )
                return summary
            raise AgentExecutionAborted("Model returned empty response", reason="model_empty_response")
        response.answer = answer
        dataset_sources = cls._unique_sources(datasets or [])
        if dataset_sources:
            response.sources = dataset_sources
        else:
            valid_sources = set(entry_ids)
            if response.sources:
                filtered = [source for source in response.sources if source in valid_sources]
                if not filtered and entry_ids:
                    filtered = list(entry_ids)
                response.sources = filtered or ["general_knowledge"]
            else:
                response.sources = list(entry_ids) if entry_ids else ["general_knowledge"]
        return response

    @classmethod
    async def llm_probe(cls) -> dict[str, Any]:
        agent = cls._get_agent()
        cls._ensure_llm_logging(agent)
        model = getattr(agent, "model", None)
        if model is None:
            raise RuntimeError("LLM model is not configured")
        client: AsyncOpenAI | None = getattr(model, "client", None)
        if client is None:
            raise RuntimeError("LLM client is not configured")
        start = perf_counter()
        try:
            response = await client.chat.completions.create(  # pyrefly: ignore[no-untyped-call]
                model=settings.AGENT_MODEL,
                messages=[
                    {"role": "system", "content": "You are a diagnostics probe."},
                    {"role": "user", "content": "Say: OK"},
                ],
                temperature=0.0,
                max_tokens=32,
                tool_choice="none",
            )
        except Exception as exc:  # noqa: BLE001
            latency = (perf_counter() - start) * 1000.0
            logger.warning(
                f"llm.probe_failed model={cls._model_identifier(model)} latency_ms={latency:.0f} error={exc}"
            )
            raise
        latency = (perf_counter() - start) * 1000.0
        choices = getattr(response, "choices", None) or []
        first_choice = choices[0] if choices else None
        message = getattr(first_choice, "message", None)
        content = getattr(message, "content", "") or ""
        tool_calls = getattr(message, "tool_calls", None)
        finish_reason = getattr(first_choice, "finish_reason", None) if first_choice else None
        usage = getattr(response, "usage", None)
        prompt_tokens = getattr(usage, "prompt_tokens", None)
        completion_tokens = getattr(usage, "completion_tokens", None)
        total_tokens = getattr(usage, "total_tokens", None)
        logger.debug(
            ("llm.probe model={} content_len={} has_tool_calls={} finish_reason={} latency_ms={:.0f}").format(
                cls._model_identifier(model),
                len(str(content).strip()),
                bool(tool_calls),
                finish_reason or "",
                latency,
            )
        )
        return {
            "model": cls._model_identifier(model),
            "content_length": len(str(content).strip()),
            "has_tool_calls": bool(tool_calls),
            "finish_reason": finish_reason,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "latency_ms": round(latency, 2),
        }
