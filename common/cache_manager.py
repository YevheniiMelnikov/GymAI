import json
import os
import random
import time
from datetime import datetime, timedelta
from json import JSONDecodeError
from typing import Any

import loguru
import redis
from dateutil.parser import parse

from common.decorators import singleton
from common.encrypter import Encrypter
from common.encrypter import encrypter as enc
from common.exceptions import ProfileNotFoundError, UserServiceError
from common.models import Client, Coach, Profile, Program, Subscription

logger = loguru.logger


@singleton
class CacheManager:
    def __init__(self, redis_url: str, encrypter: Encrypter, prefix: str = "app/"):
        self.redis_url = redis_url
        self.redis = redis.from_url(f"{self.redis_url}", encoding="utf-8", decode_responses=True)
        self.encrypter = encrypter
        self.prefix = prefix

    def _add_prefix(self, key: str) -> str:
        return f"{self.prefix}{key}"

    def close_pool(self) -> None:
        if self.redis:
            self.redis.close()

    def _get_profile_data(self, telegram_id: int) -> list[dict[str, Any]]:
        key = self._add_prefix("user_profiles")
        profiles_data = self.redis.hget(key, str(telegram_id)) or "[]"
        try:
            return json.loads(profiles_data)
        except JSONDecodeError as e:
            logger.error(f"JSON decode error: {e}")
            return []

    def _set_data(self, key: str, profile_id: int, data: dict[str, Any], allowed_fields: list[str]) -> None:
        try:
            key = self._add_prefix(key)
            filtered_data = {k: data[k] for k in allowed_fields if k in data}
            existing_data = json.loads(self.redis.hget(key, str(profile_id)) or "{}")
            existing_data.update(filtered_data)
            self.redis.hset(key, str(profile_id), json.dumps(existing_data))
            logger.debug(f"Data for profile {profile_id} has been updated in {key}: {filtered_data}")
        except Exception as e:
            logger.error(f"Failed to set or update data for {profile_id} in {key}", e)

    def _update_profile_data(self, telegram_id: int, profiles_data: list[dict[str, Any]]) -> None:
        key = self._add_prefix("user_profiles")
        self.redis.hset(key, str(telegram_id), json.dumps(profiles_data))

    def set_profile(
        self, profile: Profile, username: str, telegram_id: int, email: str, is_current: bool = True
    ) -> None:
        try:
            current_profiles = self._get_profile_data(telegram_id)
            profile_data = {
                "id": profile.id,
                "status": profile.status,
                "language": profile.language,
                "username": username,
                "email": email,
                "is_current": is_current,
                "last_used": time.time(),
                "current_tg_id": telegram_id,
            }
            existing_profile_index = next((i for i, p in enumerate(current_profiles) if p["id"] == profile.id), None)
            if existing_profile_index is not None:
                current_profiles[existing_profile_index].update(profile_data)
            else:
                current_profiles.append(profile_data)

            for p in current_profiles:
                if p["id"] != profile.id:
                    p["is_current"] = False
                    p["current_tg_id"] = None

            self._update_profile_data(telegram_id, current_profiles)
            logger.debug(f"Profile {profile.id} set for user {telegram_id}")

        except Exception as e:
            logger.error(f"Failed to set profile for user {telegram_id}: {e}")

    def get_current_profile(self, telegram_id: int) -> Profile:
        try:
            current_profiles = [
                Profile.from_dict(data) for data in self._get_profile_data(telegram_id) if data.get("is_current", True)
            ]
            if current_profiles:
                return max(current_profiles, key=lambda p: p.last_used)
            else:
                raise ProfileNotFoundError(f"No current profile found for user {telegram_id}")
        except Exception as e:
            raise ProfileNotFoundError(f"Failed to get current profile for user {telegram_id}: {e}")

    def get_profiles(self, telegram_id: int) -> list[Profile]:
        return [Profile.from_dict(data) for data in self._get_profile_data(telegram_id)]

    def get_coaches(self) -> list[Coach] | None:
        try:
            key = self._add_prefix("coaches")
            all_coaches = self.redis.hgetall(key)
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

    def deactivate_profiles(self, telegram_id: int) -> None:
        try:
            profiles_data = self._get_profile_data(telegram_id)
            for profile_data in profiles_data:
                profile_data["is_current"] = False
            self._update_profile_data(telegram_id, profiles_data)
            logger.debug(f"Profiles of user {telegram_id} deactivated")
        except Exception as e:
            logger.error(f"Failed to deactivate profiles of user {telegram_id}: {e}")

    def get_profile_info_by_key(self, telegram_id: int, profile_id: int, key: str) -> str | None:
        profiles = self._get_profile_data(telegram_id)
        for profile_data in profiles:
            if profile_data.get("id") == profile_id:
                return profile_data.get(key)
        return None

    def set_profile_info_by_key(self, telegram_id: int, profile_id: int, key: str, value: Any) -> bool:
        try:
            profiles_data = self._get_profile_data(telegram_id)
            for profile_data in profiles_data:
                if profile_data.get("id") == profile_id:
                    profile_data[key] = value
                    break
            else:
                return False
            self._update_profile_data(telegram_id, profiles_data)
            return True
        except Exception:
            logger.exception(f"Failed to set profile info for profile {profile_id}")
            return False

    def set_client_data(self, profile_id: int, client_data: dict[str, Any]) -> None:
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
        self._set_data("clients", profile_id, client_data, allowed_fields)

    def get_client_by_id(self, profile_id: int) -> Client:
        try:
            key = self._add_prefix("clients")
            client_data = self.redis.hget(key, str(profile_id))
            if client_data:
                data = json.loads(client_data)
                data["id"] = profile_id
                return Client.from_dict(data)
            else:
                logger.debug(f"No client data found for client ID {profile_id}")
                raise UserServiceError
        except Exception as e:
            logger.info(f"Failed to get client data for client ID {profile_id}: {e}")
            raise UserServiceError

    def set_coach_data(self, profile_id: int, profile_data: dict) -> None:
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
            profile_data["payment_details"] = self.encrypter.encrypt(profile_data["payment_details"])
        self._set_data("coaches", profile_id, profile_data, allowed_fields)

    def get_coach_by_id(self, profile_id: int) -> Coach:
        try:
            key = self._add_prefix("coaches")
            coach_data = self.redis.hget(key, str(profile_id))
            if coach_data:
                data = json.loads(coach_data)
                data["id"] = profile_id
                if "payment_details" in data:
                    data["payment_details"] = self.encrypter.decrypt(data["payment_details"])
                return Coach.from_dict(data)

            else:
                logger.debug(f"No data found for profile_id {profile_id} in cache")
                raise UserServiceError
        except Exception as e:
            logger.info(f"Failed to get data for profile_id {profile_id} from cache: {e}")
            raise UserServiceError

    def set_program(self, client_id: int, program_data: dict) -> None:
        try:
            key = self._add_prefix("workout_plans:programs")
            self.redis.hset(key, str(client_id), json.dumps(program_data))
            logger.debug(f"Program for client {client_id} saved in cache")
        except Exception as e:
            logger.error(f"Failed to save program in cache for client {client_id}: {e}")

    def get_program(self, profile_id: int) -> Program | None:
        try:
            key = self._add_prefix("workout_plans:programs")
            program_data = self.redis.hget(key, str(profile_id))
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

    def set_payment_status(self, profile_id: int, paid: bool, service_type: str) -> None:
        try:
            key = self._add_prefix(f"workout_plans:payments:{service_type}")
            self.redis.hset(key, str(profile_id), json.dumps({"paid": paid}))
            logger.debug(f"Program status for profile_id {profile_id} set to {paid}")
        except Exception as e:
            logger.error(f"Failed to set payment status for profile_id {profile_id}: {e}")

    def reset_program_payment_status(self, profile_id: int, service_type: str) -> None:
        try:
            key = self._add_prefix(f"workout_plans:payments:{service_type}")
            self.redis.hdel(key, str(profile_id))
            logger.debug(f"Payment status for profile_id {profile_id} has been reset")
        except Exception as e:
            logger.error(f"Failed to reset payment status for profile_id {profile_id}: {e}")

    def check_payment_status(self, profile_id: int, service_type: str) -> bool:
        try:
            key = self._add_prefix(f"workout_plans:payments:{service_type}")
            payment_status = self.redis.hget(key, str(profile_id))
            if payment_status:
                return json.loads(payment_status).get("paid", False)
            else:
                logger.debug(f"No payment data found for profile_id {profile_id}")
                return False
        except Exception as e:
            logger.info(f"Failed to check payment status for profile_id {profile_id}: {e}")
            return False

    def save_subscription(self, profile_id: int, subscription_data: dict) -> None:
        try:
            key = self._add_prefix("workout_plans:subscriptions")
            self.redis.hset(key, str(profile_id), json.dumps(subscription_data))
            self.reset_program_payment_status(profile_id, "subscription")
            logger.debug(f"Subscription for profile {profile_id} saved in cache")
        except Exception as e:
            logger.error(f"Failed to save subscription in cache for profile {profile_id}: {e}")

    def get_subscription(self, profile_id: int) -> Subscription | None:
        try:
            key = self._add_prefix("workout_plans:subscriptions")
            subscription_data = self.redis.hget(key, str(profile_id))
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


cache_manager = CacheManager(os.getenv("REDIS_URL"), enc)
