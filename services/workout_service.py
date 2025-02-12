from datetime import datetime
from urllib.parse import urljoin
import loguru

from services.api_service import APIService
from core.exceptions import UserServiceError
from core.models import Exercise

logger = loguru.logger


class WorkoutService(APIService):
    async def save_program(
        self, client_id: int, exercises: dict[int, Exercise], split_number: int, wishes: str
    ) -> dict:
        url = urljoin(self.api_url, "api/v1/programs/")
        data = {
            "client_profile": client_id,
            "exercises_by_day": exercises,
            "split_number": split_number,
            "wishes": wishes,
        }

        try:
            status_code, response = await self._api_request(
                "post", url, data, headers={"Authorization": f"Api-Key {self.api_key}"}
            )

            if status_code != 201:
                logger.error(f"Failed to save program for client {client_id}: {response}")
                raise UserServiceError(f"Failed to save program, received status {status_code}: {response}")

            return dict(
                id=response.get("id"),
                split_number=split_number,
                exercises_by_day=exercises,
                created_at=response.get("created_at"),
                client_profile=client_id,
                wishes=wishes,
            )

        except UserServiceError as e:
            logger.error(f"Error while saving program for client {client_id}: {str(e)}")
            raise

        except Exception as e:
            logger.exception(f"Unexpected error while saving program for client {client_id}: {str(e)}")
            raise UserServiceError(f"Unexpected error occurred while saving program: {str(e)}") from e

    async def update_program(self, program_id: int, data: dict) -> bool:
        url = urljoin(self.api_url, f"api/v1/programs/{program_id}/")
        status_code, response = await self._api_request(
            "put", url, data, headers={"Authorization": f"Api-Key {self.api_key}"}
        )
        if status_code == 200:
            logger.debug(f"Program {program_id} updated successfully")
            return True
        logger.error(f"Failed to update program {program_id}. HTTP status: {status_code}")
        return False

    async def create_subscription(
        self, profile_id: int, workout_days: list[str], wishes: str, amount: int, auth_token: str
    ) -> int | None:
        url = urljoin(self.api_url, "api/v1/subscriptions/")
        data = {
            "client_profile": profile_id,
            "enabled": False,
            "price": amount,
            "workout_days": workout_days,
            "payment_date": datetime.today().strftime("%Y-%m-%d"),
            "wishes": wishes,
            "exercises": {},
        }
        status_code, response = await self._api_request(
            "post", url, data, headers={"Authorization": f"Token {auth_token}"}
        )
        if status_code == 201 and response:
            return response.get("id")
        logger.error(f"Failed to create subscription for profile {profile_id}. HTTP status: {status_code}")
        return None

    async def update_subscription(self, subscription_id: int, data: dict, auth_token: str) -> bool:
        url = urljoin(self.api_url, f"api/v1/subscriptions/{subscription_id}/")
        status_code, response = await self._api_request(
            "put", url, data, headers={"Authorization": f"Token {auth_token}"}
        )
        if status_code == 200:
            return True
        logger.error(f"Failed to update subscription {subscription_id}. HTTP status: {status_code}")
        return False


workout_service = WorkoutService()
