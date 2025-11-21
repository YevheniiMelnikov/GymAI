from decimal import Decimal
from typing import Dict

from loguru import logger

from core.enums import PaymentStatus
from core.exceptions import ClientNotFoundError
from core.schemas import Client, Payment
from core.services.internal.profile_service import ProfileService
from core.services.internal.workout_service import WorkoutService

from core.services.internal.payment_service import PaymentService
from .strategies import (
    ClosedPayment,
    FailurePayment,
    PaymentStrategy,
    PendingPayment,
    SuccessPayment,
)
from .types import CacheProtocol, CreditService, PaymentNotifier


class PaymentProcessor:
    def __init__(
        self,
        cache: CacheProtocol,
        payment_service: PaymentService,
        profile_service: ProfileService,
        workout_service: WorkoutService,
        notifier: PaymentNotifier,
        credit_service: CreditService,
        strategies: Dict[PaymentStatus, PaymentStrategy] | None = None,
    ) -> None:
        self.cache = cache
        self.payment_service = payment_service
        self.profile_service = profile_service
        self.workout_service = workout_service
        self._credit_service = credit_service
        self.strategies = strategies or {
            PaymentStatus.SUCCESS: SuccessPayment(
                cache,
                profile_service,
                self.process_credit_topup,
                notifier,
            ),
            PaymentStatus.FAILURE: FailurePayment(cache, profile_service, notifier),
            PaymentStatus.CLOSED: ClosedPayment(cache),
            PaymentStatus.PENDING: PendingPayment(),
        }

    async def _process_payment(self, payment: Payment) -> None:
        if payment.processed:
            logger.info(f"Payment {payment.id} already processed")
            return
        try:
            client = await self.cache.client.get_client(payment.client_profile)
            strategy = self.strategies.get(payment.status)
            if strategy:
                await strategy.handle(payment, client)
                await self.payment_service.update_payment(payment.id, {"processed": True})
            else:
                logger.warning(f"No strategy for payment {payment.id} with status {payment.status}")
        except ClientNotFoundError:
            logger.error(f"Client profile not found for payment {payment.id}")
        except Exception as e:  # noqa: BLE001
            logger.exception(f"Payment processing failed for {payment.id}: {e}")

    async def process_credit_topup(self, client: Client, amount: Decimal) -> None:
        credits = self._credit_service.credits_for_amount(amount)
        await self.profile_service.adjust_client_credits(client.profile, credits)
        await self.cache.client.update_client(client.profile, {"credits": client.credits + credits})

    async def handle_webhook_event(self, order_id: str, status_: str, error: str = "") -> None:
        payment = await self.payment_service.update_payment_status(order_id, status_, error)
        if not payment:
            logger.warning(f"Payment not found for order_id {order_id}")
            return
        await self._process_payment(payment)
