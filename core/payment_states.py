from __future__ import annotations

from abc import ABC, abstractmethod
from loguru import logger

from apps.payments.tasks import send_payment_message
from bot.texts.text_manager import msg_text
from config.env_settings import settings
from typing import TYPE_CHECKING

from core.schemas import Payment, Client

if TYPE_CHECKING:  # pragma: no cover - used only for type checking
    from core.payment_processor import PaymentProcessor


class PaymentState(ABC):
    """Abstract payment processing state."""

    def __init__(self, processor: type["PaymentProcessor"]):
        self.processor = processor

    @abstractmethod
    async def handle(self, payment: Payment, client: Client) -> None:
        """Handle payment based on current state."""


class SuccessState(PaymentState):
    async def handle(self, payment: Payment, client: Client) -> None:
        profile = await self.processor.profile_service.get_profile(client.profile)
        if not profile:
            logger.error(f"Profile not found for client {client.id}")
            return

        send_payment_message.delay(
            client.id,
            msg_text("payment_success", profile.language),  # type: ignore[attr-defined]
        )
        logger.info(f"Client {client.id} successfully paid {payment.amount} UAH for credits")
        await self.processor.process_credit_topup(client, payment.amount)


class FailureState(PaymentState):
    async def handle(self, payment: Payment, client: Client) -> None:
        profile = await self.processor.profile_service.get_profile(client.profile)
        if not profile:
            logger.error(f"Profile not found for client {client.id}")
            return

        send_payment_message.delay(
            client.id,
            msg_text("payment_failure", profile.language).format(
                mail=settings.EMAIL,
                tg=settings.TG_SUPPORT_CONTACT,
            ),
        )
