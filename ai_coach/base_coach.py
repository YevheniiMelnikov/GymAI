from __future__ import annotations

from abc import ABC, abstractmethod

from .base_knowledge_loader import KnowledgeLoader
from ai_coach.enums import DataKind


class BaseAICoach(ABC):
    """Pure interface-layer for AI coach backends."""

    @classmethod
    @abstractmethod
    async def initialize(cls, knowledge_loader: KnowledgeLoader | None = None) -> None:
        """Run necessary bootstrapping such as DB migrations or LLM pings."""
        raise NotImplementedError

    @classmethod
    @abstractmethod
    async def save_user_message(cls, text: str, client_id: int) -> None:
        """Persist a user-authored message."""
        raise NotImplementedError

    @classmethod
    @abstractmethod
    async def save_ai_message(cls, text: str, client_id: int) -> None:
        """Persist an AI-generated reply."""
        raise NotImplementedError

    @classmethod
    @abstractmethod
    async def save_prompt(cls, text: str, client_id: int) -> None:
        """Persist a raw prompt exchanged with the model."""
        raise NotImplementedError

    @classmethod
    @abstractmethod
    async def get_client_knowledge(
        cls, client_id: int, query: str
    ) -> dict[str, list[str]]:
        """Retrieve client context separated into messages and prompts."""
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
