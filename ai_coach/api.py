import hmac
import sys
import time
from fastapi import Depends, HTTPException, Request  # pyrefly: ignore[import-error]
from fastapi.responses import JSONResponse  # pyrefly: ignore[import-error]
from fastapi.security import HTTPBasicCredentials  # pyrefly: ignore[import-error]
from loguru import logger  # pyrefly: ignore[import-error]
from pydantic import ValidationError  # pyrefly: ignore[import-error]
from typing import Any, Awaitable, Callable, cast
from time import monotonic
from uuid import uuid4
from hashlib import sha1
from cachetools import TTLCache
import os

from ai_coach.agent.knowledge.knowledge_base import KnowledgeBase
from ai_coach.agent.knowledge.schemas import ProjectionStatus
from ai_coach.agent import AgentDeps, CoachAgent  # pyrefly: ignore[missing-module-attribute]
from ai_coach.agent.utils import get_knowledge_base
from ai_coach.exceptions import AgentExecutionAborted
from core.exceptions import UserServiceError
from core.internal_http import resolve_hmac_credentials
from core.utils.redis_lock import get_redis_client
from core.services import APIService
from ai_coach.application import app, security
from ai_coach.schemas import AICoachRequest
from ai_coach.types import AskCtx, CoachMode, MessageRole
from core.enums import WorkoutPlanType, SubscriptionPeriod
from config.app_settings import settings
import config.app_settings as app_settings
from core.schemas import Profile, Program, Subscription
from core.schemas import QAResponse

CoachAction = Callable[[AskCtx], Awaitable[Program | Subscription | QAResponse | list[str] | None]]

DEFAULT_WORKOUT_DAYS: tuple[str, ...] = ("Пн", "Ср", "Пт", "Сб")

dedupe_cache = TTLCache(maxsize=2048, ttl=15)


def _get_refresh_settings() -> Any:
    module = sys.modules.get("config.app_settings")
    if module is not None and hasattr(module, "settings"):
        return getattr(module, "settings")
    return getattr(app_settings, "settings", settings)


def _validate_refresh_credentials(credentials: HTTPBasicCredentials) -> None:
    cfg = _get_refresh_settings()
    username = str(credentials.username or "")
    password = str(credentials.password or "")
    expected_user = str(getattr(cfg, "AI_COACH_REFRESH_USER", "") or "")
    expected_pass = str(getattr(cfg, "AI_COACH_REFRESH_PASSWORD", "") or "")
    if username != expected_user or password != expected_pass:
        raise HTTPException(status_code=401, detail="Unauthorized")


async def _require_hmac(request: Request) -> None:
    env_mode = str(getattr(settings, "ENVIRONMENT", "development")).lower()
    creds = resolve_hmac_credentials(settings, prefer_ai_coach=True)
    if creds is None:
        if env_mode != "production":
            if not getattr(_require_hmac, "_warned_missing", False):
                logger.warning("HMAC credentials missing; skipping validation in non-production mode")
                setattr(_require_hmac, "_warned_missing", True)
            return
        raise HTTPException(status_code=503, detail="AI coach HMAC is not configured")
    expected_key_id, secret_key = creds
    key_id = request.headers.get("X-Key-Id")
    ts_header = request.headers.get("X-TS")
    sig_header = request.headers.get("X-Sig")
    if not all((key_id, ts_header, sig_header)):
        raise HTTPException(status_code=403, detail="Missing signature headers")
    if key_id != expected_key_id:
        raise HTTPException(status_code=403, detail="Unknown key ID")
    try:
        ts = int(ts_header) if ts_header is not None else 0
    except ValueError:
        raise HTTPException(status_code=403, detail="Invalid timestamp format")
    if abs(time.time() - ts) > 300:
        raise HTTPException(status_code=403, detail="Stale signature")
    body = await request.body()
    message = str(ts).encode() + b"." + body
    expected_sig = hmac.new(secret_key.encode(), message, "sha256").hexdigest()
    if not hmac.compare_digest(expected_sig, sig_header or ""):
        raise HTTPException(status_code=403, detail="Signature mismatch")

    # Rate limit per key
    rate_limit = int(getattr(settings, "AI_COACH_RATE_LIMIT", 0) or 0)
    period = int(getattr(settings, "AI_COACH_RATE_PERIOD", 0) or 0)
    if rate_limit > 0 and period > 0:
        window = int(time.time() // period)
        key = f"rl:ai:{expected_key_id}:{window}"
        try:
            client = get_redis_client()
            count = await client.incr(key)
            if count == 1:
                await client.expire(key, period)
            if count > rate_limit:
                raise HTTPException(status_code=429, detail="Rate limit exceeded")
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "ai_coach_rate_limit_error key_id={} window={} limit={} detail={}",
                expected_key_id,
                window,
                rate_limit,
                exc,
            )


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


