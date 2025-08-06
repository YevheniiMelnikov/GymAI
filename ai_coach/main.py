from __future__ import annotations

import asyncio
from typing import Type

from fastapi import FastAPI
from fastapi.security import HTTPBasic
from loguru import logger

from ai_coach.api import lifespan
from ai_coach.base_coach import BaseAICoach
from ai_coach.base_knowledge_loader import KnowledgeLoader

coach_ready_event: asyncio.Event | None = None


async def init_ai_coach(ai_coach: type[BaseAICoach], knowledge_loader: KnowledgeLoader | None = None) -> None:
    """Initialize the AI coach and register it."""
    global coach_ready_event
    if coach_ready_event is None:
        coach_ready_event = asyncio.Event()

    if coach_ready_event.is_set():
        return

    set_ai_coach(ai_coach)
    try:
        await ai_coach.initialize(knowledge_loader)
    except Exception as e:  # pragma: no cover - best effort
        logger.error(f"AI coach init failed: {e}")
        coach_ready_event.clear()
        raise

    logger.success("AI coach initialized")
    coach_ready_event.set()


app = FastAPI(title="AI Coach", lifespan=lifespan)
security = HTTPBasic()
AI_COACH: Type[BaseAICoach] | None = None


def set_ai_coach(coach: Type[BaseAICoach]) -> None:
    global AI_COACH
    AI_COACH = coach


def get_ai_coach() -> Type[BaseAICoach]:
    if AI_COACH is None:
        raise RuntimeError("AI coach is not initialized")
    return AI_COACH
