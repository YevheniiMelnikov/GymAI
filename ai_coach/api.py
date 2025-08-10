from __future__ import annotations

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBasicCredentials
from loguru import logger

from ai_coach.cognee_coach import CogneeCoach
from ai_coach.application import app, security
from ai_coach.schemas import AskRequest, MessageRequest
from config.app_settings import settings
from core.tasks import refresh_external_knowledge

from config.celery import celery_app as celery  # type: ignore

celery.set_default()


@app.get("/health/")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/ask/", response_model=list[str] | None)
async def ask(data: AskRequest) -> list[str] | None:
    logger.debug("/ask received request_id={} client_id={}", data.request_id, data.client_id)
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
        raise HTTPException(status_code=500, detail="AI coach error") from e


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
        refresh_external_knowledge.apply_async(queue="maintenance")
        return {"status": "queued"}
    except Exception as e:
        logger.exception("Failed to enqueue refresh task: {}", e)
        raise HTTPException(status_code=503, detail="Queue unavailable")
