from fastapi import Depends, HTTPException, Request  # pyrefly: ignore[import-error]
from fastapi.responses import JSONResponse  # pyrefly: ignore[import-error]
from fastapi.security import HTTPBasicCredentials  # pyrefly: ignore[import-error]
from loguru import logger  # pyrefly: ignore[import-error]
from pydantic import ValidationError  # pyrefly: ignore[import-error]
from typing import Any, Awaitable, Callable, cast

from ai_coach.agent.knowledge.knowledge_base import KnowledgeBase
from ai_coach.agent import AgentDeps, CoachAgent  # pyrefly: ignore[missing-module-attribute]
from ai_coach.exceptions import AgentExecutionAborted
from core.exceptions import UserServiceError
from core.services import APIService
from ai_coach.application import app, security
from ai_coach.schemas import AICoachRequest
from ai_coach.types import AskCtx, CoachMode
from core.enums import WorkoutPlanType, SubscriptionPeriod
from config.app_settings import settings
from core.schemas import Client, Profile, Program, Subscription
from core.schemas import QAResponse

CoachAction = Callable[[AskCtx], Awaitable[Program | Subscription | QAResponse | list[str] | None]]

DEFAULT_WORKOUT_DAYS: tuple[str, ...] = ("Пн", "Ср", "Пт", "Сб")


def _validate_refresh_credentials(credentials: HTTPBasicCredentials) -> None:
    if (
        credentials.username != settings.AI_COACH_REFRESH_USER
        or credentials.password != settings.AI_COACH_REFRESH_PASSWORD
    ):
        raise HTTPException(status_code=401, detail="Unauthorized")


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
        workout_type=ctx.get("workout_type"),
        wishes=ctx["wishes"],
        instructions=ctx.get("instructions"),
        output_type=Program,
    ),
    CoachMode.subscription: lambda ctx: CoachAgent.generate_workout_plan(
        ctx.get("prompt"),
        deps=ctx["deps"],
        workout_type=ctx.get("workout_type"),
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
        workout_type=ctx.get("workout_type"),
        deps=ctx["deps"],
        output_type=Program if ctx["plan_type"] == WorkoutPlanType.PROGRAM else Subscription,
        instructions=ctx.get("instructions"),
    ),
    CoachMode.ask_ai: lambda ctx: CoachAgent.answer_question(ctx["prompt"] or "", deps=ctx["deps"]),
}


@app.get("/health/")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/internal/debug/ping")
async def internal_ping() -> dict[str, bool]:
    return {"ok": True}


