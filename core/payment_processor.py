import asyncio
from datetime import datetime, timezone
from loguru import logger
from dateutil.relativedelta import relativedelta
from functions.chat import send_message, client_request
from core.cache_manager import cache_manager, CacheManager
from functions.workout_plans import cancel_subscription
from core.models import Payment, Profile
from common.settings import settings
from core.google_sheets_manager import sheets_manager
from services.payment_service import payment_service, PaymentService
from services.profile_service import profile_service, ProfileService
from services.user_service import user_service
from services.workout_service import workout_service, WorkoutService
from bot.texts.resources import MessageText
from bot.texts.text_manager import translate


class PaymentProcessor:
    def __init__(
        self,
        cache_mngr: CacheManager,
        payment_srv: PaymentService,
        profile_srv: ProfileService,
        workout_srv: WorkoutService,
    ):
        self.cache_manager = cache_mngr
        self.payment_service = payment_srv
        self.profile_service = profile_srv
        self.workout_service = workout_srv

    def run(self) -> None:
        asyncio.create_task(self._check_payments_loop())
        asyncio.create_task(self._schedule_unclosed_payment_check())

    async def _schedule_unclosed_payment_check(self) -> None:
        while True:
            now = datetime.now(timezone.utc)
            target_time = now.replace(day=1, hour=8, minute=0, second=0, microsecond=0)
            if now >= target_time:
                target_time += relativedelta(months=1)
            delay = (target_time - now).total_seconds()
            await asyncio.sleep(delay)
            await self._process_unclosed_payments()

    async def _process_unclosed_payments(self) -> None:
        try:
            payments = await self.payment_service.get_unclosed_payments()
            payments_data = []

            for payment in payments:
                client = self.cache_manager.get_client_by_id(payment.profile)
                if not client or not client.assigned_to:
                    logger.warning(f"Skipping payment {payment.order_id} - invalid client or no assigned coaches")
                    continue

                try:
                    coach_id = client.assigned_to[0]
                    coach = self.cache_manager.get_coach_by_id(coach_id)
                    if not coach:
                        logger.error(f"Coach {coach_id} not found for payment {payment.order_id}")
                        continue

                    payments_data.append(
                        [coach.name, coach.surname, coach.payment_details, payment.order_id, payment.amount // 2]
                    )

                    if await self.payment_service.update_payment(
                        payment.id, {"status": settings.PAYMENT_STATUS_CLOSED}
                    ):
                        logger.info(f"Payment {payment.order_id} marked as closed")
                    else:
                        logger.error(f"Failed to update payment {payment.order_id}")

                except Exception as e:
                    logger.error(f"Error processing payment {payment.order_id}: {e}")
                    continue

            if payments_data:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, sheets_manager.create_new_payment_sheet, payments_data)

        except Exception as e:
            logger.error(f"Failed to process unclosed payments: {e}")

    async def _check_payments_loop(self) -> None:
        while True:
            try:
                if payments := await self.payment_service.get_unhandled_payments():
                    await asyncio.gather(*(self._process_payment(p) for p in payments))
            except Exception as e:
                logger.exception(f"Payment check error: {e}")
            await asyncio.sleep(settings.PAYMENT_CHECK_INTERVAL)

    async def _process_payment(self, payment: Payment) -> None:
        try:
            profile_data = await self.profile_service.get_profile(payment.profile)
            if not profile_data:
                logger.error(f"Profile not found for payment {payment.id}")
                return

            profile = Profile.from_dict(profile_data)
            if payment.status in {settings.SUCCESS_PAYMENT_STATUS, settings.SUBSCRIBED_PAYMENT_STATUS}:
                await self._handle_successful_payment(payment, profile)
            elif payment.status == settings.FAILURE_PAYMENT_STATUS:
                await self._handle_failed_payment(payment, profile)
            await self.payment_service.update_payment(payment.id, {"handled": True})
        except Exception as e:
            logger.exception(f"Payment processing failed for {payment.id}: {e}")

    async def _handle_failed_payment(self, payment: Payment, profile: Profile) -> None:
        client = self.cache_manager.get_client_by_id(profile.id)
        if not client:
            logger.error(f"Client not found for profile {profile.id}")
            return

        if payment.payment_type == "subscription":
            subscription = self.cache_manager.get_subscription(profile.id)
            if subscription and subscription.enabled:
                payment_date = datetime.strptime(subscription.payment_date, "%Y-%m-%d")
                next_payment_date = payment_date + relativedelta(months=1)
                await send_message(
                    recipient=client,
                    text=translate(MessageText.subscription_cancel_warning, profile.language).format(
                        date=next_payment_date.strftime("%Y-%m-%d"),
                        mail=settings.DEFAULT_FROM_EMAIL,
                        tg=settings.TG_SUPPORT_CONTACT,
                    ),
                    state=None,
                    include_incoming_message=False,
                )
                await cancel_subscription(next_payment_date, profile.id, subscription.id)
                return

        await send_message(
            recipient=client,
            text=translate(MessageText.payment_failure, profile.language).format(
                mail=settings.DEFAULT_FROM_EMAIL, tg=settings.TG_SUPPORT_CONTACT
            ),
            state=None,
            include_incoming_message=False,
        )

    async def _handle_successful_payment(self, payment: Payment, profile: Profile) -> None:
        client = self.cache_manager.get_client_by_id(profile.id)
        if not client:
            logger.error(f"Client not found for profile {profile.id}")
            return

        await send_message(
            recipient=client,
            text=translate(MessageText.payment_success, profile.language),
            state=None,
            include_incoming_message=False,
        )
        logger.info(f"Profile {profile.id} successfully paid {payment.amount} UAH for {payment.payment_type}")
        if payment.payment_type == "subscription":
            await self._process_subscription_payment(profile)
        elif payment.payment_type == "program":
            await self._process_program_payment(profile)

    async def _process_subscription_payment(self, profile: Profile) -> None:
        self.cache_manager.set_client_data(profile.id, {"status": "waiting_for_subscription"})
        subscription = self.cache_manager.get_subscription(profile.id)
        if not subscription:
            logger.error(f"Subscription not found for profile {profile.id}")
            return

        current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.cache_manager.update_subscription_data(profile.id, {"enabled": True, "payment_date": current_date})
        auth_token = await user_service.get_user_token(profile.id)
        await self.workout_service.update_subscription(
            subscription.id, {"enabled": True, "price": subscription.price, "payment_date": current_date}, auth_token
        )
        if not subscription.enabled:
            client = self.cache_manager.get_client_by_id(profile.id)
            coach_id = client.assigned_to[0]
            coach = self.cache_manager.get_coach_by_id(coach_id)
            await client_request(
                coach,
                client,
                {
                    "request_type": "subscription",
                    "workout_type": subscription.workout_type,
                    "wishes": subscription.wishes,
                },
            )

    async def _process_program_payment(self, profile: Profile) -> None:
        self.cache_manager.set_client_data(profile.id, {"status": "waiting_for_program"})
        program = self.cache_manager.get_program(profile.id)
        if not program:
            logger.error(f"Program not found for profile {profile.id}")
            return

        client = self.cache_manager.get_client_by_id(profile.id)
        if not client or not client.assigned_to:
            logger.error(f"Invalid client or no assigned coaches for profile {profile.id}")
            return

        coach_id = client.assigned_to[0]
        coach = self.cache_manager.get_coach_by_id(coach_id)
        if not coach:
            logger.error(f"Coach {coach_id} not found for profile {profile.id}")
            return

        await client_request(
            coach, client, {"request_type": "program", "workout_type": program.workout_type, "wishes": program.wishes}
        )


def run():
    payment_processor = PaymentProcessor(
        cache_mngr=cache_manager,
        payment_srv=payment_service,
        profile_srv=profile_service,
        workout_srv=workout_service,
    )
    payment_processor.run()
