from base64 import b64decode
from binascii import Error as BinasciiError
from hashlib import sha1
import asyncio
import os
from datetime import datetime
from time import monotonic
from typing import Any, cast, Iterable
from uuid import uuid4

from cachetools import TTLCache
from fastapi import HTTPException  # pyrefly: ignore[import-error]
from fastapi.responses import JSONResponse  # pyrefly: ignore[import-error]
from loguru import logger  # pyrefly: ignore[import-error]
from pydantic import ValidationError  # pyrefly: ignore[import-error]

try:
    import pydantic_ai.exceptions as _pa_exceptions  # type: ignore
except Exception:  # noqa: BLE001
    ModelHTTPError = RuntimeError
else:
    ModelHTTPError = getattr(_pa_exceptions, "ModelHTTPError", RuntimeError)

from ai_coach.agent import AgentDeps, CoachAgent
from ai_coach.agent.knowledge.knowledge_base import KnowledgeBase
from ai_coach.agent.knowledge.schemas import ProjectionStatus
from ai_coach.agent.utils import get_knowledge_base
from ai_coach.exceptions import AgentExecutionAborted
from ai_coach.schemas import AICoachRequest
from ai_coach.types import AskCtx, CoachMode, MessageRole
from ai_coach.coach_actions import DISPATCH, CoachAction
from config.app_settings import settings
from core.cache import Cache
from core.enums import SubscriptionPeriod
from core.schemas import DayExercises, DietPlan, Exercise, Program, Profile, QAResponse, Subscription
from core.services import APIService

DEFAULT_SPLIT_NUMBER = 3
dedupe_cache = TTLCache(maxsize=2048, ttl=15)
request_cache = TTLCache(maxsize=2048, ttl=900)
_ALLOWED_ATTACHMENT_MIME = {"image/jpeg", "image/png", "image/webp"}
_LOG_PAYLOADS = os.getenv("AI_COACH_LOG_PAYLOADS", "").strip() == "1"
_inflight_requests: dict[str, asyncio.Future] = {}
_inflight_lock = asyncio.Lock()

WORKOUT_EXPERIENCE_DESCRIPTIONS: dict[str, str] = {
    "beginner": "a newcomer with little to no structured training or only very sporadic activity, not yet training consistently", # noqa: E501
    "amateur": "someone with a few months of experience, training irregularly and comfortable with basic movements",
    "advanced": "a regular trainee for at least a year, familiar with technique and structured progression patterns",
    "pro": "long-term, consistent athlete with years of disciplined practice, close to competitive conditioning",
}


def _to_language_code(raw: object, default: str) -> str:
    """Normalize raw language values to a lowercase language code."""

    if raw is None:
        return default

    value_obj: object = getattr(raw, "value", raw)
    candidate: str = str(value_obj or "").strip()
    if not candidate:
        return default

    normalized: str = candidate.lower()
    if normalized.startswith("language."):
        normalized = normalized.split(".", 1)[1]
    return normalized or default


def _compute_dedupe_key(
    prompt: str | None,
    profile_id: int,
    mode: CoachMode,
    *,
    attachments: Iterable[dict[str, str]] | None = None,
) -> str | None:
    if not prompt:
        return None
    base = f"{profile_id}:{prompt.strip()}:{mode.value}"
    if attachments:
        for attachment in attachments:
            fingerprint = str(attachment.get("data_base64") or "").strip()
            if not fingerprint:
                continue
            base = f"{base}:{sha1(fingerprint.encode()).hexdigest()[:16]}"
            break
    return sha1(base.encode()).hexdigest()


def _resolve_language(request_lang: object | None, profile: Profile | None) -> str:
    request_language: str | None = None
    if request_lang:
        request_language = _to_language_code(request_lang, settings.DEFAULT_LANG)

    profile_language: str | None = None
    if profile is not None:
        profile_language_raw = getattr(profile, "language", None)
        if profile_language_raw is not None:
            profile_language = _to_language_code(profile_language_raw, settings.DEFAULT_LANG)

    return request_language or profile_language or settings.DEFAULT_LANG


