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
    async def coach_request(cls, text: str) -> None:
        """Handle an incoming user message."""

    @classmethod
    @abstractmethod
    async def coach_assign(cls, client: Client) -> None:
        """Run one-off logic when a new client is assigned."""

    @classmethod
    async def init_loader(cls, loader: KnowledgeLoader) -> None:  # noqa: D401
        """Attach a loader at startup (override to use)."""
        raise NotImplementedError

    @classmethod
    async def load_external_knowledge(cls) -> None:
        """Fetch external knowledge (override to use)."""
        raise NotImplementedError

    @classmethod
    async def update_knowledge_base(cls) -> None:
        """Re-index knowledge after load (override to use)."""
        raise NotImplementedError
