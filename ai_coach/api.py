from fastapi import Depends, HTTPException, Request  # pyrefly: ignore[import-error]
from fastapi.responses import JSONResponse  # pyrefly: ignore[import-error]
from fastapi.security import HTTPBasicCredentials  # pyrefly: ignore[import-error]
from loguru import logger  # pyrefly: ignore[import-error]
from pydantic import ValidationError  # pyrefly: ignore[import-error]
from typing import Any, Awaitable, Callable

from ai_coach.agent.knowledge.knowledge_base import KnowledgeBase
from ai_coach.agent import AgentDeps, CoachAgent  # pyrefly: ignore[missing-module-attribute]
from ai_coach.agent.base import AgentExecutionAborted
from core.services import APIService
from ai_coach.application import app, security
from ai_coach.schemas import AICoachRequest
from ai_coach.types import AskCtx, CoachMode
from core.ai_coach_fallback import FALLBACK_WORKOUT_DAYS, fallback_plan
from core.enums import WorkoutPlanType, SubscriptionPeriod, WorkoutType
from config.app_settings import settings
from core.schemas import Client, Profile, Program, QAResponse, Subscription

CoachAction = Callable[[AskCtx], Awaitable[Program | Subscription | QAResponse | list[str] | None]]

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

    workout_days: list[str] = data.workout_days or list(FALLBACK_WORKOUT_DAYS)

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

    profile_language: str | None = None
    if profile is not None:
        profile_language_raw = getattr(profile, "language", None)
        if profile_language_raw is not None:
            profile_language = str(profile_language_raw)

    language: str = (data.language or None) or profile_language or settings.DEFAULT_LANG

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

    try:
        coach_agent_action = DISPATCH[mode]
    except KeyError as e:
        logger.exception(f"/ask unsupported mode: {mode.value}")
        raise HTTPException(status_code=422, detail="Unsupported mode") from e

    try:
        result: Any = await coach_agent_action(ctx)

        if mode == CoachMode.ask_ai:
            answer = getattr(result, "answer", None)
            sources = getattr(result, "sources", []) or []
            logger.debug(
                f"/ask agent completed request_id={data.request_id}"
                f" client_id={data.client_id} mode=ask_ai"
                f" answer_len={len(answer) if isinstance(answer, str) else 0} sources={len(sources)}"
                f" steps_used={deps.tool_calls} kb_empty={deps.knowledge_base_empty}"
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
        fallback_result: Program | Subscription | None = None
        if mode in {CoachMode.program, CoachMode.subscription, CoachMode.update}:
            plan_type_raw = ctx.get("plan_type")
            try:
                plan_type_enum = (
                    plan_type_raw if isinstance(plan_type_raw, WorkoutPlanType) else WorkoutPlanType(plan_type_raw)
                )
            except Exception:
                plan_type_enum = WorkoutPlanType.PROGRAM
            workout_type_raw = ctx.get("workout_type")
            workout_type_value = (
                workout_type_raw.value if isinstance(workout_type_raw, WorkoutType) else workout_type_raw
            )
            fallback_result = fallback_plan(
                plan_type=plan_type_enum,
                client_profile_id=data.client_id,
                workout_type=workout_type_value,
                wishes=ctx.get("wishes"),
                workout_days=ctx.get("workout_days"),
                period=ctx.get("period"),
            )
        if fallback_result is not None:
            deps.fallback_used = True
            logger.info(
                f"/ask agent fallback request_id={data.request_id} client_id={data.client_id} "
                f"mode={mode.value} reason={exc.reason} steps_used={deps.tool_calls}"
            )
            return fallback_result
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
    if (
        credentials.username != settings.AI_COACH_REFRESH_USER
        or credentials.password != settings.AI_COACH_REFRESH_PASSWORD
    ):
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        await KnowledgeBase.refresh()
    except Exception as e:  # pragma: no cover - log unexpected errors
        logger.exception(f"Knowledge refresh failed: {e}")
        raise HTTPException(status_code=503, detail="Refresh failed")
    return {"status": "ok"}
