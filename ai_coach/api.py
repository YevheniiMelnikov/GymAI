from fastapi import Depends, HTTPException, Request  # pyrefly: ignore[import-error]
from fastapi.security import HTTPBasicCredentials  # pyrefly: ignore[import-error]
from loguru import logger  # pyrefly: ignore[import-error]
from pydantic import ValidationError  # pyrefly: ignore[import-error]
from typing import Awaitable, Callable, Any

from ai_coach.agent.knowledge.knowledge_base import KnowledgeBase
from ai_coach.agent import AgentDeps, CoachAgent  # pyrefly: ignore[missing-module-attribute]
from core.services import APIService
from ai_coach.application import app, security
from ai_coach.schemas import AICoachRequest
from ai_coach.types import AskCtx, CoachMode
from core.enums import WorkoutPlanType, SubscriptionPeriod
from config.app_settings import settings
from core.schemas import Program, QAResponse, Subscription

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


@app.post("/ask/", response_model=Program | Subscription | QAResponse | list[str] | None)
async def ask(data: AICoachRequest, request: Request) -> Program | Subscription | QAResponse | list[str] | None:
    mode = data.mode if isinstance(data.mode, CoachMode) else CoachMode(data.mode)
    logger.debug(f"/ask received request_id={data.request_id} client_id={data.client_id} mode={mode.value}")

    if mode == CoachMode.update and data.plan_type is None:
        raise HTTPException(status_code=422, detail="plan_type required for update mode")

    period = (
        data.period
        if isinstance(data.period, SubscriptionPeriod)
        else SubscriptionPeriod(data.period or SubscriptionPeriod.one_month.value)
    )

    ctx: AskCtx = {
        "prompt": data.prompt,
        "client_id": data.client_id,
        "period": period.value,
        "workout_days": data.workout_days or [],
        "expected_workout": data.expected_workout or "",
        "feedback": data.feedback or "",
        "wishes": data.wishes or "",
        "language": data.language or settings.DEFAULT_LANG,
        "workout_type": data.workout_type,
        "plan_type": data.plan_type,
        "instructions": data.instructions,
    }

    try:
        client = await APIService.profile.get_client(data.client_id)
    except Exception:  # pragma: no cover - missing profile service
        client = None

    client_name = getattr(client, "name", None)

    deps = AgentDeps(
        client_id=data.client_id,
        locale=ctx["language"],
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
            )
            if isinstance(answer, str):
                await KnowledgeBase.save_client_message(data.prompt or "", client_id=data.client_id)
                await KnowledgeBase.save_ai_message(answer, client_id=data.client_id)
        else:
            logger.debug(
                f"/ask agent completed request_id={data.request_id} client_id={data.client_id} mode={mode.value}"
            )
        return result

    except ValidationError as e:
        logger.exception(f"/ask agent validation error: {e}")
        raise HTTPException(status_code=422, detail="Invalid response") from e
    except Exception as e:  # pragma: no cover - log unexpected errors
        logger.exception(f"/ask agent failed, falling back to KnowledgeBase: {e}")
        try:
            responses = await KnowledgeBase.search(data.prompt or "", client_id=data.client_id)
            logger.debug(
                f"/ask completed request_id={data.request_id} client_id={data.client_id} responses={responses}"
            )
            return responses
        except Exception as e:  # pragma: no cover - log unexpected errors
            logger.exception(f"/ask failed: {e}")
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