async def _ingest_chat_prompt(
    kb: KnowledgeBase,
    profile_id: int,
    prompt: str,
) -> None:
    kb_chat_dataset = kb.chat_dataset_name(profile_id)
    await kb.add_text(
        dataset=kb_chat_dataset,
        text=prompt,
        role=MessageRole.CLIENT,
        profile_id=profile_id,
    )
    question_bytes = len(prompt.encode())
    logger.debug(f"ask.ingest_chat profile_id={profile_id} dataset={kb_chat_dataset} bytes={question_bytes}")
    chat_user = getattr(kb, "_user", None)
    if chat_user is None:
        chat_user = await kb.dataset_service.get_cognee_user()
    try:
        wait_status = await kb.projection_service.wait(
            kb_chat_dataset,
            chat_user,
            timeout=2.0,
        )
    except Exception as exc:  # noqa: BLE001 - projection best effort
        logger.debug(f"ask.wait_projection dataset={kb_chat_dataset} timeout=2.0 result=error detail={exc}")
    else:
        status_label = "ok" if wait_status in {ProjectionStatus.READY, ProjectionStatus.READY_EMPTY} else "timeout"
        logger.debug(f"ask.wait_projection dataset={kb_chat_dataset} timeout=2.0 {status_label}")


async def _fetch_profile(profile_id: int) -> Profile | None:
    try:
        return await APIService.profile.get_profile(profile_id)
    except Exception:
        return None


def _build_context(
    data,
    language: str,
    period: SubscriptionPeriod,
    split_number: int,
    deps: AgentDeps,
    attachments: list[dict[str, str]],
    *,
    profile_context: str | None = None,
) -> AskCtx:
    return {
        "prompt": data.prompt,
        "profile_id": data.profile_id,
        "attachments": attachments,
        "period": period.value,
        "split_number": split_number,
        "feedback": data.feedback or "",
        "wishes": data.wishes or "",
        "language": language,
        "workout_location": data.workout_location,
        "plan_type": data.plan_type,
        "diet_allergies": data.diet_allergies,
        "diet_products": data.diet_products or [],
        "profile_context": profile_context,
        "instructions": data.instructions,
        "deps": deps,
    }


def _format_exercise_entry(exercise: Exercise) -> str:
    details: list[str] = []
    sets = getattr(exercise, "sets", None)
    reps = getattr(exercise, "reps", None)
    if sets and reps:
        details.append(f"{sets}x{reps}")
    elif sets:
        details.append(f"{sets} sets")
    elif reps:
        details.append(f"{reps} reps")
    weight = getattr(exercise, "weight", None)
    if weight:
        details.append(f"weight {weight}")
    if details:
        return f"{exercise.name} ({', '.join(details)})"
    return exercise.name


def _format_plan_days(days: list[DayExercises], *, max_exercises: int = 8) -> list[str]:
    lines: list[str] = []
    for day in days:
        exercises = day.exercises or []
        if not exercises:
            lines.append(f"{day.day}: no exercises")
            continue
        entries = [_format_exercise_entry(ex) for ex in exercises[:max_exercises]]
        if len(exercises) > max_exercises:
            entries.append("…")
        lines.append(f"{day.day}: {', '.join(entries)}")
    return lines


def _format_program_label(program: Program, *, ordinal: int | None = None) -> str:
    created_at = getattr(program, "created_at", None)
    label = f"Program {ordinal}" if ordinal is not None else "Program"
    if created_at is not None:
        return f"{label} (created_at: {created_at})"
    return label


def _format_subscription_label(subscription: Subscription, *, ordinal: int | None = None) -> str:
    label = f"Subscription {ordinal}" if ordinal is not None else "Subscription"
    payment_date = getattr(subscription, "payment_date", None)
    period = getattr(subscription, "period", None)
    parts = [f"period: {period}" if period else None, f"payment_date: {payment_date}" if payment_date else None]
    summary = ", ".join(part for part in parts if part)
    if summary:
        return f"{label} ({summary})"
    return label


