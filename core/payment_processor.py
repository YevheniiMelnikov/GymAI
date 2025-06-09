import asyncio
from aiogram import Bot
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone
from loguru import logger
from dateutil.relativedelta import relativedelta
from dependency_injector.wiring import inject, Provide

from core.cache import Cache
from core.enums import PaymentStatus, ClientStatus
from core.exceptions import ClientNotFoundError, CoachNotFoundError
from core.services.workout_service import WorkoutService
from bot.utils.chat import send_message, client_request
from bot.utils.workout_plans import cancel_subscription
from core.schemas import Payment, Client
from config.env_settings import settings
from core.containers import App
from core.services.outer.gsheets_service import GSheetsService
from core.services.payment_service import PaymentService
from core.services.profile_service import ProfileService
from bot.texts.text_manager import msg_text


class PaymentProcessor:
    cache = Cache
    payment_service = PaymentService
    profile_service = ProfileService
    workout_service = WorkoutService

    @classmethod
    @inject
    async def _process_payment(cls, payment: Payment, bot: Bot = Provide[App.bot]) -> None:
        if payment.processed:
            logger.info(f"Payment {payment.id} already processed")
            return

        try:
            client = await cls.cache.client.get_client(payment.client_profile)
            if payment.status == PaymentStatus.SUCCESS:
                await cls.cache.payment.set_status(client.id, payment.payment_type, PaymentStatus.SUCCESS)
                await cls._handle_successful_payment(payment, client, bot)
            elif payment.status == PaymentStatus.FAILURE:
                await cls.cache.payment.set_status(client.id, payment.payment_type, PaymentStatus.FAILURE)
                await cls._handle_failed_payment(payment, client, bot)

        except ClientNotFoundError:
            logger.error(f"Client profile not found for payment {payment.id}")

        except Exception as e:
            logger.exception(f"Payment processing failed for {payment.id}: {e}")

        finally:
            await cls.payment_service.update_payment(payment.id, {"processed": True})

    @classmethod
    @inject
    async def _handle_failed_payment(cls, payment: Payment, client: Client, bot: Bot = Provide[App.bot]) -> None:
        profile = await cls.profile_service.get_profile(client.profile)
        if not profile:
            logger.error(f"Profile not found for client {client.id}")
            return

        if payment.payment_type == "subscription":
            subscription = await cls.cache.workout.get_latest_subscription(client.id)
            if subscription and subscription.enabled:
                try:
                    payment_date = datetime.strptime(subscription.payment_date, "%Y-%m-%d")
                    next_payment_date = payment_date + relativedelta(months=1)
                    await send_message(
                        recipient=client,
                        text=msg_text("subscription_cancel_warning", profile.language).format(
                            # type: ignore[attr-defined]
                            date=next_payment_date.strftime("%Y-%m-%d"),
                            mail=settings.EMAIL,
                            tg=settings.TG_SUPPORT_CONTACT,
                        ),
                        bot=bot,
                        state=None,
                        include_incoming_message=False,
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

        await send_message(
            recipient=client,
            text=msg_text("payment_failure", profile.language).format(  # type: ignore[attr-defined]
                mail=settings.EMAIL, tg=settings.TG_SUPPORT_CONTACT
            ),
            bot=bot,
            state=None,
            include_incoming_message=False,
        )

    @classmethod
    @inject
    async def _handle_successful_payment(cls, payment: Payment, client: Client, bot: Bot = Provide[App.bot]) -> None:
        profile = await cls.profile_service.get_profile(client.profile)
        if not profile:
            logger.error(f"Profile not found for client {client.id}")
            return

        await send_message(
            recipient=client,
            text=msg_text("payment_success", profile.language),  # type: ignore[attr-defined]
            bot=bot,
            state=None,
            include_incoming_message=False,
        )
        logger.info(f"Client {client.id} successfully paid {payment.amount} UAH for {payment.payment_type}")

        if payment.payment_type == "subscription":
            await cls._process_subscription_payment(client, bot)
        elif payment.payment_type == "program":
            await cls._process_program_payment(client, bot)

    @classmethod
    @inject
    async def _process_subscription_payment(cls, client: Client, bot: Bot = Provide[App.bot]) -> None:
        await cls.cache.client.update_client(client.id, {"status": ClientStatus.waiting_for_subscription})
        subscription = await cls.cache.workout.get_latest_subscription(client.id)
        if not subscription:
            logger.error(f"Subscription not found for client {client.id}")
            return

        current_date = datetime.now(timezone.utc).date().isoformat()

        await cls.workout_service.update_subscription(
            subscription.id,
            {"enabled": True, "price": subscription.price, "payment_date": current_date},
        )
        await cls.cache.workout.update_subscription(client.id, {"enabled": True, "payment_date": current_date})

        if not subscription.enabled:
            coach_id = client.assigned_to[0]
            try:
                coach = await cls.cache.coach.get_coach(coach_id)
            except CoachNotFoundError:
                logger.error(f"Coach {coach_id} not found for client {client.id}")
                return

            await client_request(
                coach,
                client,
                {
                    "service_type": "subscription",
                    "workout_type": subscription.workout_type,
                    "wishes": subscription.wishes,
                },
                bot=bot,
            )

    @classmethod
    @inject
    async def _process_program_payment(cls, client: Client, bot: Bot = Provide[App.bot]) -> None:
        await cls.cache.client.update_client(client.id, {"status": ClientStatus.waiting_for_program})
        program = await cls.cache.workout.get_program(client.id)
        if not program:
            logger.error(f"Program not found for client {client.id}")
            return

        coach_id = client.assigned_to[0]
        coach = await cls.cache.coach.get_coach(coach_id)
        if not coach:
            logger.error(f"Coach {coach_id} not found for client {client.id}")
            return

        await client_request(
            coach=coach,
            client=client,
            data={"service_type": "program", "workout_type": program.workout_type, "wishes": program.wishes},
            bot=bot,
        )

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
