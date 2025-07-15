from __future__ import annotations

from typing import Any


from core.ai_coach.base import BaseAICoach
from core.ai_coach.knowledge_loader import KnowledgeLoader
from core.ai_coach.registry import set_ai_coach, get_ai_coach
from core.schemas import Client
from loguru import logger


async def init_ai_coach(
    ai_coach: type[BaseAICoach], knowledge_loader: KnowledgeLoader | None = None
) -> None:
    """Initialize the AI coach and register it."""

    set_ai_coach(ai_coach)
    logger.info("Starting AI coach initialization")

    await ai_coach.initialize()

    if knowledge_loader is not None:
        await ai_coach.init_loader(knowledge_loader)

    logger.info(f"AI coach {ai_coach.__name__} initialized")


async def ai_coach_request(*args: Any, **kwargs: Any) -> list | None:
    text = kwargs.get("text") or (args[0] if args else None)
    client: Client | None = kwargs.get("client")
    chat_id: int | None = kwargs.get("chat_id")
    language: str | None = kwargs.get("language")
    if not text:
        return None
    coach = get_ai_coach()
    return await coach.coach_request(str(text), client=client, chat_id=chat_id, language=language)


async def ai_assign_client(*args: Any, **kwargs: Any) -> None:
    client: Client | None = kwargs.get("client") or (args[0] if args else None)
    if client is None:
        return
    coach = get_ai_coach()
    await coach.assign_client(client)


async def ai_process_workout_result(client_id: int, feedback: str, language: str | None = None) -> str:
    coach = get_ai_coach()
    return await coach.process_workout_result(client_id, feedback, language)
