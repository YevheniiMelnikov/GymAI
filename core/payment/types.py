from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Protocol, Type

from core.enums import CoachType

if TYPE_CHECKING:
    from core.cache.client_profile import ClientCacheManager
    from core.cache.coach_profile import CoachCacheManager
    from core.cache.payment import PaymentCacheManager
    from core.schemas import Client, Coach
else:  # pragma: no cover - typing only
    ClientCacheManager = CoachCacheManager = PaymentCacheManager = object  # type: ignore[misc]
    Client = Coach = object  # type: ignore[misc]


class CacheProtocol(Protocol):
    client: Type[ClientCacheManager]
    coach: Type[CoachCacheManager]
    payment: Type[PaymentCacheManager]


class CreditService(Protocol):
    def credits_for_amount(self, amount: Decimal) -> int: ...


class PaymentNotifier(Protocol):
    def success(self, client_id: int, language: str) -> None: ...

    def failure(self, client_id: int, language: str) -> None: ...


class CoachResolver(Protocol):
    async def get_assigned_coach(
        self,
        client: Client,
        *,
        coach_type: CoachType | None = None,
    ) -> Coach | None: ...
