import asyncio
from decimal import Decimal, ROUND_HALF_UP
from loguru import logger

from core.cache import Cache
from datetime import datetime
from core.enums import PaymentStatus, CoachType
from core.exceptions import ClientNotFoundError
from core.services.workout_service import WorkoutService

from core.schemas import Payment, Client
from config.env_settings import settings
from core.services.external.gsheets_service import GSheetsService
from core.services.payment_service import PaymentService
from core.services.profile_service import ProfileService
from apps.payments.tasks import send_payment_message
from bot.texts.text_manager import msg_text
from bot.utils.credits import uah_to_credits, available_packages


class PaymentProcessor:
    cache = Cache
    payment_service = PaymentService
    profile_service = ProfileService
    workout_service = WorkoutService

    @classmethod
    async def _process_payment(cls, payment: Payment) -> None:
        if payment.processed:
            logger.info(f"Payment {payment.id} already processed")
            return
        try:
            client = await cls.cache.client.get_client(payment.client_profile)
            if payment.status == PaymentStatus.SUCCESS:
                await cls.cache.payment.set_status(client.id, payment.payment_type, PaymentStatus.SUCCESS)
                profile = await cls.profile_service.get_profile(client.profile)
                if profile:
                    send_payment_message.delay(client.id, msg_text("payment_success", profile.language))
                await cls.process_credit_topup(client, payment.amount)
            elif payment.status == PaymentStatus.FAILURE:
                await cls.cache.payment.set_status(client.id, payment.payment_type, PaymentStatus.FAILURE)
                profile = await cls.profile_service.get_profile(client.profile)
                if profile:
                    send_payment_message.delay(
                        client.id,
                        msg_text("payment_failure", profile.language).format(
                            mail=settings.EMAIL, tg=settings.TG_SUPPORT_CONTACT
                        ),
                    )
        except ClientNotFoundError:
            logger.error(f"Client profile not found for payment {payment.id}")
        except Exception as e:
            logger.exception(f"Payment processing failed for {payment.id}: {e}")
        finally:
            await cls.payment_service.update_payment(payment.id, {"processed": True})

    @classmethod
    async def _process_payout(cls, payment: Payment) -> list[str] | None:
        try:
            client = await cls.cache.client.get_client(payment.client_profile)
            if not client or not client.assigned_to:
                logger.warning(f"Skip payment {payment.order_id}: client/coach missing")
                return None
            coach = await cls.cache.coach.get_coach(client.assigned_to[0])
            if not coach:
                logger.error(f"Coach {client.assigned_to[0]} not found for payment {payment.order_id}")
                return None
            if coach.coach_type == CoachType.ai:
                logger.info(f"Skip AI coach {coach.id} for payment {payment.order_id}")
                return None
            amount = payment.amount.quantize(Decimal("0.01"), ROUND_HALF_UP)
            ok = await cls.payment_service.update_payment(payment.id, {"payout_handled": True})
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
        except Exception as e:
            logger.exception(f"Failed to process payment {payment.order_id}: {e}")
            return None

    @classmethod
    async def process_credit_topup(cls, client: Client, amount: Decimal) -> None:
        package_map = {p.price: p.credits for p in available_packages()}
        credits = package_map.get(amount)
        if credits is None:
            credits = uah_to_credits(amount, apply_markup=False)
        await cls.profile_service.adjust_client_credits(client.profile, credits)
        await cls.cache.client.update_client(client.profile, {"credits": client.credits + credits})

    @classmethod
    async def handle_webhook_event(cls, order_id: str, status_: str, error: str = "") -> None:
        payment = await cls.payment_service.update_payment_status(order_id, status_, error)
        if not payment:
            logger.warning(f"Payment not found for order_id {order_id}")
            return
        await cls._process_payment(payment)

    @classmethod
    async def export_coach_payouts(cls) -> None:
        """Accrue coach payouts based on their monthly due amount."""
        try:
            coaches = await cls.profile_service.list_coach_profiles()
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
                await cls.profile_service.update_coach_profile(coach.id, {"payout_due": "0"})
                await cls.cache.coach.update_coach(coach.profile, {"payout_due": "0"})
            if payout_rows:
                await asyncio.to_thread(GSheetsService.create_new_payment_sheet, payout_rows)
                logger.info(f"Payout sheet created: {len(payout_rows)} rows")
        except Exception as e:
            logger.exception(f"Failed batch payout: {e}")
