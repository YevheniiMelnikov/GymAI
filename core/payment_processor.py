from __future__ import annotations

import asyncio
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict

from loguru import logger

from core.cache import Cache
from core.enums import CoachType, PaymentStatus
from core.exceptions import ClientNotFoundError
from core.schemas import Client, Payment
from core.services import ProfileService, WorkoutService
from core.services.gsheets_service import GSheetsService
from core.services.internal.payment_service import PaymentService
from bot.utils.credits import available_packages, uah_to_credits
from bot.utils.profiles import get_assigned_coach
from core.payment.notifications import PaymentNotifier, TaskPaymentNotifier
from core.payment.strategies import (
    ClosedPayment,
    FailurePayment,
    PaymentStrategy,
    PendingPayment,
    SuccessPayment,
)


class PaymentProcessor:
    def __init__(
        self,
        cache: Cache,
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

    async def _process_payout(self, payment: Payment) -> list[str] | None:
        try:
            client = await self.cache.client.get_client(payment.client_profile)
            if not client or not client.assigned_to:
                logger.warning(f"Skip payment {payment.order_id}: client/coach missing")
                return None
            coach = await get_assigned_coach(client, coach_type=CoachType.human)
            if not coach:
                logger.error(f"Coach not found for payment {payment.order_id}")
                return None
            if coach.coach_type == CoachType.ai:
                logger.info(f"Skip AI coach {coach.id} for payment {payment.order_id}")
                return None
            amount = payment.amount.quantize(Decimal("0.01"), ROUND_HALF_UP)
            ok = await self.payment_service.update_payment(payment.id, {"payout_handled": True})
            if not ok:
                logger.error(f"Cannot mark payment {payment.order_id} as handled")
                return None
            logger.info(f"Payment {payment.order_id} processed, payout {amount} UAH")
            return [
                coach.name or "",
                coach.surname or "",
                coach.payment_details or "",
                payment.order_id,
                str(amount),
            ]
        except Exception as e:  # noqa: BLE001
            logger.exception(f"Failed to process payment {payment.order_id}: {e}")
            return None

    async def process_credit_topup(self, client: Client, amount: Decimal) -> None:
        package_map = {p.price: p.credits for p in available_packages()}
        credits = package_map.get(amount)
        if credits is None:
            credits = uah_to_credits(amount, apply_markup=False)
        await self.profile_service.adjust_client_credits(client.profile, credits)
        await self.cache.client.update_client(client.profile, {"credits": client.credits + credits})

    async def handle_webhook_event(self, order_id: str, status_: str, error: str = "") -> None:
        payment = await self.payment_service.update_payment_status(order_id, status_, error)
        if not payment:
            logger.warning(f"Payment not found for order_id {order_id}")
            return
        await self._process_payment(payment)

    async def export_coach_payouts(self) -> None:
        """Accrue coach payouts based on their monthly due amount."""
        try:
            coaches = await self.profile_service.list_coach_profiles()
            payout_rows = []
            for coach in coaches:
                if coach.coach_type == CoachType.ai:
                    continue
                amount = (coach.payout_due or Decimal("0")).quantize(Decimal("0.01"), ROUND_HALF_UP)
                if amount <= 0:
                    continue
                payout_rows.append(
                    [
                        coach.name or "",
                        coach.surname or "",
                        coach.payment_details_plain,
                        datetime.today().strftime("%Y-%m"),
                        str(amount),
                    ]
                )
                await self.profile_service.update_coach_profile(coach.id, {"payout_due": "0"})
                await self.cache.coach.update_coach(coach.profile, {"payout_due": "0"})
            if payout_rows:
                await asyncio.to_thread(GSheetsService.create_new_payment_sheet, payout_rows)
                logger.info(f"Payout sheet created: {len(payout_rows)} rows")
        except Exception as e:  # noqa: BLE001
            logger.exception(f"Failed batch payout: {e}")


payment_processor = PaymentProcessor(
    cache=Cache,
    payment_service=PaymentService,
    profile_service=ProfileService,
    workout_service=WorkoutService,
    notifier=TaskPaymentNotifier(),
)
