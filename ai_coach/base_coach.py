from __future__ import annotations

from abc import ABC, abstractmethod

from .base_knowledge_loader import KnowledgeLoader
from ai_coach.enums import DataKind, MessageRole


class BaseAICoach(ABC):
    """Pure interface-layer for AI coach backends."""

    @classmethod
    @abstractmethod
    async def initialize(cls, knowledge_loader: KnowledgeLoader | None = None) -> None:
        """Run necessary bootstrapping such as DB migrations or LLM pings."""
        raise NotImplementedError

    @classmethod
    @abstractmethod
    async def update_client_knowledge(
        cls,
        text: str,
        client_id: int,
        *,
        kind: DataKind = DataKind.MESSAGE,
        role: MessageRole | None = None,
    ) -> None:
        """Persist ``text`` under ``client_id`` and ``kind``; ``role`` for messages."""
        raise NotImplementedError

    @classmethod
    @abstractmethod
    async def get_context(cls, client_id: int, query: str) -> list[str]:
        """Retrieve context for ``client_id`` without side effects."""
        raise NotImplementedError

    @classmethod
    @abstractmethod
    async def make_request(cls, prompt: str, client_id: int) -> list[str]:
        """Search indexed data for ``prompt`` scoped to ``client_id``."""
        raise NotImplementedError

    @classmethod
    @abstractmethod
    async def refresh_knowledge_base(cls) -> None:
        """Fetch external knowledge and rebuild the knowledge base."""
        raise NotImplementedError

    @classmethod
    @abstractmethod
    async def reindex(
        cls, client_id: int, kind: DataKind = DataKind.MESSAGE
    ) -> None:
        """Force reindex of the specified dataset."""
        raise NotImplementedError
