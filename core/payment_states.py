from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from dateutil.relativedelta import relativedelta
from loguru import logger

from apps.payments.tasks import send_payment_message
from bot.texts.text_manager import msg_text
from bot.utils.workout_plans import cancel_subscription
from config.env_settings import settings
from typing import TYPE_CHECKING

from core.enums import PaymentType
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
        logger.info(f"Client {client.id} successfully paid {payment.amount} UAH for {payment.payment_type}")

        if payment.payment_type == PaymentType.subscription:
            await self.processor.process_subscription_payment(client)
        elif payment.payment_type == PaymentType.program:
            await self.processor.process_program_payment(client)


class FailureState(PaymentState):
    async def handle(self, payment: Payment, client: Client) -> None:
        profile = await self.processor.profile_service.get_profile(client.profile)
        if not profile:
            logger.error(f"Profile not found for client {client.id}")
            return

        if payment.payment_type == PaymentType.subscription:
            subscription = await self.processor.cache.workout.get_latest_subscription(client.id)
            if subscription and subscription.enabled:
                try:
                    payment_date = datetime.strptime(subscription.payment_date, "%Y-%m-%d")
                    next_payment_date = payment_date + relativedelta(months=1)
                    send_payment_message.delay(
                        client.id,
                        msg_text("subscription_cancel_warning", profile.language).format(
                            date=next_payment_date.strftime("%Y-%m-%d"),
                            mail=settings.EMAIL,
                            tg=settings.TG_SUPPORT_CONTACT,
                        ),
                    )
                    await cancel_subscription(next_payment_date, client.id, subscription.id)
                    logger.info(f"Subscription for client_id {client.id} deactivated due to failed payment")
                    return
                except ValueError as e:
                    logger.error(
                        f"Invalid date format for subscription payment_date: {subscription.payment_date} — {e}"
                    )
                except Exception as e:
                    logger.exception(f"Error processing failed subscription payment for profile {client.id}: {e}")

        send_payment_message.delay(
            client.id,
            msg_text("payment_failure", profile.language).format(  # type: ignore[attr-defined]
                mail=settings.EMAIL,
                tg=settings.TG_SUPPORT_CONTACT,
            ),
        )