async def _build_profile_context(profile: Profile | None, *, include_plans: bool) -> str | None:
    if profile is None:
        return None
    lines: list[str] = []
    workout_goals = getattr(profile, "workout_goals", None)
    if workout_goals:
        lines.append(f"Workout goals: {workout_goals}")
    weight = getattr(profile, "weight", None)
    if weight:
        lines.append(f"Weight (kg): {weight}")
    height = getattr(profile, "height", None)
    if height:
        lines.append(f"Height (cm): {height}")
    workout_experience = getattr(profile, "workout_experience", None)
    if workout_experience:
        experience_value = str(workout_experience).lower()
        experience_description = WORKOUT_EXPERIENCE_DESCRIPTIONS.get(experience_value)
        if experience_description:
            lines.append(f"Workout experience: {experience_value} ({experience_description})")
        else:
            lines.append(f"Workout experience: {experience_value}")
    health_notes = getattr(profile, "health_notes", None)
    if health_notes:
        lines.append(f"Health notes: {health_notes}")
    diet_allergies = getattr(profile, "diet_allergies", None)
    if diet_allergies is not None:
        allergies = str(diet_allergies).strip()
        if allergies:
            lines.append(f"Diet allergies: {allergies}")
        else:
            lines.append("Diet allergies: none")
    diet_products = getattr(profile, "diet_products", None)
    if diet_products:
        lines.append(f"Diet products: {', '.join(diet_products)}")
    gender = getattr(profile, "gender", None)
    if gender:
        lines.append(f"Gender: {gender.value}")
    born_in = getattr(profile, "born_in", None)
    if born_in:
        lines.append(f"Birth year: {born_in}")
    if include_plans:
        try:
            programs = await Cache.workout.get_all_programs(profile.id)
        except Exception:  # noqa: BLE001
            programs = []
        if programs:
            sorted_programs = sorted(
                programs,
                key=lambda program: float(getattr(program, "created_at", 0.0) or 0.0),
                reverse=True,
            )
            programs_added = False
            for index, program in enumerate(sorted_programs[:3], start=1):
                try:
                    program_days = [
                        day if isinstance(day, DayExercises) else DayExercises.model_validate(day)
                        for day in program.exercises_by_day
                    ]
                except Exception:  # noqa: BLE001
                    program_days = []
                if program_days:
                    if not programs_added:
                        lines.append("Recent programs:")
                        programs_added = True
                    lines.append(_format_program_label(program, ordinal=index))
                    lines.extend(_format_plan_days(program_days))
        try:
            subscriptions = await Cache.workout.get_all_subscriptions(profile.id)
        except Exception:  # noqa: BLE001
            subscriptions = []
        if subscriptions:

            def _subscription_sort_key(subscription: Subscription) -> tuple[float, int]:
                payment_date = getattr(subscription, "payment_date", None)
                timestamp = 0.0
                if payment_date:
                    try:
                        timestamp = datetime.fromisoformat(str(payment_date)).timestamp()
                    except ValueError:
                        timestamp = 0.0
                return (timestamp, int(getattr(subscription, "id", 0) or 0))

            sorted_subscriptions = sorted(subscriptions, key=_subscription_sort_key, reverse=True)
            subscriptions_added = False
            for index, subscription in enumerate(sorted_subscriptions[:3], start=1):
                try:
                    sub_days = [
                        day if isinstance(day, DayExercises) else DayExercises.model_validate(day)
                        for day in subscription.exercises
                    ]
                except Exception:  # noqa: BLE001
                    sub_days = []
                if sub_days:
                    if not subscriptions_added:
                        lines.append("Recent subscriptions:")
                        subscriptions_added = True
                    lines.append(_format_subscription_label(subscription, ordinal=index))
                    lines.extend(_format_plan_days(sub_days))
    return "\n".join(lines) if lines else None


