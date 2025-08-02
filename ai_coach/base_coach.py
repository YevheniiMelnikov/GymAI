from __future__ import annotations

from abc import ABC, abstractmethod

from .base_knowledge_loader import KnowledgeLoader
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
    async def make_request(cls, prompt: str, *, client: Client | None = None) -> list[str]:
        """Handle an incoming user message."""

    @classmethod
    async def save_user_message(cls, text: str, client_id: int) -> None:
        """Persist a user message for later context retrieval."""
        raise NotImplementedError

    @classmethod
    async def init_loader(cls, loader: KnowledgeLoader) -> None:  # noqa: D401
        """Attach a loader at startup (override to use)."""
        raise NotImplementedError

    @classmethod
    async def refresh_knowledge_base(cls) -> None:
        """Fetch external knowledge and rebuild the knowledge base."""
        raise NotImplementedError
