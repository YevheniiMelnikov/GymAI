import json
import random
from datetime import datetime, timedelta
from json import JSONDecodeError
from typing import Any

import redis
from dateutil.parser import parse
from loguru import logger

from core.encryptor import Encryptor
from core.exceptions import UserServiceError, ProfileNotFoundError
from core.models import Client, Coach, Profile, Program, Subscription
from config.env_settings import Settings


class CacheManager:
    redis = redis.from_url(Settings.REDIS_URL, encoding="utf-8", decode_responses=True)
    encryptor = Encryptor

    @classmethod
    def _add_prefix(cls, key: str) -> str:
        return f"app/{key}"

    @classmethod
    def close_pool(cls) -> None:
        if cls.redis:
            cls.redis.close()

    @classmethod
    def _set_data(cls, key: str, profile_id: int, data: dict[str, Any], allowed_fields: list[str]) -> None:
        try:
            key = cls._add_prefix(key)
            filtered_data = {k: data[k] for k in allowed_fields if k in data}
            existing_data = json.loads(cls.redis.hget(key, str(profile_id)) or "{}")
            existing_data.update(filtered_data)
            cls.redis.hset(key, str(profile_id), json.dumps(existing_data))
        except Exception as e:
            logger.error(f"Error setting data for profile_id {profile_id}: {e}")

    @classmethod
    def get_profile(cls, telegram_id: int) -> Profile | None:
        key = cls._add_prefix("user_profiles")
        raw_data = cls.redis.hget(key, str(telegram_id))
        if not raw_data:
            raise ProfileNotFoundError(telegram_id)

        try:
            data = json.loads(raw_data)
            if "id" not in data:
                raise ProfileNotFoundError(telegram_id)
            return Profile.from_dict(data)
        except (JSONDecodeError, TypeError) as e:
            logger.debug(f"Profile data in Redis is invalid or incomplete for user {telegram_id}: {e}")
            raise ProfileNotFoundError(telegram_id)

    @classmethod
    def get_profile_data(cls, telegram_id: int, key_name: str) -> Any:
        profile = cls.get_profile(telegram_id)
        if profile:
            return profile.to_dict().get(key_name)

    @classmethod
    def set_profile_data(cls, telegram_id: int, data: dict[str, Any]) -> bool:
        allowed_fields = [
            "language",
            "status",
            "tg_id",
        ]
        try:
            key = cls._add_prefix("user_profiles")
            filtered_data = {k: data[k] for k in allowed_fields if k in data}
            existing_data = json.loads(cls.redis.hget(key, str(telegram_id)) or "{}")
            existing_data.update(filtered_data)
            cls.redis.hset(key, str(telegram_id), json.dumps(existing_data))
            return True
        except Exception as e:
            logger.error(f"Error setting data for profile_id {telegram_id}: {e}")
            return False

    @classmethod
    def delete_profile(cls, telegram_id: int) -> bool:
        try:
            key = cls._add_prefix("user_profiles")
            cls.redis.hdel(key, str(telegram_id))
            logger.info(f"Profile for telegram_id {telegram_id} has been deleted")
            return True
        except Exception as e:
            logger.error(f"Error deleting profile for telegram_id {telegram_id}: {e}")
            return False

    @classmethod
    def get_coaches(cls) -> list[Coach] | None:
        try:
            key = cls._add_prefix("coaches")
            all_coaches = cls.redis.hgetall(key)
            coaches_data = []
            for k, v in all_coaches.items():
                coach_dict = json.loads(v)
                coach_dict["id"] = int(k)
                coach = Coach.from_dict(coach_dict)
                if coach.verified:
                    coaches_data.append(coach)
            random.shuffle(coaches_data)
            return coaches_data
        except Exception as e:
            logger.info(f"Failed to retrieve coach data: {e}")
            return None

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
        cls._set_data("clients", profile_id, client_data, allowed_fields)

    @classmethod
    def get_client_by_id(cls, profile_id: int) -> Client:
        try:
            key = cls._add_prefix("clients")
            client_data = cls.redis.hget(key, str(profile_id))
            if client_data:
                data = json.loads(client_data)
                data["id"] = profile_id
                return Client.from_dict(data)
            else:
                logger.debug(f"No client data found for client ID {profile_id}")
                raise UserServiceError(
                    message="No client data found",
                    code=404,
                    details=f"Client ID: {profile_id} not found in Redis cache",
                )
        except Exception as e:
            logger.error(f"Failed to get client data for client ID {profile_id}: {e}")
            raise UserServiceError(
                message="Failed to get client data", code=500, details=f"Error: {e}, Client ID: {profile_id}"
            )

    @classmethod
    def get_clients_to_survey(cls) -> list[int]:
        try:
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%A").lower()
            clients_with_workout = []
            key = cls._add_prefix("clients")
            all_clients = cls.redis.hgetall(key)

            for client_id, _ in all_clients.items():
                subscription = cls.get_subscription(int(client_id))
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

    @classmethod
    def set_coach_data(cls, profile_id: int, profile_data: dict) -> None:
        allowed_fields = [
            "name",
            "surname",
            "work_experience",
            "additional_info",
            "payment_details",
            "profile_photo",
            "verified",
            "assigned_to",
            "subscription_price",
            "program_price",
        ]
        if profile_data.get("payment_details"):
            profile_data["payment_details"] = cls.encryptor.encrypt(profile_data["payment_details"])
        cls._set_data("coaches", profile_id, profile_data, allowed_fields)

    @classmethod
    def get_coach_by_id(cls, profile_id: int) -> Coach:
        try:
            key = cls._add_prefix("coaches")
            coach_data = cls.redis.hget(key, str(profile_id))
            if coach_data:
                data = json.loads(coach_data)
                data["id"] = profile_id
                if "payment_details" in data:
                    data["payment_details"] = cls.encryptor.decrypt(data["payment_details"])
                return Coach.from_dict(data)
            else:
                logger.debug(f"No data found for profile_id {profile_id} in cache")
                raise UserServiceError(
                    message="No coach data found", code=404, details=f"Coach ID: {profile_id} not found in Redis cache"
                )
        except Exception as e:
            logger.error(f"Failed to get data for profile_id {profile_id} from cache: {e}")
            raise UserServiceError(
                message="Failed to get coach data", code=500, details=f"Error: {e}, Coach ID: {profile_id}"
            )

    @classmethod
    def set_program(cls, client_id: int, program_data: dict) -> None:
        try:
            key = cls._add_prefix("workout_plans:programs")
            cls.redis.hset(key, str(client_id), json.dumps(program_data))
            logger.debug(f"Program for client {client_id} saved in cache")
        except Exception as e:
            logger.error(f"Failed to save program in cache for client {client_id}: {e}")

    @classmethod
    def get_program(cls, profile_id: int) -> Program | None:
        try:
            key = cls._add_prefix("workout_plans:programs")
            program_data = cls.redis.hget(key, str(profile_id))
            if program_data:
                data = json.loads(program_data)
                data["profile"] = profile_id
                return Program.from_dict(data)
            else:
                logger.debug(f"No program data found for profile_id {profile_id}")
                return None
        except Exception as e:
            logger.info(f"Failed to get program for profile_id {profile_id}: {e}")
            return None

    @classmethod
    def update_subscription_data(cls, profile_id: int, subscription_data: dict) -> None:
        allowed_fields = [
            "payment_date",
            "enabled",
            "price",
            "client_profile",
            "workout_type",
            "workout_days",
            "exercises",
            "wishes",
        ]
        cls._set_data("workout_plans:subscriptions", profile_id, subscription_data, allowed_fields)

    @classmethod
    def update_program_data(cls, profile_id: int, program_data: dict[str, Any]) -> None:
        allowed_fields = [
            "exercises_by_day",
            "split_number",
            "workout_type",
            "wishes",
        ]
        cls._set_data("workout_plans:programs", profile_id, program_data, allowed_fields)

    @classmethod
    def set_payment_status(cls, profile_id: int, paid: bool, service_type: str) -> None:
        try:
            key = cls._add_prefix(f"workout_plans:payments:{service_type}")
            cls.redis.hset(key, str(profile_id), json.dumps({"paid": paid}))
            logger.debug(f"Program status for profile_id {profile_id} set to {paid}")
        except Exception as e:
            logger.error(f"Failed to set payment status for profile_id {profile_id}: {e}")

    @classmethod
    def reset_program_payment_status(cls, profile_id: int, service_type: str) -> None:
        try:
            key = cls._add_prefix(f"workout_plans:payments:{service_type}")
            cls.redis.hdel(key, str(profile_id))
            logger.debug(f"Payment status for profile_id {profile_id} has been reset")
        except Exception as e:
            logger.error(f"Failed to reset payment status for profile_id {profile_id}: {e}")

    @classmethod
    def check_payment_status(cls, profile_id: int, service_type: str) -> bool:
        try:
            key = cls._add_prefix(f"workout_plans:payments:{service_type}")
            payment_status = cls.redis.hget(key, str(profile_id))
            if payment_status:
                return json.loads(payment_status).get("paid", False)
            else:
                logger.debug(f"No payment data found for profile_id {profile_id}")
                return False
        except Exception as e:
            logger.info(f"Failed to check payment status for profile_id {profile_id}: {e}")
            return False

    @classmethod
    def save_subscription(cls, profile_id: int, subscription_data: dict) -> None:
        try:
            key = cls._add_prefix("workout_plans:subscriptions")
            cls.redis.hset(key, str(profile_id), json.dumps(subscription_data))
            cls.reset_program_payment_status(profile_id, "subscription")
            logger.debug(f"Subscription for profile_id {profile_id} saved in cache")
        except Exception as e:
            logger.error(f"Failed to save subscription in cache for profile {profile_id}: {e}")

    @classmethod
    def get_subscription(cls, profile_id: int) -> Subscription | None:
        try:
            key = cls._add_prefix("workout_plans:subscriptions")
            subscription_data = cls.redis.hget(key, str(profile_id))
            if subscription_data:
                data = json.loads(subscription_data)
                if payment_date := data.get("payment_date"):
                    payment_date = parse(payment_date)
                    data["payment_date"] = payment_date.strftime("%Y-%m-%d")
                return Subscription.from_dict(data)
            else:
                logger.debug(f"No subscription data found for profile_id {profile_id}")
                return None
        except Exception as e:
            logger.info(f"Failed to get subscription for profile_id {profile_id}: {e}")
            return None

    @classmethod
    def cache_gif_filename(cls, exercise_name: str, filename: str) -> None:
        if not exercise_name or not filename:
            return
        try:
            key = cls._add_prefix("gifs")
            cls.redis.hset(key, exercise_name, filename)
        except Exception as e:
            logger.info(f"Failed to cache gif filename for exercise {exercise_name}: {e}")

    @classmethod
    def get_exercise_gif(cls, exercise_name: str) -> str | None:
        try:
            key = cls._add_prefix("gifs")
            return cls.redis.hget(key, exercise_name)
        except Exception as e:
            logger.info(f"Failed to get gif filename for exercise {exercise_name}: {e}")
            return None