def _normalize_attachments(raw: Any) -> tuple[list[dict[str, str]], int]:
    attachments: list[dict[str, str]] = []
    total_bytes = 0
    if not raw:
        return attachments, total_bytes
    for item in raw:
        if not isinstance(item, dict):
            continue
        mime = str(item.get("mime") or "").strip().lower()
        data_base64 = str(item.get("data_base64") or "").strip()
        if not mime or not data_base64:
            continue
        if mime not in _ALLOWED_ATTACHMENT_MIME:
            logger.warning(f"ask.attachments_unsupported_mime mime={mime}")
            continue
        try:
            decoded = b64decode(data_base64, validate=True)
        except (BinasciiError, ValueError):
            logger.warning("ask.attachments_invalid_base64 mime={} bytes_hint={}", mime, len(data_base64))
            continue
        if not decoded:
            continue
        total_bytes += len(decoded)
        attachments.append({"mime": mime, "data_base64": data_base64})
    return attachments, total_bytes


def _allowed_mode_or_422(mode: CoachMode, allowed: set[CoachMode]) -> None:
    if allowed and mode not in allowed:
        raise HTTPException(status_code=422, detail=f"Unsupported mode {mode.value}")


def _log_sources(
    rid: str,
    request_id: str | None,
    profile_id: int,
    deps: AgentDeps,
    result: QAResponse,
    sources: list[str],
) -> None:
    if sources and _LOG_PAYLOADS:
        joined = " | ".join(sources)
        if len(joined) > 300:
            joined = joined[:297] + "..."
        logger.debug(
            f"/ask agent sources rid={rid} request_id={request_id} profile_id={profile_id} "
            f"count={len(sources)} sources={joined}"
        )
    origin = "llm"
    answer_len = len(result.answer) if isinstance(result.answer, str) else 0
    if deps.fallback_used:
        origin = "kb_fallback"
    elif not isinstance(result, QAResponse):
        origin = "structured"
    logger.debug(
        "api.answer_out rid={} request_id={} profile_id={} len={} from={}",
        rid,
        request_id,
        profile_id,
        answer_len,
        origin,
    )


def _log_stage_duration(
    stage: str,
    started: float,
    *,
    request_id: str | None,
    profile_id: int,
    mode: CoachMode,
    **fields: Any,
) -> None:
    elapsed_ms = int((monotonic() - started) * 1000)
    extra_parts = " ".join(f"{key}={value}" for key, value in fields.items() if value is not None)
    message = (
        f"ask.stage stage={stage} request_id={request_id} profile_id={profile_id} "
        f"mode={mode.value} elapsed_ms={elapsed_ms}"
    )
    if extra_parts:
        message = f"{message} {extra_parts}"
    if elapsed_ms >= 500:
        logger.info(message)
    else:
        logger.debug(message)


async def _handle_abort(
    exc: AgentExecutionAborted,
    deps: AgentDeps,
    mode: CoachMode,
) -> Program | Subscription | JSONResponse:
    reason_map = {
        "max_tool_calls_exceeded": "tool budget exceeded",
        "timeout": "request timed out",
        "knowledge_base_empty": "knowledge base returned no data",
        "knowledge_base_unavailable": "knowledge base unavailable",
        "model_empty_response": "model returned empty response",
        "ask_ai_unavailable": "unable to process ask_ai request; credits refunded",
    }
    detail_reason = reason_map.get(exc.reason, exc.reason)
    if exc.reason in {"knowledge_base_empty", "knowledge_base_unavailable"}:
        logger.error("knowledge_base_unavailable profile_id={} mode={}", deps.profile_id, mode.value)
        return JSONResponse(
            status_code=503,
            content={
                "detail": "knowledge base unavailable",
                "reason": exc.reason,
            },
        )
    if mode in {CoachMode.program, CoachMode.subscription}:
        final_result = deps.final_result
        if final_result is None:
            for cache_key in ("tool_save_program", "tool_create_subscription"):
                cached_value = deps.tool_cache.get(cache_key)  # pyrefly: ignore[no-matching-overload]
                if cached_value is not None:
                    final_result = cast(Program | Subscription, cached_value)
                    break
        if final_result is not None:
            return final_result
    return JSONResponse(
        status_code=408,
        content={
            "detail": detail_reason or "AI coach aborted request",
            "reason": exc.reason,
        },
    )


