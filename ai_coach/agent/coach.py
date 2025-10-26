import json
import inspect
from datetime import datetime
from functools import wraps
from time import perf_counter
from typing import Any, Awaitable, Callable, ClassVar, Mapping, Optional, Sequence, TypeVar, cast

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
    agent_instructions,
)

from .tools import toolset
from ..schemas import ProgramPayload
from pydantic_ai import Agent, RunContext  # pyrefly: ignore[import-error]
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart  # pyrefly: ignore[import-error]
from pydantic_ai.models.openai import OpenAIChatModel  # pyrefly: ignore[import-error]
from ai_coach.types import CoachMode, MessageRole
from ai_coach.agent.knowledge.knowledge_base import KnowledgeBase, KnowledgeSnippet
from ai_coach.language import resolve_language_name


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
    }

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
        client, model_name = cls._get_completion_client()
        cls._ensure_llm_logging(client, model_name)
        deps.mode = CoachMode.ask_ai
        _, language = cls._language_context(deps)
        history = cls._message_history(deps.client_id)
        if inspect.isawaitable(history):
            history = await history
        prefetched_knowledge: Sequence[KnowledgeSnippet]
        try:
            prefetched_knowledge = await KnowledgeBase.search(prompt, deps.client_id, 6)
        except Exception as exc:  # noqa: BLE001 - prefetch should not block main flow
            prefetched_knowledge = []
            logger.warning(f"agent.ask knowledge_prefetch_failed client_id={deps.client_id} error={exc}")
        entry_ids, entries = cls._build_knowledge_entries(prefetched_knowledge)
        entry_ids, entries = cls._filter_entries_for_prompt(prompt, entry_ids, entries)
        if not entry_ids:
            try:
                raw_entries = await KnowledgeBase.fallback_entries(deps.client_id, limit=6)
            except Exception as exc:  # noqa: BLE001 - last resort
                raw_entries = []
                logger.debug(f"agent.ask fallback_entries_failed client_id={deps.client_id} detail={exc}")
            extra_ids, extra_entries = cls._build_knowledge_entries(raw_entries)
            extra_ids, extra_entries = cls._filter_entries_for_prompt(prompt, extra_ids, extra_entries)
            if extra_ids:
                entry_ids, entries = extra_ids, extra_entries
        deps.knowledge_base_empty = len(entry_ids) == 0
        logger.debug(
            (
                f"agent.ask knowledge_ready client_id={deps.client_id} entries={len(entry_ids)} "
                f"kb_used={not deps.knowledge_base_empty}"
            )
        )

        supports_json = cls._supports_json_object(model_name)

        knowledge_section = cls._format_knowledge_entries(entry_ids, entries)
        system_prompt = (
            "You are GymBot's fitness coach.\n"
            "- Keep guidance evidence-based and actionable.\n"
            "- Treat ambiguous terms (e.g. 'сушка') as fitness context unless explicitly about towels or beauty.\n"
            "- Answer in the client's language and stay concise.\n"
            "- Mention which knowledge snippets you used; fall back to ['general_knowledge'] when none apply."
        )
        user_prompt = (
            f"Client language: {language}\n"
            f"Client question: {prompt}\n"
            "Knowledge entries (client and global):\n"
            f"{knowledge_section}\n"
            "Respond with practical fitness advice and cite the snippet IDs you relied on."
        )

        try:
            primary = await cls._complete_with_retries(
                client,
                system_prompt,
                user_prompt,
                entry_ids,
                supports_json=supports_json,
                client_id=deps.client_id,
                max_tokens=settings.AI_COACH_FIRST_PASS_MAX_TOKENS,
            )
        except AgentExecutionAborted as exc:
            logger.info(f"agent.ask completion_aborted client_id={deps.client_id} reason={exc.reason}")
            deps.knowledge_base_empty = deps.knowledge_base_empty or (exc.reason == "knowledge_base_empty")
            fallback = await cls._fallback_answer_question(
                prompt,
                deps,
                history,
                prefetched_knowledge=prefetched_knowledge,
            )
            if fallback is not None:
                return fallback
            if not entry_ids:
                try:
                    raw_entries = await KnowledgeBase.fallback_entries(deps.client_id, limit=6)
                except Exception as extra_exc:  # noqa: BLE001 - enrichment best effort
                    logger.debug(
                        f"agent.ask fallback_entries_retry_failed client_id={deps.client_id} detail={extra_exc}"
                    )
                else:
                    extra_ids, extra_entries = cls._build_knowledge_entries(raw_entries)
                    if extra_ids:
                        entry_ids, entries = extra_ids, extra_entries
                        deps.knowledge_base_empty = False
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
                    snippets=snippets_for_summary,
                    client_id=deps.client_id,
                    language=language,
                )
                return cls._enforce_fitness_domain(
                    prompt,
                    summary,
                    language,
                    entry_ids,
                    entries,
                    deps.client_id,
                    deps=deps,
                )
            raise AgentExecutionAborted("Knowledge base empty", reason="knowledge_base_empty")

        if primary is not None:
            primary = cls._enforce_fitness_domain(
                prompt,
                primary,
                language,
                entry_ids,
                entries,
                deps.client_id,
                deps=deps,
            )
            logger.info(
                "agent.ask completed client_id={} answer_len={} sources={}".format(
                    deps.client_id,
                    len(primary.answer),
                    len(primary.sources),
                )
            )
            if not entry_ids:
                primary.sources = ["general_knowledge"]
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
                snippets=snippets_for_summary,
                client_id=deps.client_id,
                language=language,
            )
            return cls._enforce_fitness_domain(
                prompt,
                summary,
                language,
                entry_ids,
                entries,
                deps.client_id,
                deps=deps,
            )
        raise AgentExecutionAborted("Knowledge base empty", reason="knowledge_base_empty")

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
        if prefetched_knowledge is not None:
            knowledge = prefetched_knowledge
        else:
            try:
                knowledge = await KnowledgeBase.search(prompt, deps.client_id, 6)
            except Exception as exc:  # noqa: BLE001 - log and continue with empty knowledge
                logger.warning(f"agent.ask fallback knowledge_failed client_id={deps.client_id} error={exc}")
                knowledge = []
        entry_ids, entries = cls._build_knowledge_entries(knowledge)
        entry_ids, entries = cls._filter_entries_for_prompt(prompt, entry_ids, entries)
        deps.knowledge_base_empty = len(entry_ids) == 0
        _, language = cls._language_context(deps)
        knowledge_section = cls._format_knowledge_entries(entry_ids, entries)
        system_prompt = (
            "You are GymBot's fitness coach.\n"
            "- Use the provided knowledge snippets first.\n"
            "- Keep the answer short, motivating, and in the client's language.\n"
            "- List the snippet IDs you used or ['general_knowledge'] when none are relevant."
        )
        user_prompt = (
            f"Client language: {language}\n"
            f"Client question: {prompt}\n"
            "Knowledge entries:\n"
            f"{knowledge_section}\n"
            "Return an actionable answer and cite the snippet IDs you relied on."
        )
        supports_json = cls._supports_json_object(model_name)
        response = await cls._complete_with_retries(
            client,
            system_prompt,
            user_prompt,
            entry_ids,
            supports_json=supports_json,
            client_id=deps.client_id,
            max_tokens=settings.AI_COACH_FIRST_PASS_MAX_TOKENS,
        )
        if response is not None:
            result = cls._enforce_fitness_domain(
                prompt,
                response,
                language,
                entry_ids,
                entries,
                deps.client_id,
                deps=deps,
            )
            logger.info(
                (
                    f"agent.ask fallback_success client_id={deps.client_id} answer_len={len(result.answer)} "
                    f"sources={len(result.sources)} kb_empty={not entry_ids}"
                )
            )
            return result
        if entry_ids:
            snippets_for_summary = knowledge if knowledge is not None and len(knowledge) >= len(entry_ids) else None
            summary = cls._kb_summary_from_entries(
                prompt,
                entry_ids,
                entries,
                snippets=snippets_for_summary,
                client_id=deps.client_id,
                language=language,
            )
            result = cls._enforce_fitness_domain(
                prompt,
                summary,
                language,
                entry_ids,
                entries,
                deps.client_id,
                deps=deps,
            )
            return result
        deps.knowledge_base_empty = True
        logger.warning(f"agent.ask fallback missing_answer client_id={deps.client_id} kb_empty=True")
        return None

    @staticmethod
    def _build_knowledge_entries(
        raw_entries: Sequence[KnowledgeSnippet | str],
    ) -> tuple[list[str], list[str]]:
        entry_ids: list[str] = []
        entries: list[str] = []
        for index, raw in enumerate(raw_entries, start=1):
            if isinstance(raw, KnowledgeSnippet):
                if not raw.is_content():
                    continue
                text = raw.text.strip()
            else:
                text = str(raw or "").strip()
            if not text:
                continue
            entry_id = f"KB-{index}"
            entry_ids.append(entry_id)
            entries.append(text)
        return entry_ids, entries

    @staticmethod
    def _filter_entries_for_prompt(
        prompt: str,
        entry_ids: Sequence[str],
        entries: Sequence[str],
    ) -> tuple[list[str], list[str]]:
        if not entry_ids or not entries:
            return list(entry_ids), list(entries)
        return list(entry_ids), list(entries)

    @classmethod
    def _format_knowledge_entries(cls, entry_ids: Sequence[str], entries: Sequence[str]) -> str:
        if not entry_ids or not entries:
            return "No knowledge entries were retrieved."
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
        supports_json: bool,
        client_id: int,
        max_tokens: int,
    ) -> QAResponse | None:
        plans = cls._build_completion_plans(supports_json, max_tokens)
        base_prompt = user_prompt
        for plan_index, plan in enumerate(plans):
            pruned_prompt, pruned_chars = cls._prune_prompt(
                base_prompt,
                plan["context_limit"],
                force_trim=plan_index > 0,
            )
            if plan_index > 0:
                logger.info(
                    ("llm.retry client_id={} model={} max_tokens={} pruned_ctx={} json_modes={}").format(
                        client_id,
                        plan["model"],
                        plan["max_tokens"],
                        pruned_chars,
                        len(plan["json_sequence"]),
                    )
                )
            for mode_index, use_json in enumerate(plan["json_sequence"]):
                try:
                    response = await cls._run_completion(
                        client,
                        system_prompt,
                        pruned_prompt,
                        use_json=use_json,
                        model=plan["model"],
                        max_tokens=plan["max_tokens"],
                    )
                except Exception as exc:  # noqa: BLE001
                    mode = "json" if use_json else "text"
                    logger.warning(
                        (
                            "agent.ask completion_failed client_id={} model={} mode={} plan_index={} mode_index={} "
                            "error={}"
                        ).format(client_id, plan["model"], mode, plan_index, mode_index, exc)
                    )
                    continue
                meta = cls._llm_response_metadata(response)
                content = cls._extract_choice_content(response, client_id=client_id)
                if not content:
                    reason = meta.get("finish_reason") or "unknown"
                    logger.warning(
                        ("llm.response.empty client_id={} reason={} model={} plan_index={} mode_index={}").format(
                            client_id, reason, plan["model"], plan_index, mode_index
                        )
                    )
                    continue
                if (meta.get("finish_reason") or "").lower() == "length" and not content.strip():
                    logger.warning(
                        (
                            "llm.response.empty client_id={} reason=finish_length model={} plan_index={} mode_index={}"
                        ).format(client_id, plan["model"], plan_index, mode_index)
                    )
                    continue
                answer, sources = cls._parse_fallback_content(
                    content,
                    list(entry_ids),
                    expects_json=use_json,
                    client_id=client_id,
                )
                if not answer:
                    continue
                if not sources:
                    sources = list(entry_ids) or ["general_knowledge"]
                return QAResponse(answer=answer, sources=sources)
        return None

    @classmethod
    def _build_completion_plans(cls, supports_json: bool, max_tokens: int) -> list[dict[str, Any]]:
        json_sequence = [True, False] if supports_json else [False]
        first_max = min(max_tokens, settings.AI_COACH_FIRST_PASS_MAX_TOKENS)
        plans: list[dict[str, Any]] = [
            {
                "model": settings.AGENT_MODEL,
                "max_tokens": first_max,
                "context_limit": settings.AI_COACH_PRIMARY_CONTEXT_LIMIT,
                "json_sequence": json_sequence,
            }
        ]
        if settings.AI_COACH_EMPTY_COMPLETION_RETRY:
            retry_model = settings.AI_COACH_SECONDARY_MODEL or settings.AGENT_MODEL
            retry_sequence = [False] if supports_json else [False]
            plans.append(
                {
                    "model": retry_model,
                    "max_tokens": settings.AI_COACH_RETRY_MAX_TOKENS,
                    "context_limit": settings.AI_COACH_RETRY_CONTEXT_LIMIT,
                    "json_sequence": retry_sequence or [False],
                }
            )
        return plans

    @staticmethod
    def _prune_prompt(prompt: str, limit: int | None, *, force_trim: bool = False) -> tuple[str, int]:
        trimmed = prompt
        pruned = 0
        if limit is not None and limit > 0 and len(prompt) > limit:
            trimmed = prompt[:limit]
            last_split = trimmed.rfind("\n\n")
            if last_split > int(limit * 0.6):
                trimmed = trimmed[:last_split]
            pruned = len(prompt) - len(trimmed)
        if force_trim and pruned == 0:
            marker = "Knowledge entries:"
            before, marker_token, after = prompt.partition(marker)
            if marker_token:
                lines = after.splitlines()
                if len(lines) > 6:
                    kept_lines = "\n".join(lines[:6]).strip()
                    trimmed_candidate = f"{before}{marker_token}\n{kept_lines}".strip()
                    if trimmed_candidate and len(trimmed_candidate) < len(prompt):
                        trimmed = trimmed_candidate
                        pruned = len(prompt) - len(trimmed)
        if force_trim and pruned == 0:
            current_len = len(prompt)
            target = max(int(current_len * 0.8), current_len - 200)
            if limit is not None and limit > 0:
                target = min(target, limit)
            target = max(target, 200)
            if target < current_len:
                trimmed = prompt[:target]
                pruned = len(prompt) - len(trimmed)
        return trimmed.rstrip(), max(pruned, 0)

    @classmethod
    def _kb_summary_from_entries(
        cls,
        prompt: str,
        entry_ids: Sequence[str],
        entries: Sequence[str],
        *,
        snippets: Sequence[KnowledgeSnippet] | None,
        client_id: int,
        language: str,
    ) -> QAResponse:
        if not entry_ids or not entries:
            raise AgentExecutionAborted("Knowledge base empty", reason="knowledge_base_empty")
        client_dataset = KnowledgeBase._dataset_name(client_id)
        index_map = {entry_id: idx for idx, entry_id in enumerate(entry_ids)}
        annotated: list[tuple[str, str, str]] = []
        for idx, text in enumerate(entries):
            cleaned = text.strip()
            if not cleaned:
                continue
            dataset = ""
            if snippets is not None and idx < len(snippets):
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
        sources = [source for _, source, _ in selected] or ["general_knowledge"]
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

    @staticmethod
    def _extract_message_content(content: Any) -> str:
        if isinstance(content, str):
            return content.strip()
        if hasattr(content, "model_dump"):
            try:
                dumped = content.model_dump()
            except Exception:  # noqa: BLE001
                dumped = None
            if isinstance(dumped, dict):
                maybe_text = dumped.get("text")
                if isinstance(maybe_text, str):
                    return maybe_text.strip()
        if isinstance(content, Sequence) and not isinstance(content, (str, bytes)):
            parts: list[str] = []
            for part in content:
                if isinstance(part, Mapping):
                    maybe_text = part.get("text") or part.get("content")
                    if isinstance(maybe_text, str) and maybe_text.strip():
                        parts.append(maybe_text.strip())
                elif hasattr(part, "text"):
                    candidate = getattr(part, "text")
                    if isinstance(candidate, str) and candidate.strip():
                        parts.append(candidate.strip())
            if parts:
                return "\n".join(parts)
        return ""

    @staticmethod
    def _supports_json_object(model: Any) -> bool:
        model_name = getattr(model, "model_name", None) or getattr(model, "name", None)
        if not model_name:
            return False
        normalized = str(model_name).lower()
        allowed_prefixes = (
            "gpt-4",
            "o3-",
            "o1-",
        )
        for segment in normalized.split("/"):
            if segment.startswith(allowed_prefixes):
                return True
        return False

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
                    "llm.request model={} json_format={} messages={} system_len={} user_len={} "
                    "temperature={} max_tokens={} tool_choice={}"
                ).format(
                    resolved_model,
                    request_meta["json_format"],
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
            content = message.get("content", "") or ""
            tool_calls = message.get("tool_calls")
        else:
            content = getattr(message, "content", "") or ""
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
        return {
            "choices": len(choices),
            "finish_reason": finish_reason or "",
            "content_len": len(str(content).strip()),
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
        use_json: bool,
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
        }
        if use_json:
            kwargs["response_format"] = {"type": "json_object"}
        return await client.chat.completions.create(**kwargs)  # pyrefly: ignore[no-untyped-call]

    @classmethod
    def _extract_choice_content(cls, response: Any, *, client_id: int | None = None) -> str:
        choices = getattr(response, "choices", None)
        if not choices:
            if client_id is not None:
                logger.debug(f"llm.parse client_id={client_id} empty=True reason=no_choices")
            return ""
        first_choice = choices[0]
        message = getattr(first_choice, "message", None)
        if message is None and isinstance(first_choice, Mapping):
            message = first_choice.get("message")
        if message is None and isinstance(first_choice, Mapping):
            fallback_text = first_choice.get("content") or first_choice.get("text")
            if isinstance(fallback_text, str) and fallback_text.strip():
                logger.debug("llm.parse client_id={} empty=False reason=choice_text".format(client_id or "na"))
                return fallback_text.strip()
        if message is None:
            if client_id is not None:
                logger.debug(f"llm.parse client_id={client_id} empty=True reason=no_message")
            return ""
        if isinstance(message, Mapping):
            content = message.get("content", "") or ""
            tool_calls = message.get("tool_calls")
        else:
            content = getattr(message, "content", "") or ""
            tool_calls = getattr(message, "tool_calls", None)
        extracted = cls._extract_message_content(content)
        if extracted:
            if client_id is not None:
                logger.debug(f"llm.parse client_id={client_id} empty=False reason=message_content")
            return extracted
        if tool_calls:
            for call in tool_calls:
                function = getattr(call, "function", None)
                arguments = getattr(function, "arguments", None)
                normalized = CoachAgent._normalize_tool_call_arguments(arguments)
                if normalized:
                    if client_id is not None:
                        logger.debug("llm.parse client_id={} empty=False reason=tool_call".format(client_id))
                    return normalized
        if client_id is not None:
            finish_reason = ""
            if choices:
                finish_reason = str(getattr(choices[0], "finish_reason", "") or "")
            preview = CoachAgent._message_preview(message)
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
        expects_json: bool,
        client_id: int,
    ) -> tuple[str, list[str]]:
        normalized_entries = [item for item in entry_ids if item]
        text = content.strip()
        if not text:
            return "", []
        should_parse_json = expects_json or text.lstrip().startswith("{")
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
                        text = str(item).strip()
                        if text:
                            normalized_sources.append(text)
                if normalized_sources:
                    valid = {entry for entry in normalized_entries}
                    normalized_sources = [item for item in normalized_sources if item in valid]
                if not normalized_sources:
                    normalized_sources = list(normalized_entries) if normalized_entries else ["general_knowledge"]
                return answer, normalized_sources
        answer = text
        default_sources = list(normalized_entries) if normalized_entries else ["general_knowledge"]
        return answer, default_sources

    @classmethod
    def _enforce_fitness_domain(
        cls,
        prompt: str,
        response: QAResponse,
        language: str,
        entry_ids: Sequence[str],
        entries: Sequence[str],
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
                    snippets=None,
                    client_id=client_id,
                    language=language,
                )
                return summary
            raise AgentExecutionAborted("Knowledge base empty", reason="knowledge_base_empty")
        response.answer = answer
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
