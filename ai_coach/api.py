from fastapi import Depends, HTTPException, Request  # pyrefly: ignore[import-error]
from fastapi.security import HTTPBasicCredentials  # pyrefly: ignore[import-error]
from loguru import logger  # pyrefly: ignore[import-error]
from pydantic import ValidationError  # pyrefly: ignore[import-error]
from typing import Awaitable, Callable, Any

from ai_coach.agent.knowledge.knowledge_base import KnowledgeBase
from ai_coach.agent import AgentDeps, CoachAgent
from core.cache import Cache
from ai_coach.application import app, security
from ai_coach.schemas import AskRequest, MessageRequest
from ai_coach.types import AskCtx, CoachMode
from config.app_settings import settings
from core.schemas import Program, QAResponse, Subscription
from core.tasks import refresh_external_knowledge

from config.celery import celery_app as celery  # type: ignore

celery.set_default()


CoachAction = Callable[[AskCtx], Awaitable[object]]

DISPATCH: dict[CoachMode, CoachAction] = {
    CoachMode.program: lambda ctx: CoachAgent.generate_program(ctx["prompt"], deps=ctx["deps"]),
    CoachMode.subscription: lambda ctx: CoachAgent.generate_subscription(
        ctx["prompt"],
        period=ctx["period"],
        workout_days=ctx["workout_days"],
        deps=ctx["deps"],
    ),
    CoachMode.update: lambda ctx: CoachAgent.update_program(
        ctx["prompt"],
        expected_workout=ctx["expected_workout"],
        feedback=ctx["feedback"],
        deps=ctx["deps"],
    ),
    CoachMode.ask_ai: lambda ctx: CoachAgent.answer_question(ctx["prompt"], deps=ctx["deps"]),
}


@app.get("/health/")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/ask/", response_model=Program | Subscription | QAResponse | list[str] | None)
async def ask(data: AskRequest, request: Request) -> Program | Subscription | QAResponse | list[str] | None:
    mode = data.mode if isinstance(data.mode, CoachMode) else CoachMode(data.mode)
    logger.debug(f"/ask received request_id={data.request_id} client_id={data.client_id} mode={mode.value}")
    ctx: AskCtx = {
        "prompt": data.prompt,
        "client_id": data.client_id,
        "period": data.period or "1m",
        "workout_days": data.workout_days or [],
        "expected_workout": data.expected_workout or "",
        "feedback": data.feedback or "",
        "language": data.language or settings.DEFAULT_LANG,
    }
    client_name: str | None = None
    try:
        client = await Cache.client.get_client(data.client_id)
        client_name = client.name
    except Exception:  # pragma: no cover - missing cache/service
        client_name = None
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
            sources = getattr(result, "sources", []) or []
            logger.debug(
                f"/ask agent completed request_id={data.request_id}"
                f" client_id={data.client_id} mode=ask_ai"
                f" answer_len={len(result.answer)} sources={len(sources)}"
            )
            await KnowledgeBase.save_client_message(data.prompt, client_id=data.client_id)
            await KnowledgeBase.save_ai_message(result.answer, client_id=data.client_id)
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
            responses = await KnowledgeBase.make_request(data.prompt, client_id=data.client_id)
            await KnowledgeBase.save_client_message(data.prompt, client_id=data.client_id)
            if responses:
                for r in responses:
                    await KnowledgeBase.save_ai_message(r, client_id=data.client_id)
            logger.debug(
                f"/ask completed request_id={data.request_id} client_id={data.client_id} responses={responses}"
            )
            return responses
        except Exception as e:  # pragma: no cover - log unexpected errors
            logger.exception(f"/ask failed: {e}")
            raise HTTPException(status_code=503, detail="Service unavailable") from e


@app.post("/messages/")
async def save_message(data: MessageRequest) -> dict[str, str]:
    await KnowledgeBase.save_client_message(data.text, client_id=data.client_id)
    return {"status": "ok"}


@app.get("/knowledge/")
async def get_knowledge(client_id: int, query: str) -> dict[str, list[str]]:
    return await KnowledgeBase.get_client_context(client_id, query)


@app.post("/knowledge/refresh/")
async def refresh_knowledge(credentials: HTTPBasicCredentials = Depends(security)) -> dict[str, str]:
    if (
        credentials.username != settings.AI_COACH_REFRESH_USER
        or credentials.password != settings.AI_COACH_REFRESH_PASSWORD
    ):
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        refresh_external_knowledge.apply_async(queue="maintenance")  # pyrefly: ignore[not-callable]
        return {"status": "queued"}
    except Exception as e:
        logger.exception(f"Failed to enqueue refresh task: {e}")
        raise HTTPException(status_code=503, detail="Queue unavailable")
