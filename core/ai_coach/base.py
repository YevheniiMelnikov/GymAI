from __future__ import annotations

from abc import ABC, abstractmethod

from core.ai_coach.knowledge_loader import KnowledgeLoader
from core.schemas import Client


class BaseAICoach(ABC):
    """Pure interface-layer for AI coach backends."""

    @classmethod
    @abstractmethod
    async def initialize(cls) -> None:
        """Run necessary bootstrapping (e.g. DB migrations, LLM pings)"""
        raise NotImplementedError

    @classmethod
    @abstractmethod
    async def coach_request(
        cls,
        text: str,
        *,
        client: Client | None = None,
        chat_id: int | None = None,
        language: str | None = None,
    ) -> None:
        """Handle an incoming user message."""

    @classmethod
    @abstractmethod
    async def assign_client(cls, client: Client) -> None:
        """Run one-off logic when a new client is assigned."""

    @classmethod
    async def init_loader(cls, loader: KnowledgeLoader) -> None:  # noqa: D401
        """Attach a loader at startup (override to use)."""
        raise NotImplementedError

    @classmethod
    async def refresh_knowledge_base(cls) -> None:
        """Fetch external knowledge and rebuild the knowledge base."""
        raise NotImplementedError

    @classmethod
    async def update_knowledge_base(cls) -> None:
        """Re-index knowledge after load (override to use)."""
        raise NotImplementedError

    @classmethod
    @abstractmethod
    async def process_workout_result(cls, client_id: int, feedback: str, language: str | None = None) -> str:
        """Return updated program text for ``client_id`` based on ``feedback``."""
