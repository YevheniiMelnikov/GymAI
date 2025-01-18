import asyncio
import os
from datetime import datetime, timezone

import loguru
from dateutil.relativedelta import relativedelta

from common.sheets_manager import sheets_manager
from functions.chat import send_message, client_request
from services.backend_service import backend_service
from common.cache_manager import cache_manager
from functions.workout_plans import cancel_subscription
from common.models import Payment, Profile
from common.settings import (
    SUCCESS_PAYMENT_STATUS,
    FAILURE_PAYMENT_STATUS,
    PAYMENT_CHECK_INTERVAL,
    SUBSCRIBED_PAYMENT_STATUS,
    PAYMENT_STATUS_CLOSED,
)
from services.payment_service import payment_service
from services.profile_service import profile_service
from services.user_service import user_service
from services.workout_service import workout_service
from bot.texts.resources import MessageText
from bot.texts.text_manager import translate

logger = loguru.logger


class PaymentHandler:
    def __init__(self):
        self.cache_manager = cache_manager
        self.backend_service = backend_service
        self.payment_service = payment_service
        self.profile_service = profile_service
        self.workout_service = workout_service

    def start_payment_checker(self) -> None:
        asyncio.create_task(self.check_payments())
        asyncio.create_task(self.schedule_unclosed_payment_check())

    async def schedule_unclosed_payment_check(self) -> None:
        while True:
            now = datetime.now(timezone.utc)
            target_time = now.replace(day=1, hour=8, minute=0, second=0, microsecond=0)

            if now >= target_time:
                target_time += relativedelta(months=1)

            delay = (target_time - now).total_seconds()
            logger.debug(f"Scheduled unclosed payment processing at {target_time.isoformat()} UTC (in {delay} seconds)")
            await asyncio.sleep(delay)

            await self.process_unclosed_payments()

    async def process_unclosed_payments(self) -> None:
        payments_data = []

        for payment in await self.payment_service.get_unclosed_payments():
            try:
                client = self.cache_manager.get_client_by_id(payment.profile)
                coach = self.cache_manager.get_coach_by_id(client.assigned_to.pop())

                payments_data.append(
                    [coach.name, coach.surname, coach.payment_details, payment.order_id, payment.amount // 2]
                )

                if await self.payment_service.update_payment(payment.id, dict(status=PAYMENT_STATUS_CLOSED)):
                    logger.info(f"Payment {payment.order_id} marked as {PAYMENT_STATUS_CLOSED}")
            except Exception as e:
                logger.error(f"Error processing payment {payment.order_id}: {e}", exc_info=True)

        if payments_data:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, sheets_manager.create_new_payment_sheet, payments_data)

    async def check_payments(self) -> None:
        while True:
            try:
                if payments := await self.payment_service.get_unhandled_payments():
                    tasks = [self.process_payment(payment) for payment in payments]
                    await asyncio.gather(*tasks)
                await asyncio.sleep(PAYMENT_CHECK_INTERVAL)
            except Exception as e:
                logger.exception(f"Error in periodic payment check: {e}")
                await asyncio.sleep(PAYMENT_CHECK_INTERVAL)

    async def process_payment(self, payment: Payment) -> None:
        try:
            profile_data = await self.profile_service.get_profile(payment.profile)
            if profile_data is None:
                logger.error(f"Profile not found for payment_id {payment.id}")
                return

            profile = Profile.from_dict(profile_data)
            if payment.status == SUCCESS_PAYMENT_STATUS or payment.status == SUBSCRIBED_PAYMENT_STATUS:
                await self.handle_successful_payment(payment, profile)
            elif payment.status == FAILURE_PAYMENT_STATUS:
                await self.handle_failed_payment(payment, profile)

        except Exception as e:
            logger.exception(f"Error processing payment {payment.id}: {e}")

    async def handle_failed_payment(self, payment: Payment, profile: Profile) -> None:
        client = self.cache_manager.get_client_by_id(profile.id)
        await self.payment_service.update_payment(payment.id, dict(handled=True, status=FAILURE_PAYMENT_STATUS))
        if payment.payment_type == "subscription":
            subscription = self.cache_manager.get_subscription(profile.id)
            if subscription and subscription.enabled:
                payment_date = datetime.strptime(subscription.payment_date, "%Y-%m-%d")
                next_payment_date = payment_date + relativedelta(months=1)
                await send_message(
                    recipient=client,
                    text=translate(MessageText.subscription_cancel_warning, profile.language).format(
                        date=next_payment_date.strftime("%Y-%m-%d"),
                        mail=os.getenv("DEFAULT_FROM_EMAIL"),
                        tg=os.getenv("TG_SUPPORT_CONTACT"),
                    ),
                    state=None,
                    include_incoming_message=False,
                )
                await cancel_subscription(next_payment_date, profile.id, subscription.id)
                return

        await send_message(
            recipient=client,
            text=translate(MessageText.payment_failure, profile.language).format(
                mail=os.getenv("DEFAULT_FROM_EMAIL"), tg=os.getenv("TG_SUPPORT_CONTACT")
            ),
            state=None,
            include_incoming_message=False,
        )

    async def handle_successful_payment(self, payment: Payment, profile: Profile) -> None:
        try:
            updated = await self.payment_service.update_payment(
                payment.id, dict(handled=True, status=SUCCESS_PAYMENT_STATUS)
            )
            if not updated:
                logger.error(f"Failed to update payment status for {payment.id}")
                return

            client = self.cache_manager.get_client_by_id(profile.id)
            if client is None:
                logger.error(f"Client not found for profile_id {profile.id}")
                return

            await send_message(
                recipient=client,
                text=translate(MessageText.payment_success, profile.language),
                state=None,
                include_incoming_message=False,
            )

            logger.info(f"Profile {profile.id} successfully payed {payment.amount} UAH for {payment.payment_type}")
            if payment.payment_type == "subscription":
                await self.process_subscription_payment(profile)
            else:
                await self.process_program_payment(profile)
        except Exception as e:
            logger.exception(f"Failed to handle successful payment {payment.id}: {e}")

    async def process_subscription_payment(self, profile: Profile) -> None:
        try:
            self.cache_manager.set_client_data(profile.id, {"status": "waiting_for_subscription"})
            subscription = self.cache_manager.get_subscription(profile.id)
            if subscription is None:
                logger.error(f"Subscription not found for profile_id {profile.id}")
                return

            current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            self.cache_manager.update_subscription_data(
                profile.id, {"client_profile": profile.id, "enabled": True, "payment_date": current_date}
            )
            auth_token = await user_service.get_user_token(profile.id)
            await self.workout_service.update_subscription(
                subscription.id,
                {
                    "enabled": True,
                    "price": subscription.price,
                    "user": profile.id,
                    "payment_date": current_date,
                },
                auth_token,
            )
            data = {
                "request_type": "subscription",
                "workout_type": subscription.workout_type,
                "wishes": subscription.wishes,
            }
            if not subscription.enabled:
                client = self.cache_manager.get_client_by_id(profile.id)
                coach = self.cache_manager.get_coach_by_id(client.assigned_to.pop())
                await client_request(coach, client, data)
        except Exception as e:
            logger.exception(f"Subscription payment processing failed for profile_id {profile.id}: {e}")

    async def process_program_payment(self, profile: Profile) -> None:
        try:
            self.cache_manager.set_client_data(profile.id, {"status": "waiting_for_program"})
            program = self.cache_manager.get_program(profile.id)
            if program is None:
                logger.error(f"Program not found for profile_id {profile.id}")
                return

            data = {
                "request_type": "program",
                "workout_type": program.workout_type,
                "wishes": program.wishes,
            }
            client = self.cache_manager.get_client_by_id(profile.id)
            if client is None:
                logger.error(f"Client not found for profile_id {profile.id}")
                return

            if coach := self.cache_manager.get_coach_by_id(client.assigned_to.pop()):
                await client_request(coach, client, data)
        except Exception as e:
            logger.exception(f"Program payment processing failed for profile_id {profile.id}: {e}")


payment_handler = PaymentHandler()
