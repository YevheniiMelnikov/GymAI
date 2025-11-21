from decimal import Decimal
from typing import TYPE_CHECKING, Protocol, Type

if TYPE_CHECKING:
    from core.cache.client_profile import ClientCacheManager
    from core.cache.payment import PaymentCacheManager
    from core.schemas import Client
else:  # pragma: no cover - typing only
    ClientCacheManager = PaymentCacheManager = object  # type: ignore[misc]
    Client = object  # type: ignore[misc]


class CacheProtocol(Protocol):
    client: Type[ClientCacheManager]
    payment: Type[PaymentCacheManager]


class CreditService(Protocol):
    def credits_for_amount(self, amount: Decimal) -> int: ...


class PaymentNotifier(Protocol):
    def success(self, client_id: int, language: str) -> None: ...

    def failure(self, client_id: int, language: str) -> None: ...
