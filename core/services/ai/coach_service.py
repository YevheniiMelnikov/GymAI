from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class AICoachService(ABC):
    """Abstract interface for AI coach backends."""

    @classmethod
    @abstractmethod
    async def coach_request(cls, text: str) -> None:
        """Process a message from a client."""

    @classmethod
    @abstractmethod
    async def coach_assign(cls, client: Any) -> None:
        """Handle a new client assignment."""

