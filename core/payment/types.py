from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, Type

if TYPE_CHECKING:
    from core.cache.client_profile import ClientCacheManager
    from core.cache.coach_profile import CoachCacheManager
    from core.cache.payment import PaymentCacheManager
else:  # pragma: no cover - typing only
    ClientCacheManager = CoachCacheManager = PaymentCacheManager = object  # type: ignore[misc]


class CacheProtocol(Protocol):
    client: Type[ClientCacheManager]
    coach: Type[CoachCacheManager]
    payment: Type[PaymentCacheManager]
