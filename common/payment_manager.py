import asyncio
from datetime import datetime

import loguru

from bot.states import States
from common.backend_service import backend_service
from common.cache_manager import cache_manager
from common.functions.chat import client_request, send_message
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
                    try:
                        status_code, payment_status = await self.payment_service.check_status(payment.shop_order_number)
                        profile = Profile.from_dict(await self.backend_service.get_profile(payment.profile))
                        if status_code == 200 and payment_status.get("RESULT") == "APPROVED":
                            await self.handle_successful_payment(payment, profile)
                        else:
                            await self.handle_failed_payment(payment, profile)
                    except Exception as e:
                        logger.error(f"Error processing payment {payment.shop_order_number}: {e}")
                        await self.backend_service.update_payment(payment.id, dict(handled=False))

                await asyncio.sleep(60)

            except Exception as e:
                logger.error(f"Error in periodic payment check: {e}")
                await asyncio.sleep(60)

    async def handle_failed_payment(self, payment: Payment, profile: Profile) -> None:
        client = self.cache_manager.get_client_by_id(profile.id)
        state = States.default
        await send_message(
            recipient=client,
            text=translate(MessageText.payment_failure, profile.language),
            state=state,
            include_incoming_message=False,
        )
        await self.backend_service.update_payment(payment.id, {"handled": False})

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
            cache_manager.set_client_data(client.id, dict(status="waiting_for_subscription"))
            await self.process_subscription_payment(profile)
        else:
            cache_manager.set_client_data(client.id, {"status": "waiting_for_program"})
            await self.process_program_payment(profile)
        # TODO: NOTIFY PORTMONE

    async def process_subscription_payment(self, profile: Profile) -> None:
        try:
            cache_manager.update_subscription_data(
                profile.id, dict(enabled=True, payment_date=datetime.today().strftime("%Y-%m-%d"))
            )
            subscription = self.cache_manager.get_subscription(profile.id)
            await self.backend_service.update_subscription(
                subscription.id, dict(enabled=True, price=SUBSCRIPTION_PRICE, user=profile.id)
            )
            data = {
                "request_type": "subscription",
                "workout_type": subscription.workout_type,
            }
            client = self.cache_manager.get_client_by_id(profile.id)
            coach = self.cache_manager.get_coach_by_id(client.assigned_to.pop())
            await client_request(coach, client, data)
        except Exception as e:
            logger.error(f"Subscription payment processing failed for profile_id {profile.id}: {e}")

    async def process_program_payment(self, profile: Profile) -> None:
        try:
            self.cache_manager.set_payment_status(profile.id, True, "program")
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
