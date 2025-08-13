from __future__ import annotations

from decimal import Decimal
from typing import Awaitable, Callable, Protocol

from loguru import logger

from core.enums import PaymentStatus
from core.schemas import Client, Payment
from core.services import ProfileService

from .notifications import PaymentNotifier
from .types import CacheProtocol

CreditTopupFunc = Callable[[Client, Decimal], Awaitable[None]]


class PaymentStrategy(Protocol):
    async def handle(self, payment: Payment, client: Client) -> None: ...


class SuccessPayment:
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

    async def handle(self, payment: Payment, client: Client) -> None:
        await self._cache.payment.set_status(
            client.id,
            payment.payment_type,
            PaymentStatus.SUCCESS,
        )
        profile = await self._profile_service.get_profile(client.profile)
        if not profile:
            return
        await self._credit_topup(client, payment.amount)
        self._notifier.success(client.id, profile.language)


class FailurePayment:
    def __init__(
        self,
        cache: CacheProtocol,
        profile_service: ProfileService,
        notifier: PaymentNotifier,
    ) -> None:
        self._cache = cache
        self._profile_service = profile_service
        self._notifier = notifier

    async def handle(self, payment: Payment, client: Client) -> None:
        await self._cache.payment.set_status(
            client.id,
            payment.payment_type,
            PaymentStatus.FAILURE,
        )
        profile = await self._profile_service.get_profile(client.profile)
        if profile:
            self._notifier.failure(client.id, profile.language)


class ClosedPayment:
    def __init__(self, cache: CacheProtocol) -> None:
        self._cache = cache

    async def handle(self, payment: Payment, client: Client) -> None:
        await self._cache.payment.set_status(
            client.id,
            payment.payment_type,
            PaymentStatus.CLOSED,
        )
        logger.info(f"Payment {payment.id} closed")


class PendingPayment:
    @staticmethod
    async def handle(payment: Payment, client: Client) -> None:  # pragma: no cover - no action
        logger.debug(f"Pending payment {payment.id} ignored for client {client.id}")