DISPATCH: dict[CoachMode, CoachAction] = {
    CoachMode.program: lambda ctx: CoachAgent.generate_workout_plan(
        ctx.get("prompt"),
        deps=ctx["deps"],
        workout_location=ctx.get("workout_location"),
        wishes=ctx["wishes"],
        instructions=ctx.get("instructions"),
        output_type=Program,
    ),
    CoachMode.subscription: lambda ctx: CoachAgent.generate_workout_plan(
        ctx.get("prompt"),
        deps=ctx["deps"],
        workout_location=ctx.get("workout_location"),
        period=ctx["period"],
        workout_days=ctx["workout_days"],
        wishes=ctx["wishes"],
        instructions=ctx.get("instructions"),
        output_type=Subscription,
    ),
    CoachMode.update: lambda ctx: CoachAgent.update_workout_plan(
        ctx.get("prompt"),
        expected_workout=ctx["expected_workout"],
        feedback=ctx["feedback"],
        workout_location=ctx.get("workout_location"),
        deps=ctx["deps"],
        output_type=Program if ctx["plan_type"] == WorkoutPlanType.PROGRAM else Subscription,
        instructions=ctx.get("instructions"),
    ),
    CoachMode.ask_ai: lambda ctx: CoachAgent.answer_question(ctx["prompt"] or "", deps=ctx["deps"]),
}


@app.get("/health/")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/kb")
async def health_kb() -> dict[str, Any]:
    kb = get_knowledge_base()
    storage_path = settings.COGNEE_STORAGE_PATH
    storage_ok = os.path.exists(storage_path) and os.access(storage_path, os.W_OK)
    user = getattr(kb, "_user", None)
    if user is None:
        user = await kb.dataset_service.get_cognee_user()
    try:
        projected, projection_reason = await kb.projection_service.probe(kb.GLOBAL_DATASET, user)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"kb_health.probe_failed detail={exc}")
        projected = False
        projection_reason = "fatal_error"
    dataset_registry_size = kb.dataset_service.get_dataset_alias_count()
    last_rebuild_info = kb.get_last_rebuild_result()
    return {
        "status": "ok" if storage_ok and projected else "error",
        "storage_access_ok": storage_ok,
        "projected": projected,
        "projection_reason": projection_reason,
        "dataset_registry_size": dataset_registry_size,
        "last_rebuild_info": last_rebuild_info,
    }


@app.get("/internal/debug/ping")
async def internal_ping(_: None = Depends(_require_hmac)) -> dict[str, bool]:
    return {"ok": True}


@app.get("/internal/debug/llm_probe")
async def debug_llm_probe(
    credentials: HTTPBasicCredentials = Depends(security),
    _: None = Depends(_require_hmac),
) -> dict[str, Any]:
    _validate_refresh_credentials(credentials)
    try:
        return await CoachAgent.llm_probe()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"/internal/debug/llm_probe failed: {exc}")
        raise HTTPException(status_code=503, detail="LLM probe failed") from exc


@app.get("/internal/debug/llm_echo")
async def debug_llm_echo(
    credentials: HTTPBasicCredentials = Depends(security),
    _: None = Depends(_require_hmac),
) -> dict[str, str]:
    _validate_refresh_credentials(credentials)
    client, model_name = CoachAgent._get_completion_client()
    CoachAgent._ensure_llm_logging(client, model_name)
    response = await CoachAgent._complete_with_retries(
        client,
        "Відповідай одним словом: OK",
        "Ехо-тест",
        [],
        profile_id=0,
        max_tokens=32,
        model=model_name,
    )
    if response is None or not response.answer.strip():
        raise HTTPException(status_code=503, detail="LLM echo failed")
    return {"answer": response.answer.strip()}


