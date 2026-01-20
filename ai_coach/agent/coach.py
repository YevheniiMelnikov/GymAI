import inspect
import os
from datetime import datetime
from time import monotonic
from typing import Any, ClassVar, Sequence

from zoneinfo import ZoneInfo


from loguru import logger  # pyrefly: ignore[import-error]
from pydantic_ai import ModelRetry  # pyrefly: ignore[import-error]
from pydantic import ValidationError
from pydantic_ai.messages import ModelMessage, ModelRequest  # pyrefly: ignore[import-error]
from pydantic_ai.settings import ModelSettings  # pyrefly: ignore[import-error]

from config.app_settings import settings
from core.enums import WorkoutLocation
from core.schemas import DayExercises, DietPlan, Program, QAResponse, Subscription
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
    DIET_PLAN,
    GENERATE_WORKOUT,
    UPDATE_WORKOUT,
)
from ai_coach.types import CoachMode
from ai_coach.agent.utils import (
    ProgramAdapter,
    apply_workout_aux_rules,
    ensure_catalog_gif_keys,
    fill_missing_gif_keys,
    get_knowledge_base,
)
from ai_coach.schemas import (
    AgentDietPlanOutput,
    AgentProgramOutput,
    AgentQAResponseOutput,
    AgentSubscriptionOutput,
    ProgramPayload,
)

_LOG_PAYLOADS = os.getenv("AI_COACH_LOG_PAYLOADS", "").strip() == "1"


