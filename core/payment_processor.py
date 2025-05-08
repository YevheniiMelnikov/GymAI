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

    @classmethod
    def run(cls) -> None:
        asyncio.create_task(cls._check_payments_loop())
        asyncio.create_task(cls._schedule_unclosed_payment_check())

    @classmethod
    async def _schedule_unclosed_payment_check(cls) -> None:
        while True:
            now = datetime.now(timezone.utc)
            target_time = now.replace(day=1, hour=8, minute=0, second=0, microsecond=0)
            if now >= target_time:
                target_time += relativedelta(months=1)
            delay = (target_time - now).total_seconds()
            await asyncio.sleep(delay)
            await cls._process_unclosed_payments()

    @classmethod
    async def _process_unclosed_payments(cls) -> None:
        try:
            payments = await cls.payment_service.get_unclosed_payments()
            payments_data = []

            for payment in payments:
                client = cls.cache_manager.get_client_by_id(payment.profile)
                if not client or not client.assigned_to:
                    logger.warning(f"Skipping payment {payment.order_id} - invalid client or no assigned coaches")
                    continue

                try:
                    coach_id = client.assigned_to[0]
                    coach = cls.cache_manager.get_coach_by_id(coach_id)
                    if not coach:
                        logger.error(f"Coach {coach_id} not found for payment {payment.order_id}")
                        continue

                    payments_data.append(
                        [coach.name, coach.surname, coach.payment_details, payment.order_id, payment.amount // 2]
                    )

                    if await cls.payment_service.update_payment(payment.id, {"status": Settings.PAYMENT_STATUS_CLOSED}):
                        logger.info(f"Payment {payment.order_id} marked as closed")
                    else:
                        logger.error(f"Failed to update payment {payment.order_id}")

                except Exception as e:
                    logger.error(f"Error processing payment {payment.order_id}: {e}")
                    continue

            if payments_data:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, GSheetsService.create_new_payment_sheet, payments_data)

        except Exception as e:
            logger.error(f"Failed to process unclosed payments: {e}")

    @classmethod
    async def _check_payments_loop(cls) -> None:
        while True:
            try:
                if payments := await cls.payment_service.get_unhandled_payments():
                    await asyncio.gather(*(cls._process_payment(p) for p in payments))
            except Exception as e:
                logger.exception(f"Payment check error: {e}")
            await asyncio.sleep(Settings.PAYMENT_CHECK_INTERVAL)

    @classmethod
    async def _process_payment(cls, payment: Payment) -> None:
        try:
            profile_data = await cls.profile_service.get_profile(payment.profile)
            if not profile_data:
                logger.error(f"Profile not found for payment {payment.id}")
                return

            profile = Profile.from_dict(profile_data)
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
            subscription = cls.cache_manager.get_subscription(profile.id)
            if subscription and subscription.enabled:
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
                logger.info(f"Subscription for profile_id {profile.id} deactivated")
                return

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
        cls.cache_manager.set_client_data(profile.id, {"status": "waiting_for_subscription"})
        subscription = cls.cache_manager.get_subscription(profile.id)
        if not subscription:
            logger.error(f"Subscription not found for profile {profile.id}")
            return

        current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cls.cache_manager.update_subscription_data(profile.id, {"enabled": True, "payment_date": current_date})
        await cls.workout_service.update_subscription(
            subscription.id, {"enabled": True, "price": subscription.price, "payment_date": current_date}
        )
        if not subscription.enabled:
            client = cls.cache_manager.get_client_by_id(profile.id)
            coach_id = client.assigned_to[0]
            coach = cls.cache_manager.get_coach_by_id(coach_id)
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
        cls.cache_manager.set_client_data(profile.id, {"status": "waiting_for_program"})
        program = cls.cache_manager.get_program(profile.id)
        if not program:
            logger.error(f"Program not found for profile {profile.id}")
            return

        client = cls.cache_manager.get_client_by_id(profile.id)
        if not client or not client.assigned_to:
            logger.error(f"Invalid client or no assigned coaches for profile {profile.id}")
            return

        coach_id = client.assigned_to[0]
        coach = cls.cache_manager.get_coach_by_id(coach_id)
        if not coach:
            logger.error(f"Coach {coach_id} not found for profile {profile.id}")
            return

        await client_request(
            coach=coach,
            client=client,
            data={"request_type": "program", "workout_type": program.workout_type, "wishes": program.wishes},
        )