@app.get("/internal/kb/dump")
async def kb_dump(
    credentials: HTTPBasicCredentials = Depends(security),
    _: None = Depends(_require_hmac),
) -> dict[str, Any]:
    _validate_refresh_credentials(credentials)
    kb = get_knowledge_base()
    ds = kb.dataset_service
    user = getattr(kb, "_user", None) or await ds.get_cognee_user()
    global_alias = ds.alias_for_dataset("kb_global")
    global_ident = ds.get_registered_identifier("kb_global")
    global_effective = global_ident or global_alias
    global_counts = await ds.get_counts(global_effective, user=user)

    chat_alias = ds.alias_for_dataset(ds.chat_dataset_name(1))
    chat_ident = ds.get_registered_identifier(chat_alias)
    chat_effective = chat_ident or chat_alias
    chat_counts = await ds.get_counts(chat_effective, user=user)

    projected_global = kb.get_projection_health(global_alias)
    projected_chat = kb.get_projection_health(chat_alias)
    return {
        "kb_global": {
            "alias": global_alias,
            "identifier": global_ident,
            "effective": global_effective,
            "counts": global_counts,
        },
        "kb_chat_1": {
            "alias": chat_alias,
            "identifier": chat_ident,
            "effective": chat_effective,
            "counts": chat_counts,
        },
        "ident_map": ds.dump_identifier_map(),
        "projection": {
            "kb_global": projected_global,
            "kb_chat_1": projected_chat,
        },
        "last_reingest": kb.get_last_rebuild_result(),
    }


@app.get("/internal/kb/audit")
async def kb_audit(
    datasets: str,
    credentials: HTTPBasicCredentials = Depends(security),
    _: None = Depends(_require_hmac),
) -> dict[str, Any]:
    _validate_refresh_credentials(credentials)
    kb = get_knowledge_base()
    ds = kb.dataset_service
    user = getattr(kb, "_user", None) or await ds.get_cognee_user()
    requested = [item.strip() for item in (datasets or "").split(",") if item.strip()]
    resolved: list[dict[str, Any]] = []
    for raw in requested:
        canonical = ds.resolve_dataset_alias(raw)
        identifier = ds.get_registered_identifier(canonical)
        effective = identifier or canonical
        counts = await ds.get_counts(effective, user)
        resolved.append(
            {
                "raw": raw,
                "canonical": canonical,
                "identifier": identifier,
                "effective": effective,
                "counts": counts,
            }
        )
    return {"requested": requested, "resolved": resolved}


