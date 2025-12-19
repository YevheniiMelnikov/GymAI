from base64 import b64decode
from binascii import Error as BinasciiError
from hashlib import sha1
import os
from time import monotonic
from typing import Any, cast, Iterable
from uuid import uuid4

from cachetools import TTLCache
from fastapi import HTTPException  # pyrefly: ignore[import-error]
from fastapi.responses import JSONResponse  # pyrefly: ignore[import-error]
from loguru import logger  # pyrefly: ignore[import-error]
from pydantic import ValidationError  # pyrefly: ignore[import-error]

from ai_coach.agent import AgentDeps, CoachAgent
from ai_coach.agent.knowledge.knowledge_base import KnowledgeBase
from ai_coach.agent.knowledge.schemas import ProjectionStatus
from ai_coach.agent.utils import get_knowledge_base
from ai_coach.exceptions import AgentExecutionAborted
from ai_coach.schemas import AICoachRequest
from ai_coach.types import AskCtx, CoachMode, MessageRole
from ai_coach.coach_actions import DISPATCH, CoachAction
from config.app_settings import settings
from core.enums import SubscriptionPeriod
from core.schemas import Program, Profile, QAResponse, Subscription
from core.services import APIService

DEFAULT_WORKOUT_DAYS: tuple[str, ...] = ("Day 1", "Day 2", "Day 3", "Day 4")
dedupe_cache = TTLCache(maxsize=2048, ttl=15)
_ALLOWED_ATTACHMENT_MIME = {"image/jpeg", "image/png", "image/webp"}
_LOG_PAYLOADS = os.getenv("AI_COACH_LOG_PAYLOADS", "").strip() == "1"


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
    except Exception:  # pragma: no cover - profile service may be unavailable
        return None


def _build_context(
    data,
    language: str,
    period: SubscriptionPeriod,
    workout_days: list[str],
    deps: AgentDeps,
    attachments: list[dict[str, str]],
) -> AskCtx:
    return {
        "prompt": data.prompt,
        "profile_id": data.profile_id,
        "attachments": attachments,
        "period": period.value,
        "workout_days": workout_days,
        "expected_workout": data.expected_workout or "",
        "feedback": data.feedback or "",
        "wishes": data.wishes or "",
        "language": language,
        "workout_location": data.workout_location,
        "plan_type": data.plan_type,
        "instructions": data.instructions,
        "deps": deps,
    }


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


async def _handle_abort(
    exc: AgentExecutionAborted,
    deps: AgentDeps,
    mode: CoachMode,
) -> Program | Subscription | JSONResponse:
    reason_map = {
        "max_tool_calls_exceeded": "tool budget exceeded",
        "timeout": "request timed out",
        "knowledge_base_empty": "knowledge base returned no data",
        "model_empty_response": "model returned empty response",
        "ask_ai_unavailable": "unable to process ask_ai request; credits refunded",
    }
    detail_reason = reason_map.get(exc.reason, exc.reason)
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


async def _prepare_chat_kb(mode: CoachMode, prompt: str | None, profile_id: int) -> KnowledgeBase | None:
    if mode != CoachMode.ask_ai or not prompt:
        return None
    kb_for_chat = get_knowledge_base()
    await _ingest_chat_prompt(kb_for_chat, profile_id, prompt)
    return kb_for_chat


async def handle_coach_request(
    data: AICoachRequest,
    *,
    allowed_modes: set[CoachMode] | None = None,
) -> Program | Subscription | QAResponse | list[str] | None | JSONResponse:
    mode = data.mode if isinstance(data.mode, CoachMode) else CoachMode(data.mode)
    _allowed_mode_or_422(mode, allowed_modes or set())
    rid = str(uuid4())
    started = monotonic()
    result: Any | None = None
    attachments, attachments_bytes = _normalize_attachments(data.attachments)
    dedupe_key = _compute_dedupe_key(data.prompt, data.profile_id, mode, attachments=attachments)

    if dedupe_key and dedupe_key in dedupe_cache:
        logger.debug(f"ask.deduped rid={rid} key={dedupe_key}")
        return dedupe_cache[dedupe_key]

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

        profile = await _fetch_profile(data.profile_id)
        language = _resolve_language(data.language, profile)
        workout_days: list[str] = data.workout_days or list(DEFAULT_WORKOUT_DAYS)

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
        kb_enabled = mode == CoachMode.ask_ai
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
        ctx: AskCtx = _build_context(data, language, period, workout_days, deps, attachments)
        logger.debug(f"/ask ctx.language={language} deps.locale={deps.locale} mode={mode.value}")

        kb_for_chat = await _prepare_chat_kb(mode, data.prompt, data.profile_id)

        try:
            coach_agent_action: CoachAction = DISPATCH[mode]
        except KeyError as exc:
            logger.exception(f"/ask unsupported mode={mode.value}")
            raise HTTPException(status_code=422, detail="Unsupported mode") from exc

        try:
            result = await coach_agent_action(ctx)

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
                    await kb.save_client_message(data.prompt or "", profile_id=data.profile_id)
                    await kb.save_ai_message(answer, profile_id=data.profile_id)

                response_data: dict[str, Any] = {"answer": answer}
                if sources:
                    response_data["sources"] = sources

                if dedupe_key:
                    dedupe_cache[dedupe_key] = JSONResponse(content=response_data)

                return JSONResponse(content=response_data)

            if dedupe_key and result and not isinstance(result, JSONResponse):
                dedupe_cache[dedupe_key] = result

            return result

        except AgentExecutionAborted as exc:
            logger.warning(
                f"/ask agent aborted rid={rid} request_id={data.request_id} profile_id={data.profile_id} "
                f"mode={mode.value} reason={exc.reason} detail={exc.reason} steps_used={deps.tool_calls}"
            )
            result = await _handle_abort(exc, deps, mode)
            return result
        except ValidationError as exc:
            logger.exception(f"/ask agent validation error rid={rid}: {exc}")
            raise HTTPException(status_code=422, detail="Invalid response") from exc
        except Exception as exc:  # pragma: no cover - log unexpected errors
            logger.exception(f"/ask agent failed rid={rid}: {exc}")
            raise HTTPException(status_code=503, detail="Service unavailable") from exc
        finally:
            _final_log(mode, result, deps, started, data.profile_id, data.request_id)
