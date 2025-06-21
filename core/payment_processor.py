import asyncio
from decimal import Decimal, ROUND_HALF_UP
from loguru import logger

from core.cache import Cache
from core.enums import PaymentStatus
from core.exceptions import ClientNotFoundError
from core.services.workout_service import WorkoutService

from core.schemas import Payment, Client
from config.env_settings import settings
from core.services.outer.gsheets_service import GSheetsService
from core.services.payment_service import PaymentService
from core.services.profile_service import ProfileService
from apps.payments.tasks import send_payment_message
from bot.texts.text_manager import msg_text
from core.credits import uah_to_credits


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
                    send_payment_message.delay(
                        client.id,
                        msg_text("payment_success", profile.language),
                    )
                await cls.process_credit_topup(client, payment.amount)
            elif payment.status == PaymentStatus.FAILURE:
                await cls.cache.payment.set_status(client.id, payment.payment_type, PaymentStatus.FAILURE)
                profile = await cls.profile_service.get_profile(client.profile)
                if profile:
                    send_payment_message.delay(
                        client.id,
                        msg_text("payment_failure", profile.language).format(
                            mail=settings.EMAIL,
                            tg=settings.TG_SUPPORT_CONTACT,
                        ),
                    )

        except ClientNotFoundError:
            logger.error(f"Client profile not found for payment {payment.id}")

        except Exception as e:
            logger.exception(f"Payment processing failed for {payment.id}: {e}")

        finally:
            await cls.payment_service.update_payment(payment.id, {"processed": True})

    @classmethod
    async def process_credit_topup(cls, client: Client, amount: Decimal) -> None:
        credits = uah_to_credits(amount, settings.CREDIT_RATE)
        await cls.profile_service.adjust_client_credits(client.profile, credits)
        await cls.cache.client.update_client(client.id, {"credits": client.credits + credits})

    @classmethod
    async def handle_webhook_event(cls, order_id: str, status_: str, error: str = "") -> None:
        payment = await cls.payment_service.update_payment_status(order_id, status_, error)
        if not payment:
            logger.warning(f"Payment not found for order_id {order_id}")
            return
        await cls._process_payment(payment)

    @classmethod
    async def process_unclosed_payments(cls) -> None:
        try:
            payments = await cls.payment_service.get_unclosed_payments()
            if not payments:
                logger.info("No unclosed payments found")
                return

            payout_rows: list[list[str]] = []

            for payment in payments:
                try:
                    client = await cls.cache.client.get_client(payment.client_profile)  # type: ignore[attr-defined]
                    if not client or not client.assigned_to:
                        logger.warning(f"Skip payment {payment.order_id}: client/coach missing")
                        continue

                    coach_id = client.assigned_to[0]
                    coach = await cls.cache.coach.get_coach(coach_id)
                    if not coach:
                        logger.error(f"Coach {coach_id} not found for payment {payment.order_id}")
                        continue

                    amount = (payment.amount * Decimal(str(settings.COACH_PAYOUT_RATE))).quantize(
                        Decimal("0.01"), ROUND_HALF_UP
                    )

                    ok = await cls.payment_service.update_payment(
                        payment.id, {"status": PaymentStatus.CLOSED, "payout_handled": True}
                    )
                    if ok:
                        await cls.cache.payment.set_status(
                            payment.client_profile,
                            payment.payment_type,
                            PaymentStatus.CLOSED,
                            # type: ignore[attr-defined]
                        )
                    else:
                        logger.error(f"Cannot mark payment {payment.order_id} as closed")
                        continue

                    payout_rows.append(
                        [coach.name, coach.surname, coach.payment_details, payment.order_id, str(amount)]
                    )
                    logger.info(f"Payment {payment.order_id} closed, payout {amount} UAH")

                except Exception as e:
                    logger.exception(f"Failed to process payment {payment.order_id}: {e}")

            if payout_rows:
                await asyncio.to_thread(GSheetsService.create_new_payment_sheet, payout_rows)
                logger.info(f"Payout sheet created: {len(payout_rows)} rows")

        except Exception as e:
            logger.exception(f"Failed batch payout: {e}")
