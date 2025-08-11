from __future__ import annotations

import abc
from typing import Any


class BaseAICoach(abc.ABC):
    """
    Abstract base class for AI Coaches managing knowledge and context.
    """

    @classmethod
    @abc.abstractmethod
    async def initialize(cls, knowledge_loader: Any | None = None) -> None:
        """
        Initialize the coach, apply config and prepare necessary systems.
        """
        ...

    @classmethod
    @abc.abstractmethod
    async def refresh_knowledge_base(cls) -> None:
        """
        Refresh any external knowledge sources and reindex.
        """
        ...

    @classmethod
    @abc.abstractmethod
    async def save_client_message(cls, text: str, client_id: int) -> None:
        """
        Save a raw user message associated with a client.
        """
        ...

    @classmethod
    @abc.abstractmethod
    async def save_ai_message(cls, text: str, client_id: int) -> None:
        """
        Save an AI-generated message associated with a client.
        """
        ...

    @classmethod
    @abc.abstractmethod
    async def get_client_context(cls, client_id: int, query: str) -> dict[str, list[str]]:
        """
        Retrieve relevant context (e.g. chat messages) for a query.
        """
        ...

    @classmethod
    @abc.abstractmethod
    async def make_request(cls, prompt: str, client_id: int) -> list[str]:
        """
        Query the AI system using a client's context.
        """
        ...

    @classmethod
    @abc.abstractmethod
    async def refresh_client_knowledge(cls, client_id: int) -> None:
        """
        Force reindex of a client's dataset. Use this method when:
        - bulk updates were applied outside the normal saving flow;
        - you suspect the index is out of sync with the underlying data;
        - admin tools or maintenance scripts require a full refresh.

        This method does NOT check if data has changed — it always triggers reindex.
        """
        ...