def _final_log(
    mode: CoachMode,
    result: Any,
    deps: AgentDeps,
    started: float,
    profile_id: int,
    request_id: str | None,
) -> None:
    latency_ms = int((monotonic() - started) * 1000)
    model_name = CoachAgent._completion_model_name or settings.AGENT_MODEL
    final_kb_used = bool(deps.kb_used)
    answer_len = 0
    origin = "llm"
    sources_for_log: list[str] = []
    if isinstance(result, QAResponse):
        answer_len = len(result.answer or "")
        sources_for_log = [src.strip() for src in result.sources if isinstance(src, str) and src.strip()]
        if not sources_for_log:
            sources_for_log = ["general_knowledge"]
        final_kb_used = any(src != "general_knowledge" for src in sources_for_log)
        if deps.fallback_used and final_kb_used:
            origin = "kb_fallback"
    elif isinstance(result, JSONResponse):
        origin = "error"
    elif isinstance(result, list):
        origin = "structured"
        answer_len = sum(len(str(item)) for item in result if isinstance(item, str))
    elif result is None:
        origin = "error"
    else:
        answer_attr = getattr(result, "answer", None)
        if isinstance(answer_attr, str):
            answer_len = len(answer_attr)
            if deps.fallback_used and final_kb_used:
                origin = "kb_fallback"
        else:
            origin = "structured"
    if not sources_for_log:
        sources_for_log = ["general_knowledge"] if not final_kb_used else ["knowledge_base"]
    if mode != CoachMode.ask_ai:
        sources_for_log = []
    sources_count = len(sources_for_log)
    if _LOG_PAYLOADS and sources_for_log:
        sources_label = ",".join(sources_for_log)
        if len(sources_label) > 300:
            sources_label = sources_label[:297] + "..."
        logger.debug(
            f"ask.out.sources request_id={request_id} profile_id={profile_id} mode={mode.value} sources={sources_label}"
        )
    logger.info(
        f"ask.out request_id={request_id} profile_id={profile_id} mode={mode.value} model={model_name} "
        f"from={origin} answer_len={answer_len} kb_used={str(final_kb_used).lower()} "
        f"sources_count={sources_count} latency_ms={latency_ms}"
    )


async def _prepare_chat_kb(
    mode: CoachMode,
    prompt: str | None,
    profile_id: int,
    language: str,
) -> KnowledgeBase | None:
    if mode != CoachMode.ask_ai or not prompt:
        return None
    return get_knowledge_base()