@app.post("/ask/", response_model=Program | Subscription | QAResponse | list[str] | None)
async def ask(
    data: AICoachRequest,
    request: Request,
    _: None = Depends(_require_hmac),
) -> Program | Subscription | QAResponse | list[str] | None | JSONResponse:
    mode = data.mode if isinstance(data.mode, CoachMode) else CoachMode(data.mode)
    rid = str(uuid4())
    started = monotonic()
    result: Any | None = None
    default_model = settings.AGENT_MODEL
    dedupe_key: str | None = None

    if data.prompt:
        dedupe_key = sha1(f"{data.profile_id}:{data.prompt.strip()}:{mode.value}".encode()).hexdigest()
        if dedupe_key in dedupe_cache:
            logger.info(f"ask.deduped rid={rid} key={dedupe_key}")
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

        workout_days: list[str] = data.workout_days or list(DEFAULT_WORKOUT_DAYS)

        profile: Profile | None
        try:
            profile = await APIService.profile.get_profile(data.profile_id)
        except Exception:  # pragma: no cover - missing profile service
            profile = None

        request_language: str | None = None
        if data.language:
            request_language = _to_language_code(data.language, settings.DEFAULT_LANG)

        profile_language: str | None = None
        if profile is not None:
            profile_language_raw = getattr(profile, "language", None)
            if profile_language_raw is not None:
                profile_language = _to_language_code(profile_language_raw, settings.DEFAULT_LANG)

        language: str = request_language or profile_language or settings.DEFAULT_LANG
        logger.debug(f"ask.in profile_id={data.profile_id} mode={mode.value} language={language}")

        ctx: AskCtx = {
            "prompt": data.prompt,
            "profile_id": data.profile_id,
            "period": period.value,
            "workout_days": workout_days,
            "expected_workout": data.expected_workout or "",
            "feedback": data.feedback or "",
            "wishes": data.wishes or "",
            "language": language,
            "workout_location": data.workout_location,
            "plan_type": data.plan_type,
            "instructions": data.instructions,
        }

        client_name = getattr(profile, "name", None)

        deps = AgentDeps(
            profile_id=data.profile_id,
            locale=language,
            allow_save=mode != CoachMode.ask_ai,
            client_name=client_name,
            request_rid=rid,
        )
        ctx["deps"] = deps

        logger.debug(f"/ask ctx.language={language} deps.locale={deps.locale} mode={mode.value}")

        kb_for_chat: KnowledgeBase | None = None

        try:
            if mode == CoachMode.ask_ai and data.prompt:
                kb_for_chat = get_knowledge_base()
                kb_chat_dataset = kb_for_chat.chat_dataset_name(data.profile_id)
                await kb_for_chat.add_text(
                    dataset=kb_chat_dataset,
                    text=data.prompt,
                    role=MessageRole.CLIENT,
                    profile_id=data.profile_id,
                )
                question_bytes = len(data.prompt.encode())
                logger.debug(
                    f"ask.ingest_chat profile_id={data.profile_id} dataset={kb_chat_dataset} bytes={question_bytes}"
                )
                chat_user = getattr(kb_for_chat, "_user", None)
                if chat_user is None:
                    chat_user = await kb_for_chat.dataset_service.get_cognee_user()
                try:
                    wait_status = await kb_for_chat.projection_service.wait(
                        kb_chat_dataset,
                        chat_user,
                        timeout=2.0,
                    )
                except Exception as exc:  # noqa: BLE001 - projection best effort
                    logger.debug(f"ask.wait_projection dataset={kb_chat_dataset} timeout=2.0 result=error detail={exc}")
                else:
                    status_label = (
                        "ok" if wait_status in {ProjectionStatus.READY, ProjectionStatus.READY_EMPTY} else "timeout"
                    )
                    logger.debug(f"ask.wait_projection dataset={kb_chat_dataset} timeout=2.0 {status_label}")

            coach_agent_action = DISPATCH[mode]
        except KeyError as e:
            logger.exception(f"/ask unsupported mode={mode.value}")
            raise HTTPException(status_code=422, detail="Unsupported mode") from e

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
                        for item in raw_sources:
                            text = str(item).strip()
                            if text:
                                sources.append(text)
                logger.debug(
                    "/ask agent completed rid={} request_id={} profile_id={} mode={} "
                    "answer_len={} steps_used={} kb_empty={}",
                    rid,
                    data.request_id,
                    data.profile_id,
                    "ask_ai",
                    len(answer) if isinstance(answer, str) else 0,
                    deps.tool_calls,
                    deps.knowledge_base_empty,
                )
                if sources:
                    joined = " | ".join(sources)
                    if len(joined) > 300:
                        joined = joined[:297] + "..."
                    logger.debug(
                        f"/ask agent sources rid={rid} request_id={data.request_id} profile_id={data.profile_id} "
                        f"count={len(sources)} sources={joined}"
                    )
                origin = "llm"
                answer_len = len(answer) if isinstance(answer, str) else 0
                if isinstance(result, QAResponse) and deps.fallback_used:
                    origin = "kb_fallback"
                elif not isinstance(result, QAResponse):
                    origin = "structured"
                logger.info(
                    "api.answer_out rid={} request_id={} profile_id={} len={} from={}",
                    rid,
                    data.request_id,
                    data.profile_id,
                    answer_len,
                    origin,
                )
                if isinstance(answer, str):
                    kb = kb_for_chat or get_knowledge_base()
                    await kb.save_client_message(data.prompt or "", profile_id=data.profile_id)
                    await kb.save_ai_message(answer, profile_id=data.profile_id)

                response_data = {"answer": answer}
                if sources:
                    response_data["sources"] = sources

                if dedupe_key:
                    dedupe_cache[dedupe_key] = JSONResponse(content=response_data)

                return JSONResponse(content=response_data)
            else:
                logger.debug(
                    "/ask agent completed rid={} request_id={} profile_id={} mode={} steps_used={} kb_empty={}",
                    rid,
                    data.request_id,
                    data.profile_id,
                    mode.value,
                    deps.tool_calls,
                    deps.knowledge_base_empty,
                )

            if dedupe_key and result and not isinstance(result, JSONResponse):
                dedupe_cache[dedupe_key] = result

            return result

        except AgentExecutionAborted as exc:
            reason_map = {
                "max_tool_calls_exceeded": "tool budget exceeded",
                "timeout": "request timed out",
                "knowledge_base_empty": "knowledge base returned no data",
                "model_empty_response": "model returned empty response",
                "ask_ai_unavailable": "unable to process ask_ai request; credits refunded",
            }
            detail_reason = reason_map.get(exc.reason, exc.reason)
            logger.info(
                f"/ask agent aborted rid={rid} request_id={data.request_id} profile_id={data.profile_id} "
                f"mode={mode.value} reason={exc.reason} detail={detail_reason} steps_used={deps.tool_calls}"
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
                    logger.info(
                        f"/ask agent returning saved result rid={rid} request_id={data.request_id} "
                        f"profile_id={data.profile_id} mode={mode.value} reason={exc.reason}"
                    )
                    result = final_result
                    return final_result
            result = JSONResponse(
                status_code=408,
                content={
                    "detail": detail_reason or "AI coach aborted request",
                    "reason": exc.reason,
                },
            )
            return result
        except ValidationError as e:
            logger.exception(f"/ask agent validation error rid={rid}: {e}")
            raise HTTPException(status_code=422, detail="Invalid response") from e
        except Exception as e:  # pragma: no cover - log unexpected errors
            logger.exception(f"/ask agent failed rid={rid}: {e}")
            raise HTTPException(status_code=503, detail="Service unavailable") from e
        finally:
            latency_ms = int((monotonic() - started) * 1000)
            model_name = CoachAgent._completion_model_name or default_model
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
            sources_label = ",".join(sources_for_log)
            if len(sources_label) > 300:
                sources_label = sources_label[:297] + "..."
            logger.info(
                f"ask.out rid={rid} profile_id={data.profile_id} mode={mode.value} model={model_name} "
                f"from={origin} answer_len={answer_len} kb_used={str(final_kb_used).lower()} "
                f"sources={sources_label} latency_ms={latency_ms}"
            )


@app.post("/knowledge/refresh/")
async def refresh_knowledge(
    _: None = Depends(_require_hmac),
) -> dict[str, str]:
    try:
        kb = get_knowledge_base()
        await kb.refresh()
    except Exception as e:  # pragma: no cover - log unexpected errors
        logger.exception(f"Knowledge refresh failed: {e}")
        raise HTTPException(status_code=503, detail="Refresh failed")
    return {"status": "ok"}


async def _execute_prune() -> dict[str, str]:
    try:
        kb = get_knowledge_base()
        await kb.prune()
    except UserServiceError as exc:
        logger.error(f"Knowledge prune failed: {exc}")
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"Knowledge prune failed unexpectedly: {exc}")
        raise HTTPException(status_code=503, detail="Cognee prune failed") from exc

    return {"status": "ok"}


@app.post("/internal/knowledge/prune/")
async def prune_knowledge_base_internal(_: None = Depends(_require_hmac)) -> dict[str, str]:
    return await _execute_prune()


@app.post("/knowledge/prune/")
async def prune_knowledge_base(_: None = Depends(_require_hmac)):
    return await _execute_prune()
