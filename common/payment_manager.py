import asyncio
import os
from datetime import datetime

import loguru
from dateutil.relativedelta import relativedelta

from common.backend_service import backend_service
from common.cache_manager import cache_manager
from common.functions.chat import client_request, send_message
from common.functions.workout_plans import cancel_subscription
from common.models import Payment, Profile
from common.payment_service import payment_service
from common.settings import SUBSCRIPTION_PRICE
from texts.resources import MessageText
from texts.text_manager import translate

logger = loguru.logger


class PaymentHandler:
    def __init__(self):
        self.cache_manager = cache_manager
        self.backend_service = backend_service
        self.payment_service = payment_service

    def start_payment_checker(self):
        asyncio.create_task(self.check_payments())

    async def check_payments(self):
        while True:
            try:
                payments = await self.backend_service.get_all_payments()

                for payment in payments:
                    if payment.handled:
                        continue

                    local_payment = await self.backend_service.check_local_payment(payment.shop_order_number)
                    profile = Profile.from_dict(await self.backend_service.get_profile(payment.profile))
                    if local_payment.status == "PAYED":
                        await self.handle_successful_payment(payment, profile)
                    elif local_payment.status == "REJECTED":
                        await self.handle_failed_payment(payment, profile)

                await asyncio.sleep(60)

            except Exception as e:
                logger.error(f"Error in periodic payment check: {e}")
                await asyncio.sleep(60)

    async def handle_failed_payment(self, payment: Payment, profile: Profile) -> None:
        client = self.cache_manager.get_client_by_id(profile.id)
        await self.backend_service.update_payment(payment.id, dict(handled=True))
        if payment.payment_type == "subscription":
            subscription = cache_manager.get_subscription(profile.id)
            if subscription and subscription.enabled:
                payment_date = datetime.strptime(subscription.payment_date, "%Y-%m-%d")
                next_payment_date = payment_date + relativedelta(months=1)
                await send_message(
                    recipient=client,
                    text=translate(MessageText.subscription_cancel_warning, profile.language).format(
                        date=next_payment_date, mail=os.getenv("DEFAULT_FROM_EMAIL"), tg=os.getenv("TG_SUPPORT_CONTACT")
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

    async def handle_successful_payment(self, payment: Payment, profile: Profile):
        await self.backend_service.update_payment(payment.id, dict(handled=True))
        client = self.cache_manager.get_client_by_id(profile.id)
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
            cache_manager.set_client_data(profile.id, dict(status="waiting_for_subscription"))
            subscription = self.cache_manager.get_subscription(profile.id)
            cache_manager.update_subscription_data(
                profile.id, dict(enabled=True, payment_date=datetime.today().strftime("%Y-%m-%d"))
            )
            await self.backend_service.update_subscription(
                subscription.id,
                dict(
                    enabled=True,
                    price=SUBSCRIPTION_PRICE,
                    user=profile.id,
                    payment_date=datetime.today().strftime("%Y-%m-%d"),
                ),
            )
            data = {
                "request_type": "subscription",
                "workout_type": subscription.workout_type,
            }
            if not subscription.enabled:
                client = self.cache_manager.get_client_by_id(profile.id)
                coach = self.cache_manager.get_coach_by_id(client.assigned_to.pop())
                await client_request(coach, client, data)
        except Exception as e:
            logger.error(f"Subscription payment processing failed for profile_id {profile.id}: {e}")

    async def process_program_payment(self, profile: Profile) -> None:
        try:
            cache_manager.set_client_data(profile.id, dict(status="waiting_for_program"))
            program = self.cache_manager.get_program(profile.id)
            data = {
                "request_type": "program",
                "workout_type": program.workout_type,
            }
            client = self.cache_manager.get_client_by_id(profile.id)
            coach = self.cache_manager.get_coach_by_id(client.assigned_to.pop())
            await client_request(coach, client, data)
        except Exception as e:
            logger.error(f"Program payment processing failed for profile_id {profile.id}: {e}")


payment_handler = PaymentHandler()