async def handle_coach_request(
    data: AICoachRequest,
    *,
    allowed_modes: set[CoachMode] | None = None,
) -> Program | Subscription | QAResponse | DietPlan | list[str] | None | JSONResponse:
    mode = data.mode if isinstance(data.mode, CoachMode) else CoachMode(data.mode)
    _allowed_mode_or_422(mode, allowed_modes or set())
    rid = str(uuid4())
    started = monotonic()
    result: Any | None = None
    inflight_future: asyncio.Future | None = None
    inflight_owner = False
    inflight_error: Exception | None = None
    attachments, attachments_bytes = _normalize_attachments(data.attachments)
    max_attachment_bytes = int(settings.AI_QA_IMAGE_MAX_BYTES)
    if attachments_bytes > max_attachment_bytes > 0:
        logger.warning(
            "ask.attachments_rejected profile_id={} request_id={} bytes={} limit={}",
            data.profile_id,
            data.request_id,
            attachments_bytes,
            max_attachment_bytes,
        )
        raise HTTPException(status_code=413, detail="Attachments too large")
    dedupe_key = _compute_dedupe_key(data.prompt, data.profile_id, mode, attachments=attachments)

    if dedupe_key and dedupe_key in dedupe_cache:
        logger.debug(f"ask.deduped rid={rid} key={dedupe_key}")
        return dedupe_cache[dedupe_key]

    request_id = str(data.request_id or "")
    if request_id and mode in {CoachMode.program, CoachMode.subscription, CoachMode.update, CoachMode.diet}:
        cached = request_cache.get(request_id)
        if cached is not None:
            logger.info(f"ask.request_cache_hit request_id={request_id} profile_id={data.profile_id} mode={mode.value}")
            return cached
        async with _inflight_lock:
            inflight_future = _inflight_requests.get(request_id)
            if inflight_future is None:
                inflight_future = asyncio.get_running_loop().create_future()
                _inflight_requests[request_id] = inflight_future
                inflight_owner = True
            else:
                inflight_owner = False
        if inflight_future is not None and not inflight_owner:
            logger.info(f"ask.request_deduped request_id={request_id} profile_id={data.profile_id} mode={mode.value}")
            return await inflight_future

    with logger.contextualize(rid=rid):
        logger.debug(
            f"/ask received rid={rid} request_id={data.request_id} profile_id={data.profile_id} mode={mode.value}"
        )

        if mode == CoachMode.update and data.plan_type is None:
            raise HTTPException(status_code=422, detail="plan_type required for update mode")

        period = (
            data.period
            if isinstance(data.period, SubscriptionPeriod)
            else SubscriptionPeriod(data.period or SubscriptionPeriod.one_month.value)
        )

        profile_started = monotonic()
        profile = await _fetch_profile(data.profile_id)
        _log_stage_duration(
            "profile_fetch",
            profile_started,
            request_id=data.request_id,
            profile_id=data.profile_id,
            mode=mode,
            found=str(profile is not None).lower(),
        )
        language = _resolve_language(data.language, profile)
        split_number = data.split_number or DEFAULT_SPLIT_NUMBER
        if mode in {CoachMode.program, CoachMode.subscription}:
            logger.info(
                f"ask.inputs request_id={data.request_id} profile_id={data.profile_id} mode={mode.value} "
                f"split_number={split_number}"
            )

        if attachments:
            kb = round(attachments_bytes / 1024, 1)
            mime_summary = ",".join(sorted({item["mime"] for item in attachments}))
            logger.debug(
                "ask.attachments_received profile_id={} request_id={} count={} total_kb={} mimes={}",
                data.profile_id,
                data.request_id,
                len(attachments),
                kb,
                mime_summary or "-",
            )

        model_name = CoachAgent._completion_model_name or settings.AGENT_MODEL
        kb_enabled = settings.AI_COACH_KB_ENABLED
        logger.info(
            f"ask.in request_id={data.request_id} profile_id={data.profile_id} mode={mode.value} "
            f"model={model_name} kb_enabled={str(kb_enabled).lower()}"
        )

        deps = AgentDeps(
            profile_id=data.profile_id,
            locale=language,
            allow_save=mode != CoachMode.ask_ai,
            client_name=getattr(profile, "name", None),
            request_rid=rid,
        )
        if not settings.AI_COACH_KB_ENABLED:
            deps.disabled_tools.add("tool_search_knowledge")
        include_plans = mode in {CoachMode.program, CoachMode.subscription, CoachMode.update}
        profile_context = await _build_profile_context(profile, include_plans=include_plans)
        ctx: AskCtx = _build_context(
            data,
            language,
            period,
            split_number,
            deps,
            attachments,
            profile_context=profile_context,
        )
        logger.debug(f"/ask ctx.language={language} deps.locale={deps.locale} mode={mode.value}")

        kb_started = monotonic()
        if settings.AI_COACH_KB_ENABLED:
            kb_for_chat = await _prepare_chat_kb(mode, data.prompt, data.profile_id, language)
        else:
            kb_for_chat = None
            logger.info(
                "kb_disabled request_id={} profile_id={} mode={}",
                data.request_id,
                data.profile_id,
                mode.value,
            )
        _log_stage_duration(
            "kb_prepare",
            kb_started,
            request_id=data.request_id,
            profile_id=data.profile_id,
            mode=mode,
            enabled=str(kb_for_chat is not None).lower(),
        )

        try:
            coach_agent_action: CoachAction = DISPATCH[mode]
        except KeyError as exc:
            logger.exception(f"/ask unsupported mode={mode.value}")
            raise HTTPException(status_code=422, detail="Unsupported mode") from exc

        try:
            logger.info(
                f"ask.stage stage=agent_run_start request_id={data.request_id} "
                f"profile_id={data.profile_id} mode={mode.value}"
            )
            agent_started = monotonic()
            result = await coach_agent_action(ctx)
            _log_stage_duration(
                "agent_run",
                agent_started,
                request_id=data.request_id,
                profile_id=data.profile_id,
                mode=mode,
                tools_used=deps.tool_calls,
            )
            if deps.final_result is not None and not isinstance(result, JSONResponse):
                result = deps.final_result

            if mode == CoachMode.ask_ai:
                answer = getattr(result, "answer", None)
                sources: list[str] = []
                if isinstance(result, QAResponse):
                    sources = [src.strip() for src in result.sources if isinstance(src, str) and src.strip()]
                else:
                    raw_sources = getattr(result, "sources", None)
                    if isinstance(raw_sources, list):
                        sources.extend(str(item).strip() for item in raw_sources if str(item).strip())
                _log_sources(rid, data.request_id, data.profile_id, deps, cast(QAResponse, result), sources)
                if isinstance(answer, str):
                    kb = kb_for_chat or get_knowledge_base()
                    await kb.maybe_summarize_session(data.profile_id, language=language)
                if settings.AI_COACH_KB_ENABLED and not deps.kb_used:
                    logger.error(
                        "knowledge_base_unavailable request_id={} profile_id={} mode={}",
                        data.request_id,
                        data.profile_id,
                        mode.value,
                    )
                    raise HTTPException(status_code=503, detail="Knowledge base unavailable")

                response_data: dict[str, Any] = {"answer": answer}
                blocks = getattr(result, "blocks", None)
                if isinstance(blocks, list) and blocks:
                    response_data["blocks"] = [
                        block.model_dump(mode="json") if hasattr(block, "model_dump") else dict(block)
                        for block in blocks
                        if block
                    ]
                if sources:
                    response_data["sources"] = sources

                if dedupe_key:
                    dedupe_cache[dedupe_key] = JSONResponse(content=response_data)

                return JSONResponse(content=response_data)

            if mode == CoachMode.diet and settings.AI_COACH_KB_ENABLED and not deps.kb_used:
                logger.error(
                    "knowledge_base_unavailable request_id={} profile_id={} mode={}",
                    data.request_id,
                    data.profile_id,
                    mode.value,
                )
                raise HTTPException(status_code=503, detail="Knowledge base unavailable")

            if dedupe_key and result and not isinstance(result, JSONResponse):
                dedupe_cache[dedupe_key] = result
            if request_id and mode in {CoachMode.program, CoachMode.subscription, CoachMode.update, CoachMode.diet}:
                if result is not None and not isinstance(result, JSONResponse):
                    request_cache[request_id] = result

            return result

        except AgentExecutionAborted as exc:
            logger.warning(
                f"/ask agent aborted rid={rid} request_id={data.request_id} profile_id={data.profile_id} "
                f"mode={mode.value} reason={exc.reason} detail={exc.reason} steps_used={deps.tool_calls}"
            )
            result = await _handle_abort(exc, deps, mode)
            return result
        except ModelHTTPError as exc:
            inflight_error = exc
            status_code = int(getattr(exc, "status_code", 503) or 503)
            if 400 <= status_code < 500:
                logger.error(
                    f"/ask agent failed rid={rid} request_id={data.request_id} "
                    f"profile_id={data.profile_id} mode={mode.value} status={status_code} detail={exc}"
                )
                raise HTTPException(status_code=400, detail="ai_coach_invalid_request") from exc
            logger.exception(f"/ask agent failed rid={rid}: {exc}")
            raise HTTPException(status_code=503, detail="Service unavailable") from exc
        except ValidationError as exc:
            inflight_error = exc
            logger.exception(f"/ask agent validation error rid={rid}: {exc}")
            raise HTTPException(status_code=422, detail="Invalid response") from exc
        except Exception as exc:
            inflight_error = exc
            logger.exception(f"/ask agent failed rid={rid}: {exc}")
            raise HTTPException(status_code=503, detail="Service unavailable") from exc
        finally:
            _final_log(mode, result, deps, started, data.profile_id, data.request_id)
            if inflight_owner and request_id and inflight_future is not None:
                if not inflight_future.done():
                    if inflight_error is not None:
                        inflight_future.set_exception(inflight_error)
                    else:
                        inflight_future.set_result(result)
                _inflight_requests.pop(request_id, None)
