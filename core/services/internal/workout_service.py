from datetime import datetime
from decimal import Decimal
from typing import Any
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from loguru import logger

from config.app_settings import settings
from core.services.internal.api_client import APIClient, APIClientHTTPError, APIClientTransportError
from core.exceptions import UserServiceError
from core.schemas import Program, DayExercises, Subscription
from core.enums import SubscriptionPeriod


class WorkoutService(APIClient):
    async def save_program(
        self, profile_id: int, exercises: list[DayExercises], split_number: int, wishes: str
    ) -> Program:
        from core.exercises import serialize_day_exercises

        url = urljoin(self.api_url, "api/v1/programs/")

        data = {
            "profile": profile_id,
            "exercises_by_day": serialize_day_exercises(exercises),
            "split_number": split_number,
            "wishes": wishes,
        }

        try:
            status_code, response = await self._api_request(
                "post", url, data, headers={"Authorization": f"Api-Key {self.api_key}"}
            )

            if status_code not in {200, 201}:
                logger.error(f"Failed to save program for profile_id={profile_id}: {response}")
                raise UserServiceError(f"Failed to save program, received status {status_code}: {response}")

            response = response or {}
            return Program(
                id=int(response.get("id", 0)),
                split_number=split_number,
                exercises_by_day=exercises,
                created_at=response.get("created_at", 0),
                profile=profile_id,
                wishes=wishes,
                workout_location=str(response.get("workout_location", "")),
            )

        except UserServiceError as e:
            logger.error(f"Error while saving program for profile_id={profile_id}: {str(e)}")
            raise

        except Exception as e:  # noqa: BLE001
            logger.exception(f"Unexpected error while saving program for profile_id={profile_id}: {str(e)}")
            raise UserServiceError(f"Unexpected error occurred while saving program: {str(e)}") from e

    async def get_latest_program(self, profile_id: int) -> Program | None:
        url = urljoin(self.api_url, f"api/v1/programs/?profile={profile_id}")
        try:
            status, data = await self._api_request(
                "get",
                url,
                headers={"Authorization": f"Api-Key {self.api_key}"},
                allow_statuses={404},
            )
        except (APIClientHTTPError, APIClientTransportError) as exc:
            logger.error(f"Program lookup failed for profile={profile_id}: {exc}")
            return None

        if status == 200:
            results = data
            if isinstance(data, dict):
                results = data.get("results", [])
            if isinstance(results, list):
                if not results:
                    logger.info(f"No program found for profile={profile_id}. HTTP={status}")
                    return None

                sorted_data = sorted(results, key=lambda p: p.get("created_at", 0), reverse=True)
                return Program.model_validate(sorted_data[0])

        logger.warning(f"Program lookup failed for profile={profile_id}. HTTP={status}, Response: {data}")
        return None

    async def update_program(self, program_id: int, data: dict[str, Any]) -> None:
        url = urljoin(self.api_url, f"api/v1/programs/{program_id}/")
        status_code, response = await self._api_request(
            "put", url, data, headers={"Authorization": f"Api-Key {self.api_key}"}
        )
        if status_code != 200:
            logger.error(f"Failed to update program {program_id}. HTTP status: {status_code}, response: {response}")

    async def create_subscription(
        self,
        profile_id: int,
        split_number: int,
        wishes: str,
        amount: Decimal,
        period: SubscriptionPeriod = SubscriptionPeriod.one_month,
        workout_location: str | None = None,
        exercises: list[dict] | None = None,
    ) -> int | None:
        url = urljoin(self.api_url, "api/v1/subscriptions/")
        data = {
            "profile_id": profile_id,
            "enabled": False,
            "price": str(amount),
            "split_number": split_number,
            "period": period.value,
            "payment_date": datetime.now(ZoneInfo(settings.TIME_ZONE)).date().isoformat(),
            "wishes": wishes,
            "workout_location": workout_location,
            "exercises": exercises or [],
        }
        status_code, response = await self._api_request(
            "post", url, data, headers={"Authorization": f"Api-Key {self.api_key}"}
        )
        if status_code == 201 and response:
            return response.get("id")
        logger.error(
            f"Failed to create subscription for profile {profile_id}. HTTP status: {status_code}, response: {response}"
        )
        return None

    async def get_latest_subscription(self, profile_id: int) -> Subscription | None:
        url = urljoin(self.api_url, f"api/v1/subscriptions/?profile={profile_id}")
        try:
            status, data = await self._api_request(
                "get",
                url,
                headers={"Authorization": f"Api-Key {self.api_key}"},
                allow_statuses={404},
            )
        except (APIClientHTTPError, APIClientTransportError) as exc:
            logger.error(f"Subscription lookup failed for profile={profile_id}: {exc}")
            return None

        if status == 200:
            results = data
            if isinstance(data, dict):
                results = data.get("results", [])
            if isinstance(results, list):
                if not results:
                    logger.debug(f"No subscription found for profile={profile_id}. HTTP={status}")
                    return None

                sorted_data = sorted(results, key=lambda s: s.get("updated_at", 0), reverse=True)
                return Subscription.model_validate(sorted_data[0])

        logger.warning(f"Subscription lookup failed for profile={profile_id}. HTTP={status}, Response: {data}")
        return None

    async def update_subscription(self, subscription_id: int, data: dict[str, Any]) -> None:
        url = urljoin(self.api_url, f"api/v1/subscriptions/{subscription_id}/")
        status_code, response = await self._api_request(
            "patch", url, data, headers={"Authorization": f"Api-Key {self.api_key}"}
        )
        if status_code != 200:
            logger.error(
                f"Failed to update subscription {subscription_id}. HTTP status: {status_code}, response: {response}"
            )

    async def get_all_subscriptions(self, profile_id: int) -> list[Subscription]:
        url = urljoin(self.api_url, f"api/v1/subscriptions/?profile={profile_id}")
        try:
            status, data = await self._api_request(
                "get",
                url,
                headers={"Authorization": f"Api-Key {self.api_key}"},
            )
        except (APIClientHTTPError, APIClientTransportError) as exc:
            logger.error(f"Failed to retrieve subscriptions for profile_id={profile_id}: {exc}")
            return []

        if status == 200:
            results = data
            if isinstance(data, dict):
                results = data.get("results", [])
            if isinstance(results, list):
                subscriptions: list[Subscription] = []
                for item in results:
                    try:
                        subscriptions.append(Subscription.model_validate(item))
                    except Exception as e:  # noqa: BLE001
                        logger.warning(f"Skipping invalid subscription for profile_id={profile_id}: {e}")
                return subscriptions

        logger.error(f"Failed to retrieve subscriptions for profile_id={profile_id}. HTTP={status}, Response: {data}")
        return []

    async def get_all_programs(self, profile_id: int) -> list[Program]:
        url = urljoin(self.api_url, f"api/v1/programs/?profile={profile_id}")
        try:
            status, data = await self._api_request(
                "get",
                url,
                headers={"Authorization": f"Api-Key {self.api_key}"},
            )
        except (APIClientHTTPError, APIClientTransportError) as exc:
            logger.error(f"Failed to retrieve programs for profile_id={profile_id}: {exc}")
            return []

        if status == 200:
            results = data
            if isinstance(data, dict):
                results = data.get("results", [])
            if isinstance(results, list):
                programs: list[Program] = []
                for item in results:
                    try:
                        programs.append(Program.model_validate(item))
                    except Exception as e:  # noqa: BLE001
                        logger.warning(f"Skipping invalid program for profile_id={profile_id}: {e}")
                programs.sort(key=lambda p: p.created_at, reverse=True)
                return programs

        logger.error(f"Failed to retrieve programs for profile_id={profile_id}. HTTP={status}, Response: {data}")
        return []