@app.post("/ask/", response_model=Program | Subscription | QAResponse | list[str] | None)
async def ask(
    data: AICoachRequest, request: Request
) -> Program | Subscription | QAResponse | list[str] | None | JSONResponse:
    mode = data.mode if isinstance(data.mode, CoachMode) else CoachMode(data.mode)
    logger.debug(f"/ask received request_id={data.request_id} client_id={data.client_id} mode={mode.value}")

    if mode == CoachMode.update and data.plan_type is None:
        raise HTTPException(status_code=422, detail="plan_type required for update mode")

    period = (
        data.period
        if isinstance(data.period, SubscriptionPeriod)
        else SubscriptionPeriod(data.period or SubscriptionPeriod.one_month.value)
    )

    workout_days: list[str] = data.workout_days or list(DEFAULT_WORKOUT_DAYS)

    client: Client | None
    try:
        client = await APIService.profile.get_client(data.client_id)
    except Exception:  # pragma: no cover - missing profile service
        client = None

    profile: Profile | None = None
    if client is not None:
        try:
            profile = await APIService.profile.get_profile(int(client.profile))
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

    ctx: AskCtx = {
        "prompt": data.prompt,
        "client_id": data.client_id,
        "period": period.value,
        "workout_days": workout_days,
        "expected_workout": data.expected_workout or "",
        "feedback": data.feedback or "",
        "wishes": data.wishes or "",
        "language": language,
        "workout_type": data.workout_type,
        "plan_type": data.plan_type,
        "instructions": data.instructions,
    }

    client_name = getattr(client, "name", None)

    deps = AgentDeps(
        client_id=data.client_id,
        locale=language,
        allow_save=mode != CoachMode.ask_ai,
        client_name=client_name,
    )
    ctx["deps"] = deps

    logger.debug(f"/ask ctx.language={language} deps.locale={deps.locale} mode={mode.value}")

    try:
        coach_agent_action = DISPATCH[mode]
    except KeyError as e:
        logger.exception(f"/ask unsupported mode: {mode.value}")
        raise HTTPException(status_code=422, detail="Unsupported mode") from e

    try:
        result: Any = await coach_agent_action(ctx)

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
                f"/ask agent completed request_id={data.request_id}"
                f" client_id={data.client_id} mode=ask_ai"
                f" answer_len={len(answer) if isinstance(answer, str) else 0}"
                f" steps_used={deps.tool_calls} kb_empty={deps.knowledge_base_empty}"
            )
            if sources:
                logger.debug(
                    f"/ask agent sources request_id={data.request_id} client_id={data.client_id} "
                    f"count={len(sources)} sources={' | '.join(sources)}"
                )
            if isinstance(answer, str):
                await KnowledgeBase.save_client_message(data.prompt or "", client_id=data.client_id)
                await KnowledgeBase.save_ai_message(answer, client_id=data.client_id)
        else:
            logger.debug(
                f"/ask agent completed request_id={data.request_id} client_id={data.client_id} mode={mode.value}"
                f" steps_used={deps.tool_calls} kb_empty={deps.knowledge_base_empty}"
            )
        return result

    except AgentExecutionAborted as exc:
        reason_map = {
            "max_tool_calls_exceeded": "tool budget exceeded",
            "timeout": "request timed out",
            "knowledge_base_empty": "knowledge base returned no data",
        }
        detail_reason = reason_map.get(exc.reason, exc.reason)
        logger.info(
            f"/ask agent aborted request_id={data.request_id} client_id={data.client_id} "
            f"mode={mode.value} reason={exc.reason} detail={detail_reason} steps_used={deps.tool_calls}"
        )
        if mode in {CoachMode.program, CoachMode.subscription}:
            final_result = deps.final_result
            if final_result is None:
                for cache_key in ("tool_save_program", "tool_create_subscription"):
                    cached_value = deps.tool_cache.get(cache_key)
                    if cached_value is not None:
                        final_result = cast(Program | Subscription, cached_value)
                        break
            if final_result is not None:
                logger.info(
                    f"/ask agent returning saved result request_id={data.request_id} client_id={data.client_id} "
                    f"mode={mode.value} reason={exc.reason}"
                )
                return final_result
        return JSONResponse(
            status_code=408,
            content={"detail": "AI coach aborted request", "reason": exc.reason},
        )
    except ValidationError as e:
        logger.exception(f"/ask agent validation error: {e}")
        raise HTTPException(status_code=422, detail="Invalid response") from e
    except Exception as e:  # pragma: no cover - log unexpected errors
        logger.exception(f"/ask agent failed: {e}")
        if mode == CoachMode.ask_ai:
            try:
                responses = await KnowledgeBase.search(data.prompt or "", client_id=data.client_id)
                logger.debug(
                    f"/ask completed request_id={data.request_id} client_id={data.client_id} responses={responses}"
                )
                return responses
            except Exception as inner_exc:  # pragma: no cover - log unexpected errors
                logger.exception(f"/ask fallback failed: {inner_exc}")
                raise HTTPException(status_code=503, detail="Service unavailable") from inner_exc
        raise HTTPException(status_code=503, detail="Service unavailable") from e


@app.post("/knowledge/refresh/")
async def refresh_knowledge(credentials: HTTPBasicCredentials = Depends(security)) -> dict[str, str]:
    _validate_refresh_credentials(credentials)

    try:
        await KnowledgeBase.refresh()
    except Exception as e:  # pragma: no cover - log unexpected errors
        logger.exception(f"Knowledge refresh failed: {e}")
        raise HTTPException(status_code=503, detail="Refresh failed")
    return {"status": "ok"}


@app.post("/knowledge/prune/")
async def prune_knowledge_base(credentials: HTTPBasicCredentials = Depends(security)) -> dict[str, str]:
    _validate_refresh_credentials(credentials)

    try:
        await KnowledgeBase.prune()
    except UserServiceError as exc:
        logger.error(f"Knowledge prune failed: {exc}")
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"Knowledge prune failed unexpectedly: {exc}")
        raise HTTPException(status_code=503, detail="Cognee prune failed") from exc

    return {"status": "ok"}
