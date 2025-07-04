from __future__ import annotations

from abc import ABC, abstractmethod


class KnowledgeLoader(ABC):
    """Abstract interface for knowledge loading backends.

    Only one method is required for now, but keeping this ABC makes it
    straightforward to plug in alternative loaders later.
    """

    @abstractmethod
    async def load(self) -> None:
        """Load external knowledge into Cognee."""
        raise NotImplementedError
