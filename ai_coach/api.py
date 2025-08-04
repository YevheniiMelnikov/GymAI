from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel

from ai_coach.cognee_coach import CogneeCoach
from ai_coach.enums import DataKind
from core.tasks import refresh_external_knowledge
from config.app_settings import settings
from ai_coach import GDriveDocumentLoader
from ai_coach.utils.coach_utils import init_ai_coach


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_ai_coach(CogneeCoach, GDriveDocumentLoader())
    yield


app = FastAPI(title="AI Coach", lifespan=lifespan)
security = HTTPBasic()


class AskRequest(BaseModel):
    prompt: str
    client_id: int
    language: str | None = None


@app.post("/ask/", response_model=list[str] | None)
async def ask(data: AskRequest) -> list[str] | None:
    responses = await CogneeCoach.make_request(data.prompt, client_id=data.client_id)
    await CogneeCoach.save_text_entry(
        data.prompt, client_id=data.client_id, kind=DataKind.PROMPT
    )
    if responses:
        for r in responses:
            await CogneeCoach.save_text_entry(
                r, client_id=data.client_id, kind=DataKind.PROMPT
            )
    return responses


class MessageRequest(BaseModel):
    text: str
    client_id: int


@app.post("/messages/")
async def save_message(data: MessageRequest) -> dict[str, str]:
    await CogneeCoach.save_text_entry(
        data.text, client_id=data.client_id, kind=DataKind.MESSAGE
    )
    return {"status": "ok"}


@app.get("/context/")
async def get_context(client_id: int, query: str) -> list[str]:
    return await CogneeCoach.get_context(client_id, query)


@app.post("/knowledge/refresh/")
async def refresh_knowledge(credentials: HTTPBasicCredentials = Depends(security)) -> dict[str, str]:
    if (
        credentials.username != settings.AI_COACH_REFRESH_USER
        or credentials.password != settings.AI_COACH_REFRESH_PASSWORD
    ):
        raise HTTPException(status_code=401, detail="Unauthorized")
    refresh_external_knowledge.delay()
    return {"status": "scheduled"}
