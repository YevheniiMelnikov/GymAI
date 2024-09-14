from datetime import datetime
from urllib.parse import urljoin
import loguru

from services.backend_service import BackendService
from common.exceptions import UserServiceError
from common.models import Exercise

logger = loguru.logger


class WorkoutService(BackendService):
    async def save_program(self, client_id: int, exercises: dict[int, Exercise], split_number: int) -> dict:
        url = urljoin(self.backend_url, "api/v1/programs/")
        data = {
            "profile": client_id,
            "exercises_by_day": exercises,
            "split_number": split_number,
        }
        status_code, response = await self._api_request(
            "post", url, data, headers={"Authorization": f"Api-Key {self.api_key}"}
        )
        if status_code != 201:
            logger.error(f"Failed to save program for client {client_id}: {response}")
            raise UserServiceError(f"Failed to save program: {response}")

        return dict(
            id=response.get("id"),
            split_number=split_number,
            exercises_by_day=exercises,
            created_at=response.get("created_at"),
            profile=client_id,
        )

    async def update_program(self, program_id: int, data: dict) -> bool:
        url = urljoin(self.backend_url, f"api/v1/programs/{program_id}/")
        status_code, response = await self._api_request(
            "put", url, data, headers={"Authorization": f"Api-Key {self.api_key}"}
        )
        if status_code == 200:
            logger.debug(f"Program {program_id} updated successfully")
            return True
        logger.error(f"Failed to update program {program_id}. HTTP status: {status_code}")
        return False

    async def create_subscription(
        self, profile_id: int, workout_days: list[str], wishes: str, amount: int
    ) -> int | None:
        url = urljoin(self.backend_url, "api/v1/subscriptions/")
        data = {
            "user": profile_id,
            "enabled": False,
            "price": amount,
            "workout_days": workout_days,
            "payment_date": datetime.today().strftime("%Y-%m-%d"),
            "wishes": wishes,
            "exercises": {},
        }
        status_code, response = await self._api_request(
            "post", url, data, headers={"Authorization": f"Api-Key {self.api_key}"}
        )
        if status_code == 201 and response:
            return response.get("id")
        logger.error(f"Failed to create subscription for profile {profile_id}. HTTP status: {status_code}")
        return None

    async def update_subscription(self, subscription_id: int, data: dict) -> bool:
        url = urljoin(self.backend_url, f"api/v1/subscriptions/{subscription_id}/")
        status_code, response = await self._api_request(
            "put", url, data, headers={"Authorization": f"Api-Key {self.api_key}"}
        )
        if status_code == 200:
            return True
        logger.error(f"Failed to update subscription {subscription_id}. HTTP status: {status_code}")
        return False


workout_service = WorkoutService()
