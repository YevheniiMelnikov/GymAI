from decimal import Decimal
from typing import Awaitable, Callable, Protocol

from loguru import logger

from core.enums import PaymentStatus
from core.schemas import Payment, Profile
from core.services import ProfileService

from .types import CacheProtocol, PaymentNotifier

CreditTopupFunc = Callable[[Profile, Decimal], Awaitable[int]]


class PaymentStrategy(Protocol):
    async def handle(self, payment: Payment, client: Profile) -> None: ...


class SuccessPayment:
    """Handle successful payments by topping up credits and notifying users."""

    def __init__(
        self,
        cache: CacheProtocol,
        profile_service: ProfileService,
        credit_topup: CreditTopupFunc,
        notifier: PaymentNotifier,
    ) -> None:
        self._cache = cache
        self._profile_service = profile_service
        self._credit_topup = credit_topup
        self._notifier = notifier

    async def handle(self, payment: Payment, profile: Profile) -> None:
        await self._cache.payment.set_status(
            profile.id,
            payment.payment_type,
            PaymentStatus.SUCCESS,
        )

        credits = await self._credit_topup(profile, payment.amount)
        self._notifier.success(profile.id, profile.language, credits)


class FailurePayment:
    """Handle failed payments by caching status and notifying users."""

    def __init__(
        self,
        cache: CacheProtocol,
        profile_service: ProfileService,
        notifier: PaymentNotifier,
    ) -> None:
        self._cache = cache
        self._profile_service = profile_service
        self._notifier = notifier

    async def handle(self, payment: Payment, profile: Profile) -> None:
        await self._cache.payment.set_status(
            profile.id,
            payment.payment_type,
            PaymentStatus.FAILURE,
        )
        logger.warning(
            "payment_failed "
            f"payment_id={payment.id} order_id={payment.order_id} profile_id={profile.id} "
            f"status={payment.status} error={payment.error}"
        )
        self._notifier.failure(profile.id, profile.language)


class ClosedPayment:
    """Handle closed payments by caching closed status."""

    def __init__(self, cache: CacheProtocol) -> None:
        self._cache = cache

    async def handle(self, payment: Payment, profile: Profile) -> None:
        await self._cache.payment.set_status(
            profile.id,
            payment.payment_type,
            PaymentStatus.CLOSED,
        )
        logger.info(f"Payment {payment.id} closed")


class PendingPayment:
    """Ignore pending payments while keeping status untouched."""

    @staticmethod
    async def handle(payment: Payment, profile: Profile) -> None:
        logger.debug(f"Pending payment {payment.id} ignored for client {profile.id}")
