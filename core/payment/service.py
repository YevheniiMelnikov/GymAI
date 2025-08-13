from __future__ import annotations

from decimal import Decimal
from typing import Any

from core.domain.payment_repository import PaymentRepository
from core.schemas import Payment, Subscription
from core.services.payments.liqpay import LiqPayGateway
from core.services.payments.payment_gateway import PaymentGateway


class PaymentService:
    def __init__(
        self,
        repository: PaymentRepository,
        settings,
        gateway: PaymentGateway | None = None,
    ) -> None:
        self._repository = repository
        self.gateway: PaymentGateway = gateway or LiqPayGateway(settings.PAYMENT_PUB_KEY, settings.PAYMENT_PRIVATE_KEY)

    async def get_payment_link(
        self,
        action: str,
        amount: Decimal,
        order_id: str,
        payment_type: str,
        client_profile_id: int,
    ) -> str:
        return await self.gateway.get_payment_link(
            action=action,
            amount=amount,
            order_id=order_id,
            payment_type=payment_type,
            client_id=client_profile_id,
        )

    async def create_payment(self, client_profile_id: int, service_type: str, order_id: str, amount: Decimal) -> bool:
        return await self._repository.create_payment(client_profile_id, service_type, order_id, amount)

    async def update_payment(self, payment_id: int, data: dict[str, Any]) -> bool:
        return await self._repository.update_payment(payment_id, data)

    async def get_unclosed_payments(self) -> list[Payment]:
        return await self._repository.get_unclosed_payments()

    async def get_expired_subscriptions(self, expired_before: str) -> list[Subscription]:
        return await self._repository.get_expired_subscriptions(expired_before)

    async def update_payment_status(self, order_id: str, status_: str, error: str = "") -> Payment | None:
        return await self._repository.update_payment_status(order_id, status_, error)

    async def get_latest_payment(self, client_profile_id: int, payment_type: str) -> Payment | None:
        return await self._repository.get_latest_payment(client_profile_id, payment_type)
