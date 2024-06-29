import datetime
from datetime import datetime

import loguru
from aiogram.fsm.context import FSMContext

from common.models import Profile
from common.user_service import user_service

logger = loguru.logger


class PaymentService:
    def __init__(self, user_service):
        self.user_service = user_service

    async def process_subscription_payment(self, state: FSMContext, profile: Profile) -> bool:
        data = await state.get_data()
        try:
            subscription_id = await self.user_service.create_subscription(
                profile.id, data.get("price"), data.get("workout_days")
            )
            subscription_data = {
                "id": subscription_id,
                "payment_date": datetime.today().isoformat(),
                "enabled": True,
                "price": data.get("price"),
                "workout_days": data.get("workout_days"),
            }
            self.user_service.storage.save_subscription(profile.id, subscription_data)
            self.user_service.storage.set_payment_status(profile.id, True, "subscription")
            return True
        except Exception as e:
            logger.error(f"Subscription not created for profile_id {profile.id}: {e}")
            return False

    async def process_program_payment(self, state: FSMContext, profile: Profile) -> bool:
        data = await state.get_data()
        try:
            # TODO: IMPLEMENT
            self.user_service.storage.set_payment_status(profile.id, True, "program")
            return True
        except Exception as e:
            logger.error(f"Program payment failed for profile_id {profile.id}: {e}")
            return False


payment_service = PaymentService(user_service)
