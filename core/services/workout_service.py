from datetime import datetime
from typing import Any
from urllib.parse import urljoin
from loguru import logger

from core.services.api_service import APIClient
from core.exceptions import UserServiceError
from core.models import Exercise, Program


class WorkoutService(APIClient):
    @classmethod
    async def save_program(
        cls, client_id: int, exercises: dict[str, list[Exercise]], split_number: int, wishes: str
    ) -> Program:
        url = urljoin(cls.api_url, "api/v1/programs/")
        exercises_payload: dict[str, list[dict[str, Any]]] = {
            day: [e.to_dict() for e in items if isinstance(e, Exercise)] for day, items in exercises.items()
        }  # TODO: REDUCE OVERCOMPLEXITY
        data = {
            "client_profile": client_id,
            "exercises_by_day": exercises_payload,
            "split_number": split_number,
            "wishes": wishes,
        }

        try:
            status_code, response = await cls._api_request(
                "post", url, data, headers={"Authorization": f"Api-Key {cls.api_key}"}
            )

            if status_code != 201:
                logger.error(f"Failed to save program for client {client_id}: {response}")
                raise UserServiceError(f"Failed to save program, received status {status_code}: {response}")

            return Program(
                id=response.get("id"),
                split_number=split_number,
                exercises_by_day=exercises,
                created_at=response.get("created_at"),
                profile=client_id,
                wishes=wishes,
                workout_type=response.get("workout_type"),
            )

        except UserServiceError as e:
            logger.error(f"Error while saving program for client {client_id}: {str(e)}")
            raise

        except Exception as e:
            logger.exception(f"Unexpected error while saving program for client {client_id}: {str(e)}")
            raise UserServiceError(f"Unexpected error occurred while saving program: {str(e)}") from e

    @classmethod
    async def update_program(cls, program_id: int, data: dict) -> bool:
        url = urljoin(cls.api_url, f"api/v1/programs/{program_id}/")
        status_code, response = await cls._api_request(
            "put", url, data, headers={"Authorization": f"Api-Key {cls.api_key}"}
        )
        if status_code == 200:
            logger.debug(f"Program {program_id} updated successfully")
            return True
        logger.error(f"Failed to update program {program_id}. HTTP status: {status_code}")
        return False

    @classmethod
    async def create_subscription(
        cls, profile_id: int, workout_days: list[str], wishes: str, amount: int
    ) -> int | None:
        url = urljoin(cls.api_url, "api/v1/subscriptions/")
        data = {
            "client_profile": profile_id,
            "enabled": False,
            "price": amount,
            "workout_days": workout_days,
            "payment_date": datetime.today().strftime("%Y-%m-%d"),
            "wishes": wishes,
            "exercises": {},
        }
        status_code, response = await cls._api_request(
            "post", url, data, headers={"Authorization": f"Api-Key {cls.api_key}"}
        )
        if status_code == 201 and response:
            return response.get("id")
        logger.error(f"Failed to create subscription for profile {profile_id}. HTTP status: {status_code}")
        return None

    @classmethod
    async def update_subscription(cls, subscription_id: int, data: dict) -> bool:
        url = urljoin(cls.api_url, f"api/v1/subscriptions/{subscription_id}/")
        status_code, response = await cls._api_request(
            "put", url, data, headers={"Authorization": f"Api-Key {cls.api_key}"}
        )
        if status_code == 200:
            return True
        logger.error(f"Failed to update subscription {subscription_id}. HTTP status: {status_code}")
        return False
