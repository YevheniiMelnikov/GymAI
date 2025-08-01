from __future__ import annotations

from typing import Any

import asyncio

from ai_coach.base_coach import BaseAICoach
from ai_coach.base_knowledge_loader import KnowledgeLoader
from ai_coach.utils.registry import set_ai_coach, get_ai_coach
from core.schemas import Client
from loguru import logger

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
        await ai_coach.initialize()
    except Exception as e:
        logger.error(f"AI coach init failed: {e}")
        coach_ready_event.clear()
        raise

    if knowledge_loader is not None:
        await ai_coach.init_loader(knowledge_loader)

    logger.success("AI coach initialized")
    coach_ready_event.set()


async def _wait_for_coach() -> None:
    if coach_ready_event is not None and not coach_ready_event.is_set():
        await coach_ready_event.wait()


async def ai_coach_request(*args: Any, **kwargs: Any) -> list[str] | None:
    text = kwargs.get("text") or (args[0] if args else None)
    client: Client | None = kwargs.get("client")
    if not text:
        return None
    if client is None:
        raise ValueError("client required")
    await _wait_for_coach()
    coach = get_ai_coach()
    return await coach.make_request(str(text), client=client)
