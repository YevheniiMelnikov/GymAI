from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from ai_coach.cognee_coach import CogneeCoach
from core.tasks import refresh_external_knowledge
from config.app_settings import settings
from core.schemas import Client
from ai_coach import GDriveDocumentLoader
from ai_coach.utils.coach_utils import init_ai_coach


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_ai_coach(CogneeCoach, GDriveDocumentLoader())
    yield


app = FastAPI(title="AI Coach", lifespan=lifespan)


class AskRequest(BaseModel):
    prompt: str
    client: dict | None = None
    chat_id: int | None = None
    language: str | None = None


@app.post("/ask/", response_model=list[str] | None)
async def ask(data: AskRequest) -> list[str] | None:
    if data.client is None:
        raise HTTPException(status_code=400, detail="client required")
    client = Client(**data.client)
    return await CogneeCoach.make_request(data.prompt, client=client)


class MessageRequest(BaseModel):
    text: str
    chat_id: int
    client_id: int


@app.post("/messages/")
async def save_message(data: MessageRequest) -> dict[str, str]:
    await CogneeCoach.save_user_message(data.text, chat_id=data.chat_id, client_id=data.client_id)
    return {"status": "ok"}


@app.get("/context/")
async def get_context(chat_id: int, query: str) -> list[str]:
    return await CogneeCoach.get_context(chat_id, query)


@app.post("/knowledge/refresh/")
async def refresh_knowledge(request: Request) -> dict[str, str]:
    if request.headers.get("Authorization") != f"Api-Key {settings.API_KEY}":
        raise HTTPException(status_code=403, detail="Forbidden")
    refresh_external_knowledge.delay()
    return {"status": "scheduled"}
