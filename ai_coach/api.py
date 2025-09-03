from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBasicCredentials
from loguru import logger
from pydantic import ValidationError

from ai_coach.cognee_coach import CogneeCoach
from ai_coach.coach_agent import AgentDeps, CoachAgent
from ai_coach.application import app, security
from ai_coach.schemas import AskRequest, MessageRequest
from config.app_settings import settings
from core.schemas import Program, QAResponse, Subscription
from core.tasks import refresh_external_knowledge

from config.celery import celery_app as celery  # type: ignore

celery.set_default()


@app.get("/health/")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/ask/", response_model=Program | Subscription | QAResponse | list[str] | None)
async def ask(data: AskRequest, request: Request) -> Program | Subscription | QAResponse | list[str] | None:
    logger.debug("/ask received request_id={} client_id={}", data.request_id, data.client_id)
    use_agent = settings.AGENT_PYDANTICAI_ENABLED or request.headers.get("X-Agent", "").lower() == "pydanticai"
    if use_agent:
        deps = AgentDeps(
            client_id=data.client_id,
            locale=data.language or settings.DEFAULT_LANG,
            allow_save=data.mode != "ask_ai",
            log_conversation_for_ask_ai=settings.LOG_CONVERSATION_FOR_ASK_AI,
        )
        try:
            if data.mode == "program":
                program = await CoachAgent.generate_program(data.prompt, deps=deps)
                logger.debug(
                    "/ask agent completed request_id={} client_id={} mode=program",
                    data.request_id,
                    data.client_id,
                )
                return program
            if data.mode == "subscription":
                result = await CoachAgent.generate_subscription(
                    data.prompt,
                    period=data.period or "1m",
                    workout_days=data.workout_days or [],
                    deps=deps,
                )
                logger.debug(
                    "/ask agent completed request_id={} client_id={} mode=subscription",
                    data.request_id,
                    data.client_id,
                )
                return result
            if data.mode == "update":
                program = await CoachAgent.update_program(
                    data.prompt,
                    expected_workout=data.expected_workout or "",
                    feedback=data.feedback or "",
                    deps=deps,
                )
                logger.debug(
                    "/ask agent completed request_id={} client_id={} mode=update",
                    data.request_id,
                    data.client_id,
                )
                return program
            if data.mode == "ask_ai":
                resp = await CoachAgent.answer_question(data.prompt, deps=deps)
                logger.debug(
                    "/ask agent completed request_id={} client_id={} mode=ask_ai answer_len={} sources={}",
                    data.request_id,
                    data.client_id,
                    len(resp.answer),
                    len(resp.sources),
                )
                if settings.LOG_CONVERSATION_FOR_ASK_AI:
                    await CogneeCoach.save_client_message(data.prompt, client_id=data.client_id)
                    await CogneeCoach.save_ai_message(resp.answer, client_id=data.client_id)
                return resp
        except ValidationError as e:
            logger.exception("/ask agent validation error: {}", e)
            raise HTTPException(status_code=422, detail="Invalid response") from e
        except Exception as e:  # pragma: no cover - log unexpected errors
            logger.exception("/ask agent failed: {}", e)
            raise HTTPException(status_code=503, detail="Service unavailable") from e
    try:
        responses = await CogneeCoach.make_request(data.prompt, client_id=data.client_id)
        await CogneeCoach.save_client_message(data.prompt, client_id=data.client_id)
        if responses:
            for r in responses:
                await CogneeCoach.save_ai_message(r, client_id=data.client_id)
        logger.debug(
            "/ask completed request_id={} client_id={} responses={}",
            data.request_id,
            data.client_id,
            responses,
        )
        return responses
    except Exception as e:  # pragma: no cover - log unexpected errors
        logger.exception("/ask failed: {}", e)
        raise HTTPException(status_code=503, detail="Service unavailable") from e


@app.post("/messages/")
async def save_message(data: MessageRequest) -> dict[str, str]:
    await CogneeCoach.save_client_message(data.text, client_id=data.client_id)
    return {"status": "ok"}


@app.get("/knowledge/")
async def get_knowledge(client_id: int, query: str) -> dict[str, list[str]]:
    return await CogneeCoach.get_client_context(client_id, query)


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
        logger.exception("Failed to enqueue refresh task: {}", e)
        raise HTTPException(status_code=503, detail="Queue unavailable")
