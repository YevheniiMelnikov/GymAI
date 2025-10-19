from typing import Protocol

from bot.utils.profiles import get_assigned_coach

from core.enums import CoachType
from core.payment.types import CoachResolver
from core.schemas import Client, Coach


class _CoachGetter(Protocol):
    async def __call__(
        self,
        client: Client,
        *,
        coach_type: CoachType | None = None,
    ) -> Coach | None: ...


class BotCoachResolver(CoachResolver):
    def __init__(self, coach_getter: _CoachGetter | None = None) -> None:
        self._coach_getter: _CoachGetter = coach_getter or get_assigned_coach

    async def get_assigned_coach(
        self,
        client: Client,
        *,
        coach_type: CoachType | None = None,
    ) -> Coach | None:
        return await self._coach_getter(client, coach_type=coach_type)
