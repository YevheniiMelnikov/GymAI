from decimal import Decimal, ROUND_HALF_UP
from typing import Dict

from loguru import logger

from core.enums import PaymentStatus
from core.exceptions import ProfileNotFoundError
from core.schemas import Payment, Profile
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
from .types import CacheProtocol, PaymentNotifier
from bot.utils.credits import available_packages


class PaymentProcessor:
    def __init__(
        self,
        cache: CacheProtocol,
        payment_service: PaymentService,
        profile_service: ProfileService,
        workout_service: WorkoutService,
        notifier: PaymentNotifier,
        strategies: Dict[PaymentStatus, PaymentStrategy] | None = None,
    ) -> None:
        self.cache = cache
        self.payment_service = payment_service
        self.profile_service = profile_service
        self.workout_service = workout_service
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
            profile = await self.cache.profile.get_record(payment.profile)
            strategy = self.strategies.get(payment.status)
            if strategy:
                await strategy.handle(payment, profile)
                await self.payment_service.update_payment(payment.id, {"processed": True})
            else:
                logger.warning(f"No strategy for payment {payment.id} with status {payment.status}")
        except ProfileNotFoundError:
            logger.error(f"Profile not found for payment {payment.id}")
        except Exception as e:  # noqa: BLE001
            logger.exception(f"Payment processing failed for {payment.id}: {e}")

    async def process_credit_topup(self, profile: Profile, amount: Decimal) -> None:
        normalized = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        package_map = {package.price: package.credits for package in available_packages()}
        credits = package_map.get(normalized)
        if credits is None:
            message = f"Unsupported payment amount for credits: {normalized}"
            logger.error(message)
            raise ValueError(message)
        await self.profile_service.adjust_credits(profile.id, credits)
        await self.cache.profile.update_record(profile.id, {"credits": profile.credits + credits})

    async def handle_webhook_event(self, order_id: str, status_: str, error: str = "") -> None:
        payment = await self.payment_service.update_payment_status(order_id, status_, error)
        if not payment:
            logger.warning(f"Payment not found for order_id {order_id}")
            return
        await self._process_payment(payment)
