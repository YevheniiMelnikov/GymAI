import inspect
from datetime import datetime
from typing import Any, ClassVar, Sequence

from zoneinfo import ZoneInfo


from loguru import logger  # pyrefly: ignore[import-error]
from pydantic_ai.messages import ModelRequest  # pyrefly: ignore[import-error]
from pydantic_ai.settings import ModelSettings  # pyrefly: ignore[import-error]

from config.app_settings import settings
from core.enums import WorkoutLocation
from core.schemas import Program, QAResponse, Subscription
from ai_coach.exceptions import AgentExecutionAborted
from ai_coach.agent.knowledge.schemas import KnowledgeSnippet

try:  # pragma: no cover - compatibility guard
    import pydantic_ai.exceptions as _pa_exceptions  # type: ignore
except Exception:  # noqa: BLE001
    BadRequestError = RuntimeError
else:
    BadRequestError = getattr(_pa_exceptions, "BadRequestError", RuntimeError)

from .base import AgentDeps
from .llm_helper import LLMHelper, LLMHelperProto
from .prompts import (
    ASK_AI_USER_PROMPT,
    COACH_INSTRUCTIONS,
    GENERATE_WORKOUT,
    UPDATE_WORKOUT,
)
from ai_coach.types import CoachMode
from ai_coach.agent.utils import get_knowledge_base


class CoachAgentMeta(type):
    def __getattr__(cls, name: str) -> Any:
        helper = getattr(cls, "llm_helper", None)
        if helper is None:
            raise AttributeError(f"{cls.__name__} has no attribute {name!r} (llm_helper is not configured)")
        try:
            descriptor = inspect.getattr_static(helper, name)
        except AttributeError as exc:
            raise AttributeError(f"{cls.__name__} has no attribute {name!r}") from exc
        if hasattr(descriptor, "__get__"):
            return descriptor.__get__(None, cls)
        return getattr(helper, name)


class CoachAgent(metaclass=CoachAgentMeta):
    """PydanticAI wrapper for program generation."""

    llm_helper: ClassVar[type[LLMHelperProto]] = LLMHelper

    @classmethod
    async def generate_workout_plan(
        cls,
        prompt: str | None,
        deps: AgentDeps,
        *,
        workout_location: WorkoutLocation | None = None,
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
        if workout_location:
            context_lines.append(f"Workout location: {workout_location.value}")
        if prompt:
            context_lines.append(prompt)
        if period:
            context_lines.append(f"Period: {period}")
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
                temperature=settings.COACH_AGENT_TEMPERATURE,
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
        workout_location: WorkoutLocation | None = None,
        output_type: type[Program] | type[Subscription] = Subscription,
        instructions: str | None = None,
    ) -> Program | Subscription:
        agent = cls._get_agent()
        deps.mode = CoachMode.update
        context_lines: list[str] = []
        if workout_location:
            context_lines.append(f"Workout location: {workout_location.value}")
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
                temperature=settings.COACH_AGENT_TEMPERATURE,
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
        attachments: Sequence[dict[str, str]] | None = None,
    ) -> QAResponse:
        deps.mode = CoachMode.ask_ai
        agent = cls._get_agent()
        _, language_label = cls._language_context(deps)
        kb = get_knowledge_base()
        raw_history = await kb.get_message_history(deps.profile_id)
        deps.cached_history = list(raw_history)
        history = cls.llm_helper._build_history_messages(raw_history)
        user_prompt = ASK_AI_USER_PROMPT.format(
            language=language_label,
            question=prompt,
        )

        multimodal_input = cls._build_user_message(user_prompt, attachments)

        async def _run_agent(user_input: Any) -> Any:
            return await agent.run(
                user_input,
                deps=deps,
                output_type=QAResponse,
                message_history=history,
                model_settings=ModelSettings(  # pyrefly: ignore[unexpected-keyword]
                    response_format={"type": "json_object"},  # pyrefly: ignore[unexpected-keyword]
                    temperature=settings.COACH_AGENT_TEMPERATURE,
                ),
            )

        async def _handle_abort(exc: AgentExecutionAborted) -> QAResponse | None:
            logger.info(f"agent.ask completion_aborted profile_id={deps.profile_id} reason={exc.reason}")
            if exc.reason == "knowledge_base_empty":
                deps.knowledge_base_empty = True
            if exc.reason in {"timeout", "max_tool_calls_exceeded"}:
                return None
            fallback = await cls._fallback_answer_question(
                prompt,
                deps,
                history,
                prefetched_knowledge=None,
            )
            if fallback is not None:
                return fallback
            raise AgentExecutionAborted("ask_ai_unavailable", reason="ask_ai_unavailable")

        raw_result: Any | None = None
        try:
            raw_result = await _run_agent(multimodal_input)
        except AgentExecutionAborted as exc:
            fallback_result = await _handle_abort(exc)
            if fallback_result is None:
                raise
            return fallback_result
        except BadRequestError as exc:
            if not attachments:
                raise
            logger.warning(
                "agent.ask.vision_fallback profile_id={} attachments={} error={}",
                deps.profile_id,
                len(attachments),
                exc,
            )
            try:
                raw_result = await _run_agent(user_prompt)
            except AgentExecutionAborted as inner:
                fallback_result = await _handle_abort(inner)
                if fallback_result is None:
                    raise
                return fallback_result
            except BadRequestError:
                raise

        if raw_result is None:
            raise RuntimeError("agent.ask_result_missing")
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
    def _build_user_message(
        prompt: str,
        attachments: Sequence[dict[str, str]] | None = None,
    ) -> Any:
        if not attachments:
            return prompt
        content_parts: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for attachment in attachments:
            mime = str(attachment.get("mime") or "").strip()
            data_base64 = str(attachment.get("data_base64") or "").strip()
            if not mime or not data_base64:
                continue
            uri = f"data:{mime};base64,{data_base64}"
            content_parts.append(
                {
                    "type": "image_url",
                    "image_url": {"url": uri},
                }
            )
        if len(content_parts) == 1:
            return prompt
        builder = getattr(ModelRequest, "user_content", None)
        if callable(builder):  # pragma: no cover - optional API
            try:
                return builder(content_parts)
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"agent.ask.user_content_builder_failed error={exc}")
        return {"role": "user", "content": content_parts}

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
