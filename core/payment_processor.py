import asyncio
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone
from loguru import logger
from dateutil.relativedelta import relativedelta

from core.cache import Cache
from core.services.workout_service import WorkoutService
from bot.utils.chat import send_message, client_request
from bot.utils.workout_plans import cancel_subscription
from core.models import Payment, Profile
from config.env_settings import Settings
from core.services.outer.gsheets_service import GSheetsService
from core.services.payment_service import PaymentService
from core.services.profile_service import ProfileService
from bot.texts.text_manager import msg_text


class PaymentProcessor:
    cache = Cache
    payment_service = PaymentService
    profile_service = ProfileService
    workout_service = WorkoutService

    STATUS_WAITING_FOR_SUBSCRIPTION = "waiting_for_subscription"
    STATUS_WAITING_FOR_PROGRAM = "waiting_for_program"

    @classmethod
    async def _process_payment(cls, payment: Payment) -> None:
        if payment.handled:
            logger.info(f"Payment {payment.id} already handled")
            return
        try:
            profile = await cls.profile_service.get_profile(payment.profile)
            if not profile:
                logger.error(f"Profile not found for payment {payment.id}")
                return

            if payment.status in {Settings.SUCCESS_PAYMENT_STATUS, Settings.SUBSCRIBED_PAYMENT_STATUS}:
                await cls._handle_successful_payment(payment, profile)
            elif payment.status == Settings.FAILURE_PAYMENT_STATUS:
                await cls._handle_failed_payment(payment, profile)
        except Exception as e:
            logger.exception(f"Payment processing failed for {payment.id}: {e}")
        finally:
            await cls.payment_service.update_payment(payment.id, {"handled": True})

    @classmethod
    async def _handle_failed_payment(cls, payment: Payment, profile: Profile) -> None:
        client = await cls.cache.client.get_client(profile.id)
        if not client:
            logger.error(f"Client not found for profile {profile.id}")
            return

        if payment.payment_type == "subscription":
            subscription = await cls.cache.workout.get_subscription(profile.id)
            if subscription and subscription.enabled:
                try:
                    payment_date = datetime.strptime(subscription.payment_date, "%Y-%m-%d")
                    next_payment_date = payment_date + relativedelta(months=1)
                    await send_message(
                        recipient=client,
                        text=msg_text("subscription_cancel_warning", profile.language).format(
                            date=next_payment_date.strftime("%Y-%m-%d"),
                            mail=Settings.EMAIL,
                            tg=Settings.TG_SUPPORT_CONTACT,
                        ),
                        state=None,
                        include_incoming_message=False,
                    )
                    await cancel_subscription(next_payment_date, profile.id, subscription.id)
                    logger.info(f"Subscription for profile_id {profile.id} deactivated due to failed payment")
                    return
                except ValueError as e:
                    logger.error(
                        f"Invalid date format for subscription payment_date: {subscription.payment_date} — {e}"
                    )
                except Exception as e:
                    logger.exception(f"Error processing failed subscription payment for profile {profile.id}: {e}")

        await send_message(
            recipient=client,
            text=msg_text("payment_failure", profile.language).format(
                mail=Settings.EMAIL, tg=Settings.TG_SUPPORT_CONTACT
            ),
            state=None,
            include_incoming_message=False,
        )

    @classmethod
    async def _handle_successful_payment(cls, payment: Payment, profile: Profile) -> None:
        client = await cls.cache.client.get_client(profile.id)
        if not client:
            logger.error(f"Client not found for profile {profile.id}")
            return

        await send_message(
            recipient=client,
            text=msg_text("payment_success", profile.language),
            state=None,
            include_incoming_message=False,
        )
        logger.info(f"Profile {profile.id} successfully paid {payment.amount} UAH for {payment.payment_type}")
        if payment.payment_type == "subscription":
            await cls._process_subscription_payment(profile)
        elif payment.payment_type == "program":
            await cls._process_program_payment(profile)

    @classmethod
    async def _process_subscription_payment(cls, profile: Profile) -> None:
        await cls.cache.client.update_client(profile.id, {"status": cls.STATUS_WAITING_FOR_SUBSCRIPTION})
        subscription = await cls.cache.workout.get_subscription(profile.id)
        if not subscription:
            logger.error(f"Subscription not found for profile {profile.id}")
            return

        current_date = datetime.now(timezone.utc).date().isoformat()
        was_enabled = subscription.enabled

        await cls.workout_service.update_subscription(
            subscription.id,
            {"enabled": True, "price": subscription.price, "payment_date": current_date},
        )
        await cls.cache.workout.update_subscription(profile.id, {"enabled": True, "payment_date": current_date})

        if not was_enabled:
            client = await cls.cache.client.get_client(profile.id)
            if not client or not client.assigned_to:
                logger.error(
                    f"Cannot activate subscription for profile {profile.id} — client or assigned coach missing"
                )
                return

            coach_id = client.assigned_to[0]
            coach = await cls.cache.coach.get_coach(coach_id)
            if not coach:
                logger.error(f"Coach {coach_id} not found for profile {profile.id}")
                return

            await client_request(
                coach,
                client,
                {
                    "request_type": "subscription",
                    "workout_type": subscription.workout_type,
                    "wishes": subscription.wishes,
                },
            )

    @classmethod
    async def _process_program_payment(cls, profile: Profile) -> None:
        await cls.cache.client.update_client(profile.id, {"status": cls.STATUS_WAITING_FOR_PROGRAM})
        program = await cls.cache.workout.get_program(profile.id)
        if not program:
            logger.error(f"Program not found for profile {profile.id}")
            return

        client = await cls.cache.client.get_client(profile.id)
        if not client or not client.assigned_to:
            logger.error(f"Client or coach not found for profile {profile.id}")
            return

        coach_id = client.assigned_to[0]
        coach = await cls.cache.coach.get_coach(coach_id)
        if not coach:
            logger.error(f"Coach {coach_id} not found for profile {profile.id}")
            return

        await client_request(
            coach=coach,
            client=client,
            data={"request_type": "program", "workout_type": program.workout_type, "wishes": program.wishes},
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

            payout_data: list[list[str]] = []

            for payment in payments:
                try:
                    client = await cls.cache.client.get_client(payment.profile)
                    if not client or not client.assigned_to:
                        logger.warning(f"Skipping payment {payment.order_id} — client or assigned coach missing")
                        continue

                    coach_id = client.assigned_to[0]
                    coach = await cls.cache.coach.get_coach(coach_id)
                    if not coach:
                        logger.error(f"Coach {coach_id} not found for payment {payment.order_id}")
                        continue

                    amount = (payment.amount * Decimal(str(Settings.COACH_PAYOUT_RATE))).quantize(
                        Decimal("0.01"), ROUND_HALF_UP
                    )

                    update_success = await cls.payment_service.update_payment(
                        payment.id, {"status": Settings.PAYMENT_STATUS_CLOSED, "handled": True}
                    )
                    if not update_success:
                        logger.error(f"Failed to mark payment {payment.order_id} as closed")
                        continue

                    payout_data.append(
                        [coach.name, coach.surname, coach.payment_details, payment.order_id, str(amount)]
                    )
                    logger.info(f"Payment {payment.order_id} marked as closed, payout: {amount} UAH")

                except Exception as inner_error:
                    logger.exception(f"Failed to process payment {payment.order_id}: {inner_error}")

            if payout_data:
                await asyncio.to_thread(GSheetsService.create_new_payment_sheet, payout_data)
                logger.info(f"Payout sheet created with {len(payout_data)} records")

        except Exception as outer_error:
            logger.exception(f"Failed to process unclosed payments batch: {outer_error}")
