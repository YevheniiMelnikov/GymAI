from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, Type, runtime_checkable

if TYPE_CHECKING:
    from core.cache.profile import ProfileCacheManager
    from core.cache.payment import PaymentCacheManager
    from core.schemas import Profile
else:
    ProfileCacheManager = PaymentCacheManager = object  # type: ignore[misc]
    Profile = object  # type: ignore[misc]


class CacheProtocol(Protocol):
    profile: Type[ProfileCacheManager]
    payment: Type[PaymentCacheManager]


@runtime_checkable
class PaymentNotifier(Protocol):
    def success(self, profile_id: int, language: str, credits: int) -> None: ...

    def failure(self, profile_id: int, language: str) -> None: ...
