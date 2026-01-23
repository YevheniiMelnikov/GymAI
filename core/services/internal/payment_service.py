from decimal import Decimal
from typing import Any

from core.domain.payment_repository import PaymentRepository
from core.schemas import Payment, Subscription
from core.payment.providers.liqpay import LiqPayGateway
from core.payment.providers.payment_gateway import PaymentGateway


class PaymentService:
    """Coordinate payment repository and gateway interactions."""

    def __init__(
        self,
        repository: PaymentRepository,
        settings,
        gateway: PaymentGateway | None = None,
    ) -> None:
        self._repository = repository
        self.gateway: PaymentGateway = gateway or LiqPayGateway(
            settings.PAYMENT_PUB_KEY,
            settings.PAYMENT_PRIVATE_KEY,
            server_url=settings.PAYMENT_CALLBACK_URL,
            result_url=settings.BOT_LINK,
            email=settings.EMAIL,
            checkout_url=settings.CHECKOUT_URL,
        )

    async def get_payment_link(
        self,
        action: str,
        amount: Decimal,
        order_id: str,
        payment_type: str,
        profile_id: int,
    ) -> str:
        return await self.gateway.get_payment_link(
            action=action,
            amount=amount,
            order_id=order_id,
            payment_type=payment_type,
            profile_id=profile_id,
        )

    async def update_payment(self, payment_id: int, data: dict[str, Any]) -> bool:
        return await self._repository.update_payment(payment_id, data)

    async def get_expired_subscriptions(self, expired_before: str) -> list[Subscription]:
        return await self._repository.get_expired_subscriptions(expired_before)

    async def update_payment_status(self, order_id: str, status_: str, error: str = "") -> Payment | None:
        return await self._repository.update_payment_status(order_id, status_, error)

    async def get_latest_payment(self, profile_id: int, payment_type: str) -> Payment | None:
        return await self._repository.get_latest_payment(profile_id, payment_type)
