import inspect
from datetime import datetime
from typing import Any, ClassVar, Sequence

from zoneinfo import ZoneInfo

from loguru import logger  # pyrefly: ignore[import-error]
from pydantic_ai.settings import ModelSettings  # pyrefly: ignore[import-error]

from config.app_settings import settings
from core.enums import WorkoutType
from core.schemas import Program, QAResponse, Subscription
from ai_coach.exceptions import AgentExecutionAborted
from ai_coach.agent.knowledge.schemas import KnowledgeSnippet

from .base import AgentDeps
from .llm_helper import LLMHelper, LLMHelperProto
from .prompts import (
    ASK_AI_USER_PROMPT,
    COACH_INSTRUCTIONS,
    GENERATE_WORKOUT,
    UPDATE_WORKOUT,
)
from ai_coach.types import CoachMode


class CoachAgentMeta(type):
    def __getattr__(cls, name: str) -> Any:
        helper = getattr(cls, "llm_helper", None)
        if helper is None:
            raise AttributeError(f"{cls.__name__} has no attribute {name!r} (llm_helper is not configured)")
        try:
            return getattr(helper, name)
        except AttributeError as exc:
            raise AttributeError(f"{cls.__name__} has no attribute {name!r}") from exc


class CoachAgent(metaclass=CoachAgentMeta):
    """PydanticAI wrapper for program generation."""

    llm_helper: ClassVar[type[LLMHelperProto]] = LLMHelper

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
        history = cls._message_history(deps.profile_id)
        if inspect.isawaitable(history):
            history = await history
        raw_result = await agent.run(
            user_prompt,
            deps=deps,
            output_type=output_type,
            message_history=history,
            model_settings=ModelSettings(  # pyrefly: ignore[unexpected-keyword]
                response_format={"type": "json_object"},  # pyrefly: ignore[unexpected-keyword]
                temperature=0.2,
            ),
        )
        if output_type is Program:
            normalized = cls._normalize_output(raw_result, Program)
        else:
            normalized = cls._normalize_output(raw_result, Subscription)
        logger.debug(
            f"agent.done profile_id={deps.profile_id} mode={deps.mode.value if deps.mode else 'unknown'} "
            f"tools_called={sorted(deps.called_tools)}"
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
        history = cls._message_history(deps.profile_id)
        if inspect.isawaitable(history):
            history = await history
        raw_result = await agent.run(
            user_prompt,
            deps=deps,
            output_type=output_type,
            message_history=history,
            model_settings=ModelSettings(  # pyrefly: ignore[unexpected-keyword]
                response_format={"type": "json_object"},  # pyrefly: ignore[unexpected-keyword]
                temperature=0.2,
            ),
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
        deps.mode = CoachMode.ask_ai
        agent = cls._get_agent()
        _, language_label = cls._language_context(deps)
        history = await cls._message_history(deps.profile_id)
        user_prompt = ASK_AI_USER_PROMPT.format(
            language=language_label,
            question=prompt,
        )
        try:
            raw_result = await agent.run(
                user_prompt,
                deps=deps,
                output_type=QAResponse,
                message_history=history,
                model_settings=ModelSettings(  # pyrefly: ignore[unexpected-keyword]
                    response_format={"type": "json_object"},  # pyrefly: ignore[unexpected-keyword]
                    temperature=0.2,
                ),
            )
        except AgentExecutionAborted as exc:
            logger.info(f"agent.ask completion_aborted profile_id={deps.profile_id} reason={exc.reason}")
            if exc.reason == "knowledge_base_empty":
                deps.knowledge_base_empty = True
            fallback = await cls._fallback_answer_question(
                prompt,
                deps,
                history,
                prefetched_knowledge=None,
            )
            if fallback is not None:
                return fallback
            raise AgentExecutionAborted("ask_ai_unavailable", reason="ask_ai_unavailable")
        normalized = cls._normalize_output(raw_result, QAResponse)
        normalized.answer = normalized.answer.strip()
        if not normalized.answer:
            fallback = await cls._fallback_answer_question(
                prompt,
                deps,
                history,
                prefetched_knowledge=None,
            )
            if fallback is not None:
                return fallback
            raise AgentExecutionAborted("ask_ai_unavailable", reason="model_empty_response")
        if not normalized.sources:
            normalized.sources = ["knowledge_base"] if deps.kb_used else ["general_knowledge"]
        logger.info(
            f"agent.ask.done profile_id={deps.profile_id} answer_len={len(normalized.answer)} "
            f"sources={','.join(normalized.sources)} kb_used={deps.kb_used}"
        )
        return normalized

    @staticmethod
    def _build_knowledge_entries(
        entries: Sequence[KnowledgeSnippet | str],
    ) -> tuple[list[str], list[str]]:
        """Prepare knowledge entries for the prompt, skipping non-content items."""
        texts: list[str] = []
        ids: list[str] = []
        for i, entry in enumerate(entries):
            text = ""
            kind = "document"
            if isinstance(entry, str):
                text = entry
            else:
                text = getattr(entry, "text", "")
                kind = getattr(entry, "kind", "document")

            if kind not in ("document", "note"):
                continue

            normalized = CoachAgent._normalize_text(text)
            if normalized:
                texts.append(normalized)
                ids.append(f"KB-{i + 1}")
        return ids, texts
