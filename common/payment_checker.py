import asyncio

import loguru

from bot.states import States
from common.backend_service import backend_service
from common.cache_manager import cache_manager
from common.functions.chat import client_request, send_message
from common.models import Payment, Profile
from common.payment_service import payment_service
from texts.resources import MessageText
from texts.text_manager import translate

logger = loguru.logger


async def handle_successful_payment(payment: Payment, profile: Profile):
    client = cache_manager.get_client_by_id(profile.id)
    coach = cache_manager.get_coach_by_id(client.assigned_to.pop())
    state = States.default
    await client_request(coach, client, state)
    await send_message(
        recipient=client,
        text=translate(MessageText.payment_success, profile.language),
        state=state,
        include_incoming_message=False,
    )

    if payment.payment_type == "subscription":
        await payment_service.process_subscription_payment(payment, profile)
    else:
        await payment_service.process_program_payment(profile)
    await backend_service.update_payment(payment.id, {"handled": True})
    # TODO: NOTIFY PORTMONE


async def handle_failed_payment(payment: Payment, profile: Profile) -> None:
    client = cache_manager.get_client_by_id(profile.id)
    state = States.default
    await send_message(
        recipient=client,
        text=translate(MessageText.payment_failure, profile.language),
        state=state,
        include_incoming_message=False,
    )
    await backend_service.update_payment(payment.id, {"handled": False})


async def check_payments():
    while True:
        try:
            payments = await backend_service.get_all_payments()
            for payment in payments:
                if payment.handled:
                    continue
                try:
                    status_code, payment_status = await payment_service.check_status(payment.shop_order_number)
                    profile = Profile.from_dict(await backend_service.get_profile(payment.profile))
                    if status_code == 200 and payment_status.get("RESULT") == "APPROVED":
                        await handle_successful_payment(payment, profile)
                    else:
                        await handle_failed_payment(payment, profile)
                except Exception as e:
                    logger.error(f"Error processing payment {payment.shop_order_number}: {e}")
                    await backend_service.update_payment(payment.id, {"handled": False})

            await asyncio.sleep(60)

        except Exception as e:
            logger.error(f"Error in periodic payment check: {e}")
            await asyncio.sleep(60)


def payment_checker():
    asyncio.create_task(check_payments())
