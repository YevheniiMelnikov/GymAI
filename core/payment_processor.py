import asyncio
from datetime import datetime, timezone
from loguru import logger
from dateutil.relativedelta import relativedelta

from core.services.workout_service import WorkoutService
from functions.chat import send_message, client_request
from core.cache_manager import CacheManager
from functions.workout_plans import cancel_subscription
from core.models import Payment, Profile
from config.env_settings import Settings
from core.services.gsheets_service import GSheetsService
from core.services.payment_service import PaymentService
from core.services.profile_service import ProfileService
from bot.texts.text_manager import msg_text


class PaymentProcessor:
    cache_manager = CacheManager
    payment_service = PaymentService
    profile_service = ProfileService
    workout_service = WorkoutService

    STATUS_WAITING_FOR_SUBSCRIPTION = "waiting_for_subscription"
    STATUS_WAITING_FOR_PROGRAM = "waiting_for_program"

    @classmethod
    async def _process_payment(cls, payment: Payment) -> None:
        try:
            profile = await cls.profile_service.get_profile(payment.profile)
            if not profile:
                logger.error(f"Profile not found for payment {payment.id}")
                return

            if payment.status in {Settings.SUCCESS_PAYMENT_STATUS, Settings.SUBSCRIBED_PAYMENT_STATUS}:
                await cls._handle_successful_payment(payment, profile)
            elif payment.status == Settings.FAILURE_PAYMENT_STATUS:
                await cls._handle_failed_payment(payment, profile)
            await cls.payment_service.update_payment(payment.id, {"handled": True})
        except Exception as e:
            logger.exception(f"Payment processing failed for {payment.id}: {e}")

    @classmethod
    async def _handle_failed_payment(cls, payment: Payment, profile: Profile) -> None:
        client = cls.cache_manager.get_client_by_id(profile.id)
        if not client:
            logger.error(f"Client not found for profile {profile.id}")
            return

        if payment.payment_type == "subscription":
            sub = cls.cache_manager.get_subscription(profile.id)
            if sub and sub.enabled:
                try:
                    payment_date = datetime.strptime(sub.payment_date, "%Y-%m-%d")
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
                    await cancel_subscription(next_payment_date, profile.id, sub.id)
                    logger.info(f"Subscription for profile_id {profile.id} deactivated due to failed payment")
                    return
                except ValueError as e:
                    logger.error(
                        f"Invalid date format for subscription {sub.id} payment_date: {sub.payment_date}. Error: {e}"
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
        client = cls.cache_manager.get_client_by_id(profile.id)
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
        cls.cache_manager.set_client_data(profile.id, {"status": cls.STATUS_WAITING_FOR_SUBSCRIPTION})
        subscription = cls.cache_manager.get_subscription(profile.id)
        if not subscription:
            logger.error(f"Subscription not found for profile {profile.id}")
            return

        current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        was_enabled_before_update = subscription.enabled

        cls.cache_manager.update_subscription_data(profile.id, {"enabled": True, "payment_date": current_date})
        await cls.workout_service.update_subscription(
            subscription.id, {"enabled": True, "price": subscription.price, "payment_date": current_date}
        )
        if not was_enabled_before_update:
            client = cls.cache_manager.get_client_by_id(profile.id)
            if not client:
                logger.error(f"Client not found for profile {profile.id} when processing new subscription activation")
                return

            if not client.assigned_to:
                logger.error(f"Client {profile.id} has no assigned coaches for subscription activation request")
                return

            coach_id = client.assigned_to[0]
            coach = cls.cache_manager.get_coach_by_id(coach_id)
            if not coach:
                logger.error(f"Coach {coach_id} not found for profile {profile.id} during subscription activation")
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
        cls.cache_manager.set_client_data(profile.id, {"status": cls.STATUS_WAITING_FOR_PROGRAM})
        program = cls.cache_manager.get_program(profile.id)
        if not program:
            logger.error(f"Program not found for profile {profile.id}")
            return

        client = cls.cache_manager.get_client_by_id(profile.id)
        if not client or not client.assigned_to:
            logger.error(f"Invalid client or no assigned coaches for profile {profile.id} for program payment")
            return

        coach_id = client.assigned_to[0]
        coach = cls.cache_manager.get_coach_by_id(coach_id)
        if not coach:
            logger.error(f"Coach {coach_id} not found for profile {profile.id} during program payment")
            return

        await client_request(
            coach=coach,
            client=client,
            data={"request_type": "program", "workout_type": program.workout_type, "wishes": program.wishes},
        )

    @classmethod
    async def handle_webhook_event(cls, order_id: str, status_: str, error: str = "") -> None:
        payment: Payment = await cls.payment_service.update_status_by_order(order_id, status_, error)
        if not payment:
            logger.warning(f"Payment not found for order_id {order_id} during webhook event or update failed")
            return

        await cls._process_payment(payment)

    @classmethod
    async def process_unclosed_payments(cls) -> None:
        try:
            payments = await cls.payment_service.get_unclosed_payments()
            coach_payout_data = []

            for payment in payments:
                client = cls.cache_manager.get_client_by_id(payment.profile)
                if not client:
                    logger.warning(
                        f"Skipping unclosed payment {payment.order_id} - client {payment.profile} not found in cache"
                    )
                    continue

                if not client.assigned_to:
                    logger.warning(
                        f"Skipping unclosed payment {payment.order_id} for client {payment.profile} - no assigned coaches"  # noqa
                    )
                    continue

                try:
                    coach_id = client.assigned_to[0]
                    coach = cls.cache_manager.get_coach_by_id(coach_id)
                    if not coach:
                        logger.error(
                            f"Coach {coach_id} not found for payment {payment.order_id}, client {payment.profile}"
                        )
                        continue

                    if await cls.payment_service.update_payment(payment.id, {"status": Settings.PAYMENT_STATUS_CLOSED}):
                        logger.info(f"Payment {payment.order_id} marked as closed")
                        payout_amount = int(payment.amount * Settings.COACH_PAYOUT_RATE)
                        coach_payout_data.append(
                            [coach.name, coach.surname, coach.payment_details, payment.order_id, payout_amount]
                        )
                    else:
                        logger.error(
                            f"Failed to update payment {payment.order_id} status to closed"
                        )

                except Exception as e:
                    logger.error(
                        f"Error processing unclosed payment {payment.order_id} for client {payment.profile}: {e}"
                    )
                    continue

            if coach_payout_data:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, GSheetsService.create_new_payment_sheet, coach_payout_data)

        except Exception as e:
            logger.error(f"Failed to process unclosed payments: {e}")
