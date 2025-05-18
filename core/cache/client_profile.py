import json
from datetime import datetime, timedelta
from loguru import logger
from typing import Any

from core.models import Client
from core.exceptions import UserServiceError
from base import BaseCacheManager
from workout import WorkoutCacheManager


class ClientCacheManager(BaseCacheManager):
    @classmethod
    def set_client_data(cls, profile_id: int, client_data: dict[str, Any]) -> None:
        allowed_fields = [
            "name",
            "gender",
            "born_in",
            "workout_experience",
            "workout_goals",
            "health_notes",
            "weight",
            "status",
            "assigned_to",
        ]
        cls.update_json_fields("clients", str(profile_id), client_data, allowed_fields)

    @classmethod
    def get_client(cls, profile_id: int) -> Client:
        raw = cls.get("clients", str(profile_id))
        if not raw:
            logger.debug(f"No client data found for client ID {profile_id}")
            raise UserServiceError(
                message="No client data found",
                code=404,
                details=f"Client ID: {profile_id} not found in Redis cache",
            )
        try:
            data = json.loads(raw)
            data["id"] = profile_id
            return Client.from_dict(data)
        except Exception as e:
            logger.error(f"Failed to parse client data for client ID {profile_id}: {e}")
            raise UserServiceError(
                message="Failed to get client data", code=500, details=f"Error: {e}, Client ID: {profile_id}"
            )

    @classmethod
    def get_clients_to_survey(cls) -> list[int]:
        try:
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%A").lower()
            clients_with_workout = []
            all_clients = cls.get_all("clients")

            for client_id in all_clients:
                subscription = Cache.workout.get_subscription(int(client_id))
                if (
                    subscription
                    and subscription.enabled
                    and subscription.exercises
                    and yesterday in [day.lower() for day in subscription.workout_days]
                ):
                    clients_with_workout.append(int(client_id))

            return clients_with_workout
        except Exception as e:
            logger.error(f"Failed to get clients to survey: {e}")
            return []
