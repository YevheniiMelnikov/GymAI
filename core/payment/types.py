from typing import TYPE_CHECKING, Protocol, Type

if TYPE_CHECKING:
    from core.cache.profile import ProfileCacheManager
    from core.cache.payment import PaymentCacheManager
    from core.schemas import Profile
else:  # pragma: no cover - typing only
    ProfileCacheManager = PaymentCacheManager = object  # type: ignore[misc]
    Profile = object  # type: ignore[misc]


class CacheProtocol(Protocol):
    profile: Type[ProfileCacheManager]
    payment: Type[PaymentCacheManager]


class PaymentNotifier(Protocol):
    def success(self, profile_id: int, language: str) -> None: ...

    def failure(self, profile_id: int, language: str) -> None: ...
