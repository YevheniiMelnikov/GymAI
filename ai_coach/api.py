from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel

from ai_coach.cognee_coach import CogneeCoach
from ai_coach.utils import init_ai_coach
from ai_coach import GDriveDocumentLoader


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
    return await CogneeCoach.make_request(data.prompt, client=None)


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
async def refresh_knowledge() -> dict[str, str]:
    await CogneeCoach.refresh_knowledge_base()
    return {"status": "ok"}
