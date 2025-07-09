from __future__ import annotations

from typing import Any

from loguru import logger

from core.ai_coach.base import BaseAICoach
from core.ai_coach.knowledge_loader import KnowledgeLoader
from core.ai_coach.registry import set_ai_coach, get_ai_coach
from core.schemas import Client


async def init_ai_coach(ai_coach: type[BaseAICoach], knowledge_loader: KnowledgeLoader | None = None) -> None:
    await ai_coach.initialize()

    if knowledge_loader is not None:
        await ai_coach.init_loader(knowledge_loader)

    set_ai_coach(ai_coach)


async def ai_coach_request(*args: Any, **kwargs: Any) -> list | None:
    text = kwargs.get("text") or (args[0] if args else None)
    if not text:
        return None
    coach = get_ai_coach()
    return await coach.coach_request(str(text))


async def ai_assign_client(*args: Any, **kwargs: Any) -> None:
    client: Client = kwargs.get("client") or (args[0] if args else None)
    if client is None:
        return
    coach = get_ai_coach()
    await coach.assign_client(client)