def _log_agent_stage(
    stage: str,
    elapsed_ms: int,
    *,
    profile_id: int,
    mode: CoachMode,
    **fields: Any,
) -> None:
    extra_parts = " ".join(f"{key}={value}" for key, value in fields.items() if value is not None)
    message = f"agent.stage stage={stage} profile_id={profile_id} mode={mode.value} elapsed_ms={elapsed_ms}"
    if extra_parts:
        message = f"{message} {extra_parts}"
    if elapsed_ms >= 500:
        logger.info(message)
    else:
        logger.debug(message)


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
    async def _load_history_messages(cls, profile_id: int) -> list[ModelMessage]:
        kb = get_knowledge_base()
        raw_history = await kb.get_message_history(profile_id)
        return cls.llm_helper._build_history_messages(raw_history)

    @classmethod
    async def generate_workout_plan(
        cls,
        prompt: str | None,
        deps: AgentDeps,
        *,
        workout_location: WorkoutLocation | None = None,
        period: str | None = None,
        split_number: int | None = None,
        wishes: str | None = None,
        profile_context: str | None = None,
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
        if profile_context:
            context_lines.append(f"Profile context:\n{profile_context}")
        if prompt:
            context_lines.append(prompt)
        if period:
            context_lines.append(f"Period: {period}")
        if split_number:
            context_lines.append(f"Split number: {split_number}")
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
        history_started = monotonic()
        kb = get_knowledge_base()
        raw_history = await kb.get_message_history(deps.profile_id)
        deps.cached_history = list(raw_history)
        history = cls.llm_helper._build_history_messages(raw_history)
        _log_agent_stage(
            "history_load",
            int((monotonic() - history_started) * 1000),
            profile_id=deps.profile_id,
            mode=deps.mode,
            messages=len(history),
        )
        logger.info(
            "agent.stage stage=run_start profile_id={} mode={} prompt_len={}",
            deps.profile_id,
            deps.mode.value,
            len(user_prompt),
        )
        run_started = monotonic()
        raw_result = await agent.run(
            user_prompt,
            deps=deps,
            output_type=AgentProgramOutput if output_type is Program else AgentSubscriptionOutput,
            message_history=history,
            model_settings=ModelSettings(
                temperature=settings.COACH_AGENT_TEMPERATURE,
                extra_body={"response_format": {"type": "json_object"}},
            ),
        )
        _log_agent_stage(
            "run",
            int((monotonic() - run_started) * 1000),
            profile_id=deps.profile_id,
            mode=deps.mode,
        )
        try:
            if output_type is Program:
                agent_output = cls._normalize_output(raw_result, AgentProgramOutput)
                payload_data = agent_output.model_dump()
                exercises_by_day = payload_data.get("exercises_by_day")
                if isinstance(exercises_by_day, list):
                    apply_workout_aux_rules(
                        exercises_by_day,
                        language=cls._lang(deps),
                        workout_location=getattr(workout_location, "value", None) if workout_location else None,
                        wishes=str(payload_data.get("wishes") or wishes or ""),
                        prompt=prompt,
                        profile_context=profile_context,
                    )
                program_payload = ProgramPayload.model_validate(payload_data)
                normalized = ProgramAdapter.to_domain(program_payload)
            else:
                agent_output = cls._normalize_output(raw_result, AgentSubscriptionOutput)
                payload_data = agent_output.model_dump()
                exercises = payload_data.get("exercises")
                if isinstance(exercises, list):
                    apply_workout_aux_rules(
                        exercises,
                        language=cls._lang(deps),
                        workout_location=getattr(workout_location, "value", None) if workout_location else None,
                        wishes=str(payload_data.get("wishes") or wishes or ""),
                        prompt=prompt,
                        profile_context=profile_context,
                    )
                normalized = Subscription.model_validate(payload_data)
        except ValidationError as exc:
            raise ModelRetry(
                "Model output must match the Program schema with required fields "
                "(id, profile, created_at, exercises_by_day). Return a single JSON object."
            ) from exc
        logger.debug(
            f"agent.done profile_id={deps.profile_id} mode={deps.mode.value if deps.mode else 'unknown'} "
            f"tools_called={sorted(deps.called_tools)}"
        )
        return normalized

    @classmethod
    async def generate_diet_plan(
        cls,
        prompt: str | None,
        deps: AgentDeps,
        *,
        profile_context: str | None = None,
        diet_allergies: str | None = None,
        diet_products: list[str] | None = None,
        instructions: str | None = None,
    ) -> DietPlan:
        deps.mode = CoachMode.diet
        deps.disabled_tools.add("tool_search_exercises")
        logger.debug(
            f"agent.stage stage=disable_tool profile_id={deps.profile_id} mode=diet tool=tool_search_exercises"
        )
        deps.max_tool_calls = 6
        agent = cls._get_agent()
        today = datetime.now(ZoneInfo(settings.TIME_ZONE)).date().isoformat()
        context_lines: list[str] = []
        if profile_context:
            context_lines.append(profile_context)
        else:
            context_lines.append("Profile data: not provided.")
        if prompt:
            context_lines.append(f"User request: {prompt}")
        diet_pref_lines: list[str] = []
        if diet_allergies:
            diet_pref_lines.append(f"Allergies: {diet_allergies}")
        if diet_products:
            diet_pref_lines.append(f"Allowed products: {', '.join(diet_products)}")
        if not diet_pref_lines:
            diet_pref_lines.append("No additional diet preferences provided.")
        rules = "\n".join(filter(None, [instructions]))
        formatted = DIET_PLAN.format(
            current_date=today,
            profile_context="\n".join(context_lines),
            diet_preferences="\n".join(diet_pref_lines),
            language=cls._lang(deps),
        )
        if rules:
            formatted = f"{formatted}\n\nRules:\n{rules}"
        user_prompt = f"MODE: diet\n{formatted}"
        history_started = monotonic()
        kb = get_knowledge_base()
        raw_history = await kb.get_message_history(deps.profile_id)
        deps.cached_history = list(raw_history)
        history = cls.llm_helper._build_history_messages(raw_history)
        _log_agent_stage(
            "history_load",
            int((monotonic() - history_started) * 1000),
            profile_id=deps.profile_id,
            mode=deps.mode,
            messages=len(history),
        )
        logger.info(
            "agent.stage stage=run_start profile_id={} mode={} prompt_len={}",
            deps.profile_id,
            deps.mode.value,
            len(user_prompt),
        )
        run_started = monotonic()
        raw_result = await agent.run(
            user_prompt,
            deps=deps,
            output_type=AgentDietPlanOutput,
            message_history=history,
            model_settings=ModelSettings(
                temperature=settings.COACH_AGENT_TEMPERATURE,
                extra_body={"response_format": {"type": "json_object"}},
            ),
        )
        _log_agent_stage(
            "run",
            int((monotonic() - run_started) * 1000),
            profile_id=deps.profile_id,
            mode=deps.mode,
        )
        try:
            agent_output = cls._normalize_output(raw_result, AgentDietPlanOutput)
            normalized = DietPlan.model_validate(agent_output.model_dump())
        except ValidationError as exc:
            raise ModelRetry("Model output must match the DietPlan schema. Return a single JSON object.") from exc
        logger.debug(
            f"agent.done profile_id={deps.profile_id} mode={deps.mode.value} tools_called={sorted(deps.called_tools)}"
        )
        return normalized

    @classmethod
    async def update_workout_plan(
        cls,
        prompt: str | None,
        feedback: str,
        deps: AgentDeps,
        *,
        workout_location: WorkoutLocation | None = None,
        profile_context: str | None = None,
        output_type: type[Program] | type[Subscription] = Subscription,
        instructions: str | None = None,
    ) -> Program | Subscription:
        agent = cls._get_agent()
        deps.mode = CoachMode.update
        deps.disabled_tools.add("tool_search_knowledge")
        today = datetime.now(ZoneInfo(settings.TIME_ZONE)).date().isoformat()
        context_lines: list[str] = []
        if workout_location:
            context_lines.append(f"Workout location: {workout_location.value}")
        if profile_context:
            context_lines.append(f"Profile context:\n{profile_context}")
        if prompt:
            context_lines.append(prompt)
        formatted = UPDATE_WORKOUT.format(
            current_date=today,
            feedback=feedback,
            context="\n".join(context_lines),
            language=cls._lang(deps),
        )
        rules = "\n".join(filter(None, [COACH_INSTRUCTIONS, instructions]))
        user_prompt = f"MODE: update\n{formatted}\nRules:\n{rules}"
        history_started = monotonic()
        kb = get_knowledge_base()
        raw_history = await kb.get_message_history(deps.profile_id)
        deps.cached_history = list(raw_history)
        history = cls.llm_helper._build_history_messages(raw_history)
        _log_agent_stage(
            "history_load",
            int((monotonic() - history_started) * 1000),
            profile_id=deps.profile_id,
            mode=deps.mode,
            messages=len(history),
        )
        logger.info(
            "agent.stage stage=run_start profile_id={} mode={} prompt_len={}",
            deps.profile_id,
            deps.mode.value,
            len(user_prompt),
        )
        run_started = monotonic()
        raw_result = await agent.run(
            user_prompt,
            deps=deps,
            output_type=AgentProgramOutput if output_type is Program else AgentSubscriptionOutput,
            message_history=history,
            model_settings=ModelSettings(
                temperature=settings.COACH_AGENT_TEMPERATURE,
                extra_body={"response_format": {"type": "json_object"}},
            ),
        )
        _log_agent_stage(
            "run",
            int((monotonic() - run_started) * 1000),
            profile_id=deps.profile_id,
            mode=deps.mode,
        )
        if output_type is Program:
            try:
                agent_output = cls._normalize_output(raw_result, AgentProgramOutput)
                payload_data = agent_output.model_dump()
                exercises_by_day = payload_data.get("exercises_by_day")
                if isinstance(exercises_by_day, list):
                    apply_workout_aux_rules(
                        exercises_by_day,
                        language=cls._lang(deps),
                        workout_location=getattr(workout_location, "value", None) if workout_location else None,
                        wishes=str(payload_data.get("wishes") or ""),
                        prompt=prompt,
                        profile_context=profile_context,
                    )
                program_payload = ProgramPayload.model_validate(payload_data)
                normalized = ProgramAdapter.to_domain(program_payload)
            except ValidationError as exc:
                raise ModelRetry(
                    "Model output must match the Program schema with required fields "
                    "(id, profile, created_at, exercises_by_day). Return a single JSON object."
                ) from exc
            exercises = [day.model_dump() for day in normalized.exercises_by_day]
            try:
                fill_missing_gif_keys(exercises)
                ensure_catalog_gif_keys(exercises)
            except ValueError as exc:
                raise ModelRetry(
                    f"Exercise catalog validation failed: {exc}. Use tool_search_exercises and include gif_key."
                ) from exc
            normalized.exercises_by_day = [DayExercises.model_validate(day) for day in exercises]
            return normalized
        try:
            agent_output = cls._normalize_output(raw_result, AgentSubscriptionOutput)
            payload_data = agent_output.model_dump()
            exercises = payload_data.get("exercises")
            if isinstance(exercises, list):
                apply_workout_aux_rules(
                    exercises,
                    language=cls._lang(deps),
                    workout_location=getattr(workout_location, "value", None) if workout_location else None,
                    wishes=str(payload_data.get("wishes") or ""),
                    prompt=prompt,
                    profile_context=profile_context,
                )
            normalized = Subscription.model_validate(payload_data)
        except ValidationError as exc:
            raise ModelRetry("Model output must match the Subscription schema. Return a single JSON object.") from exc
        exercises = [day.model_dump() for day in normalized.exercises]
        try:
            fill_missing_gif_keys(exercises)
            ensure_catalog_gif_keys(exercises)
        except ValueError as exc:
            raise ModelRetry(
                f"Exercise catalog validation failed: {exc}. Use tool_search_exercises and include gif_key."
            ) from exc
        normalized.exercises = [DayExercises.model_validate(day) for day in exercises]
        return normalized

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
        history_started = monotonic()
        raw_history = await kb.get_message_history(deps.profile_id)
        deps.cached_history = list(raw_history)
        history = cls.llm_helper._build_history_messages(raw_history)
        _log_agent_stage(
            "history_load",
            int((monotonic() - history_started) * 1000),
            profile_id=deps.profile_id,
            mode=deps.mode,
            messages=len(history),
        )
        user_prompt = ASK_AI_USER_PROMPT.format(
            language=language_label,
            question=prompt,
        )

        multimodal_input = cls._build_user_message(user_prompt, attachments)

        async def _run_agent(user_input: Any) -> Any:
            mode = deps.mode or CoachMode.ask_ai
            logger.info(
                f"agent.stage stage=run_start profile_id={deps.profile_id} mode={mode.value} "
                f"prompt_len={len(user_prompt)}"
            )
            run_started = monotonic()
            result = await agent.run(
                user_input,
                deps=deps,
                output_type=AgentQAResponseOutput,
                message_history=history,
                model_settings=ModelSettings(
                    temperature=settings.COACH_AGENT_TEMPERATURE,
                    extra_body={"response_format": {"type": "json_object"}},
                ),
            )
            _log_agent_stage(
                "run",
                int((monotonic() - run_started) * 1000),
                profile_id=deps.profile_id,
                mode=mode,
            )
            return result

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
        try:
            agent_output = cls._normalize_output(raw_result, AgentQAResponseOutput)
            normalized = QAResponse.model_validate(agent_output.model_dump())
        except ValidationError as exc:
            raise ModelRetry("Model output must match the QAResponse schema. Return a single JSON object.") from exc
        normalized.answer = cls.llm_helper._strip_markup(normalized.answer).strip()
        if normalized.blocks:
            normalized.blocks = cls.llm_helper._normalize_blocks(normalized.blocks) or None
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
        if _LOG_PAYLOADS:
            logger.debug(
                "agent.ask.sources profile_id={} count={} sources={}",
                deps.profile_id,
                len(normalized.sources),
                ",".join(normalized.sources),
            )
        logger.debug(
            f"agent.ask.done profile_id={deps.profile_id} answer_len={len(normalized.answer)} "
            f"sources_count={len(normalized.sources)} kb_used={deps.kb_used}"
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
