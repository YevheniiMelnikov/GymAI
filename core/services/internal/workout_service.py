from datetime import datetime
from decimal import Decimal
from typing import Any
from urllib.parse import urljoin
from loguru import logger

from core.services.internal.api_client import APIClient
from core.exceptions import UserServiceError
from core.schemas import Program, DayExercises, Subscription
from bot.utils.exercises import serialize_day_exercises


class WorkoutService(APIClient):
    @classmethod
    async def save_program(
        cls, client_profile_id: int, exercises: list[DayExercises], split_number: int, wishes: str
    ) -> Program:
        url = urljoin(cls.api_url, "api/v1/programs/")

        data = {
            "client_profile": client_profile_id,
            "exercises_by_day": serialize_day_exercises(exercises),
            "split_number": split_number,
            "wishes": wishes,
        }

        try:
            status_code, response = await cls._api_request(
                "post", url, data, headers={"Authorization": f"Api-Key {cls.api_key}"}
            )

            if status_code != 201:
                logger.error(f"Failed to save program for client_profile_id={client_profile_id}: {response}")
                raise UserServiceError(f"Failed to save program, received status {status_code}: {response}")

            response = response or {}
            return Program(
                id=int(response.get("id", 0)),
                split_number=split_number,
                exercises_by_day=exercises,
                created_at=float(response.get("created_at", 0)),
                client_profile=client_profile_id,
                wishes=wishes,
                workout_type=str(response.get("workout_type", "")),
            )

        except UserServiceError as e:
            logger.error(f"Error while saving program for client_profile_id={client_profile_id}: {str(e)}")
            raise

        except Exception as e:
            logger.exception(
                f"Unexpected error while saving program for client_profile_id={client_profile_id}: {str(e)}"
            )
            raise UserServiceError(f"Unexpected error occurred while saving program: {str(e)}") from e

    @classmethod
    async def get_latest_program(cls, client_profile_id: int) -> Program | None:
        url = urljoin(cls.api_url, f"api/v1/programs/?client_profile={client_profile_id}")
        status, data = await cls._api_request("get", url, headers={"Authorization": f"Api-Key {cls.api_key}"})

        if status == 200:
            results = data
            if isinstance(data, dict):
                results = data.get("results", [])
            if isinstance(results, list):
                if not results:
                    logger.info(f"No program found for client_profile={client_profile_id}. HTTP={status}")
                    return None

                sorted_data = sorted(results, key=lambda p: p.get("created_at", 0), reverse=True)
                return Program.model_validate(sorted_data[0])

        logger.warning(f"Program lookup failed for client_profile={client_profile_id}. HTTP={status}, Response: {data}")
        return None

    @classmethod
    async def update_program(cls, program_id: int, data: dict[str, Any]) -> None:
        url = urljoin(cls.api_url, f"api/v1/programs/{program_id}/")
        status_code, response = await cls._api_request(
            "put", url, data, headers={"Authorization": f"Api-Key {cls.api_key}"}
        )
        if not status_code == 200:
            logger.error(f"Failed to update program {program_id}. HTTP status: {status_code}, response: {response}")

    @classmethod
    async def create_subscription(
        cls,
        client_profile_id: int,
        workout_days: list[str],
        wishes: str,
        amount: Decimal,
        period: str = "1m",
        exercises: list[dict] | None = None,
    ) -> int | None:
        url = urljoin(cls.api_url, "api/v1/subscriptions/")
        data = {
            "client_profile": client_profile_id,
            "enabled": False,
            "price": str(amount),
            "workout_days": workout_days,
            "period": period,
            "payment_date": datetime.today().strftime("%Y-%m-%d"),
            "wishes": wishes,
            "exercises": exercises or [],
        }
        status_code, response = await cls._api_request(
            "post", url, data, headers={"Authorization": f"Api-Key {cls.api_key}"}
        )
        if status_code == 201 and response:
            return response.get("id")
        logger.error(
            "Failed to create subscription for profile %s. HTTP status: %s, response: %s",
            client_profile_id,
            status_code,
            response,
        )
        return None

    @classmethod
    async def get_latest_subscription(cls, client_profile_id: int) -> Subscription | None:
        url = urljoin(cls.api_url, f"api/v1/subscriptions/?client_profile={client_profile_id}")
        status, data = await cls._api_request("get", url, headers={"Authorization": f"Api-Key {cls.api_key}"})

        if status == 200:
            results = data
            if isinstance(data, dict):
                results = data.get("results", [])
            if isinstance(results, list):
                if not results:
                    logger.info(f"No subscription found for client_profile={client_profile_id}. HTTP={status}")
                    return None

                sorted_data = sorted(results, key=lambda s: s.get("updated_at", 0), reverse=True)
                return Subscription.model_validate(sorted_data[0])

        logger.warning(
            f"Subscription lookup failed for client_profile={client_profile_id}. HTTP={status}, Response: {data}"
        )
        return None

    @classmethod
    async def update_subscription(cls, subscription_id: int, data: dict[str, Any]) -> None:
        url = urljoin(cls.api_url, f"api/v1/subscriptions/{subscription_id}/")
        status_code, response = await cls._api_request(
            "put", url, data, headers={"Authorization": f"Api-Key {cls.api_key}"}
        )
        if not status_code == 200:
            logger.error(
                f"Failed to update subscription {subscription_id}. HTTP status: {status_code}, response: {response}"
            )

    @classmethod
    async def get_all_subscriptions(cls, client_profile_id: int) -> list[Subscription]:
        url = urljoin(cls.api_url, f"api/v1/subscriptions/?client_profile={client_profile_id}")
        status, data = await cls._api_request("get", url, headers={"Authorization": f"Api-Key {cls.api_key}"})

        if status == 200:
            results = data
            if isinstance(data, dict):
                results = data.get("results", [])
            if isinstance(results, list):
                subscriptions: list[Subscription] = []
                for item in results:
                    try:
                        subscriptions.append(Subscription.model_validate(item))
                    except Exception as e:
                        logger.warning(f"Skipping invalid subscription for client_profile_id={client_profile_id}: {e}")
                return subscriptions

        logger.error(
            "Failed to retrieve subscriptions for client_profile_id=%s. HTTP=%s, Response: %s",
            client_profile_id,
            status,
            data,
        )
        return []

    @classmethod
    async def get_all_programs(cls, client_profile_id: int) -> list[Program]:
        url = urljoin(cls.api_url, f"api/v1/programs/?client_profile={client_profile_id}")
        status, data = await cls._api_request("get", url, headers={"Authorization": f"Api-Key {cls.api_key}"})

        if status == 200:
            results = data
            if isinstance(data, dict):
                results = data.get("results", [])
            if isinstance(results, list):
                programs: list[Program] = []
                for item in results:
                    try:
                        programs.append(Program.model_validate(item))
                    except Exception as e:
                        logger.warning(f"Skipping invalid program for client_profile_id={client_profile_id}: {e}")
                programs.sort(key=lambda p: p.created_at, reverse=True)
                return programs

        logger.error(
            "Failed to retrieve programs for client_profile_id=%s. HTTP=%s, Response: %s",
            client_profile_id,
            status,
            data,
        )
        return []
