import json
from datetime import datetime, timedelta
from loguru import logger
from typing import Any

from core.cache import Cache
from core.models import Client
from core.exceptions import UserServiceError
from base import BaseCacheManager
from core.validators import validate_or_raise


class ClientCacheManager(BaseCacheManager):
    @classmethod
    async def update_client(cls, profile_id: int, client_data: dict[str, Any]) -> None:
        await cls.update_json("clients", str(profile_id), client_data)

    @classmethod
    async def save_client(cls, profile_id: int, client_data: dict[str, Any]) -> None:
        try:
            await cls.set("clients", str(profile_id), json.dumps(client_data))
            logger.debug(f"Saved client data to cache for profile_id={profile_id}")
        except Exception as e:
            logger.error(f"Failed to save client data for profile_id={profile_id}: {e}")

    @classmethod
    async def get_client(cls, profile_id: int) -> Client:
        raw = await cls.get("clients", str(profile_id))
        if not raw:
            raise UserServiceError(
                message="No client data found",
                code=404,
                details=f"Client ID: {profile_id} not found in Redis cache",
            )
        try:
            data = json.loads(raw)
            data["id"] = profile_id
            return validate_or_raise(data, Client, context=f"profile_id={profile_id}")
        except Exception as e:
            raise UserServiceError(
                message="Failed to get client data", code=500, details=f"Error: {e}, Client ID: {profile_id}"
            )

    @classmethod
    async def get_clients_to_survey(cls) -> list[int]:
        try:
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%A").lower()
            clients_with_workout = []
            raw_clients = await cls.get_all("clients")

            for client_id_str in raw_clients:
                client_id = int(client_id_str)
                subscription = await Cache.workout.get_subscription(client_id)

                if not subscription:
                    continue
                if not isinstance(subscription.workout_days, list):
                    logger.warning(f"Invalid workout_days for client_id={client_id}")
                    continue
                if (
                    subscription.enabled
                    and subscription.exercises
                    and yesterday in [day.lower() for day in subscription.workout_days]
                ):
                    clients_with_workout.append(client_id)

            return clients_with_workout

        except Exception as e:
            logger.error(f"Failed to get clients to survey: {e}")
            return []
