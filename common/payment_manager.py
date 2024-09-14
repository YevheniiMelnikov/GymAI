import asyncio
import os
from datetime import datetime, timezone

import loguru
from dateutil.relativedelta import relativedelta

from services.backend_service import backend_service
from common.cache_manager import cache_manager
from common.functions.chat import client_request, send_message
from common.functions.workout_plans import cancel_subscription
from common.models import Payment, Profile
from common.settings import PAYMENT_STATUS_PAYED, PAYMENT_STATUS_REJECTED
from services.payment_service import payment_service
from services.profile_service import profile_service
from services.workout_service import workout_service
from texts.resources import MessageText
from texts.text_manager import translate

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

    async def check_payments(self) -> None:
        while True:
            try:
                payments = await self.payment_service.get_unhandled_payments()

                for payment in payments:
                    local_payment = await self.backend_service.check_local_payment(payment.shop_order_number)
                    profile_data = await self.profile_service.get_profile(payment.profile)
                    if not profile_data:
                        logger.error(f"Profile not found for payment {payment.id}")
                        continue
                    profile = Profile.from_dict(profile_data)

                    if local_payment.status == PAYMENT_STATUS_PAYED:
                        await self.handle_successful_payment(payment, profile)
                    elif local_payment.status == PAYMENT_STATUS_REJECTED:
                        await self.handle_failed_payment(payment, profile)

                await asyncio.sleep(60)

            except Exception as e:
                logger.exception(f"Error in periodic payment check: {e}")
                await asyncio.sleep(60)

    async def handle_failed_payment(self, payment: Payment, profile: Profile) -> None:
        client = self.cache_manager.get_client_by_id(profile.id)
        await self.payment_service.update_payment(payment.id, dict(handled=True))
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
        await self.payment_service.update_payment(payment.id, {"handled": True})
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

        if payment.payment_type == "subscription":
            await self.process_subscription_payment(profile)
        else:
            await self.process_program_payment(profile)

    async def process_subscription_payment(self, profile: Profile) -> None:
        try:
            self.cache_manager.set_client_data(profile.id, {"status": "waiting_for_subscription"})
            subscription = self.cache_manager.get_subscription(profile.id)
            if subscription is None:
                logger.error(f"Subscription not found for profile_id {profile.id}")
                return

            current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            self.cache_manager.update_subscription_data(profile.id, {"enabled": True, "payment_date": current_date})
            await self.workout_service.update_subscription(
                subscription.id,
                {
                    "enabled": True,
                    "price": subscription.price,
                    "user": profile.id,
                    "payment_date": current_date,
                },
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
            coach = self.cache_manager.get_coach_by_id(client.assigned_to.pop())
            await client_request(coach, client, data)
        except Exception as e:
            logger.exception(f"Program payment processing failed for profile_id {profile.id}: {e}")


payment_handler = PaymentHandler()
