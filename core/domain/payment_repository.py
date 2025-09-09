from decimal import Decimal
from typing import Any, Protocol

from core.schemas import Payment, Subscription


class PaymentRepository(Protocol):
    async def create_payment(
        self, client_profile_id: int, service_type: str, order_id: str, amount: Decimal
    ) -> bool: ...

    async def update_payment(self, payment_id: int, data: dict[str, Any]) -> bool: ...

    async def get_unclosed_payments(self) -> list[Payment]: ...

    async def get_expired_subscriptions(self, expired_before: str) -> list[Subscription]: ...

    async def update_payment_status(self, order_id: str, status_: str, error: str = "") -> Payment | None: ...

    async def get_latest_payment(self, client_profile_id: int, payment_type: str) -> Payment | None: ...
