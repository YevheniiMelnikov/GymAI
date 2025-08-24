from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.security import HTTPBasic
from loguru import logger

from ai_coach.cognee_coach import CogneeCoach
from ai_coach.base_coach import BaseAICoach
from ai_coach.base_knowledge_loader import KnowledgeLoader
from core.containers import create_container, set_container, get_container
from core.services.internal import APIService

coach_ready_event: asyncio.Event | None = None


async def init_ai_coach(ai_coach: type[BaseAICoach], knowledge_loader: KnowledgeLoader | None = None) -> None:
    """Initialize the AI coach."""
    global coach_ready_event
    if coach_ready_event is None:
        coach_ready_event = asyncio.Event()

    if coach_ready_event.is_set():
        return

    try:
        await ai_coach.initialize(knowledge_loader)
    except Exception as e:  # pragma: no cover - best effort
        logger.error(f"AI coach init failed: {e}")
        coach_ready_event.clear()
        raise

    logger.success("AI coach initialized")
    coach_ready_event.set()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    from ai_coach.gdrive_knowledge_loader import GDriveDocumentLoader

    container = create_container()
    set_container(container)
    APIService.configure(get_container)
    container.wire(modules=["core.tasks"])
    init_resources = container.init_resources()
    if init_resources is not None:
        await init_resources

    loader = GDriveDocumentLoader(CogneeCoach.add_text)
    await init_ai_coach(CogneeCoach, loader)
    try:
        yield
    finally:
        shutdown_resources = container.shutdown_resources()
        if shutdown_resources is not None:
            await shutdown_resources


app = FastAPI(title="AI Coach", lifespan=lifespan)
security = HTTPBasic()
