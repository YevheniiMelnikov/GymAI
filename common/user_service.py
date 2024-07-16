import json
import os
import random
import time
from datetime import datetime, timedelta
from json import JSONDecodeError
from typing import Any

import httpx
import loguru
import redis
from dateutil.parser import parse

from common.exceptions import EmailUnavailable, UsernameUnavailable, UserServiceError
from common.models import Client, Coach, Exercise, Profile, Program, Subscription

logger = loguru.logger


class UserProfileManager:
    def __init__(self, redis_url: str):
        self._redis_url = redis_url
        self._redis = redis.from_url(f"{self._redis_url}/1", encoding="utf-8", decode_responses=True)

    @property
    def redis_url(self) -> str:
        return self._redis_url

    @property
    def redis(self) -> redis.Redis:
        return self._redis

    def close_pool(self) -> None:
        if self.redis:
            self.redis.close()

    def _get_profile_data(self, telegram_id: int | str) -> list[dict[str, Any]]:
        profiles_data = self.redis.hget("user_profiles", str(telegram_id)) or "[]"
        try:
            return json.loads(profiles_data)
        except JSONDecodeError as e:
            logger.error(f"JSON decode error: {e}")
            return []

    def _update_profile_data(self, telegram_id: int | str, profiles_data: list[dict[str, Any]]) -> None:
        self.redis.hset("user_profiles", str(telegram_id), json.dumps(profiles_data))

    def set_profile(
        self,
        profile: Profile,
        username: str,
        auth_token: str,
        telegram_id: str,
        email: str | None = None,
        is_current: bool = True,
    ) -> None:
        email = email or self.get_profile_info_by_key(telegram_id, profile.id, "email")

        try:
            current_profiles = self._get_profile_data(telegram_id)
            profile_data = {
                "id": profile.id,
                "status": profile.status,
                "language": profile.language,
                "username": username,
                "auth_token": auth_token,
                "email": email,
                "is_current": is_current,
                "last_used": time.time(),
            }

            existing_profile_index = next((i for i, p in enumerate(current_profiles) if p["id"] == profile.id), None)

            if existing_profile_index is not None:
                current_profiles[existing_profile_index].update(profile_data)
            else:
                current_profiles.append(profile_data)

            self._update_profile_data(telegram_id, current_profiles)
            logger.info(f"Profile {profile.id} set for user {telegram_id}")

        except Exception as e:
            logger.error(f"Failed to set profile for user {telegram_id}: {e}")

    def get_current_profile(self, telegram_id: int) -> Profile | None:
        try:
            current_profiles = [
                Profile.from_dict(data) for data in self._get_profile_data(telegram_id) if data.get("is_current", True)
            ]
            if current_profiles:
                return max(current_profiles, key=lambda p: p.last_used)
            return None
        except Exception as e:
            logger.error(f"Failed to get current profile for user {telegram_id}: {e}")
            return None

    def get_profiles(self, telegram_id: str) -> list[Profile]:
        return [Profile.from_dict(data) for data in self._get_profile_data(telegram_id)]

    def get_coaches(self) -> list[Coach] | None:
        try:
            all_coaches = self.redis.hgetall("coaches")
            coaches_data = []
            for k, v in all_coaches.items():
                coach_dict = json.loads(v)
                coach_dict["id"] = k
                coach = Coach.from_dict(coach_dict)
                coaches_data.append(coach)
            random.shuffle(coaches_data)
            return coaches_data
        except Exception as e:
            logger.error(f"Failed to retrieve coach data: {e}")
            return

    def deactivate_profiles(self, telegram_id: str) -> None:
        try:
            profiles_data = self._get_profile_data(telegram_id)
            for profile_data in profiles_data:
                profile_data["is_current"] = False
            self._update_profile_data(telegram_id, profiles_data)
            logger.info(f"Profiles of user {telegram_id} deactivated")
        except Exception as e:
            logger.error(f"Failed to deactivate profiles of user {telegram_id}: {e}")

    def get_profile_info_by_key(self, telegram_id: int | str, profile_id: int, key: str) -> str | None:
        profiles = self._get_profile_data(telegram_id)
        for profile_data in profiles:
            if int(profile_data.get("id")) == int(profile_id):
                return profile_data.get(key)
        return None

    def set_profile_info_by_key(self, telegram_id: str, profile_id: int, key: str, value: Any) -> bool:
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
        except Exception as e:
            logger.error(f"Failed to set profile info for profile {profile_id}: {e}")
            return False

    def _set_data(self, key: str, profile_id: str, data: dict[str, Any], allowed_fields: list[str]) -> None:
        try:
            filtered_data = {k: data[k] for k in allowed_fields if k in data}
            existing_data = json.loads(self.redis.hget(key, profile_id) or "{}")
            existing_data.update(filtered_data)
            self.redis.hset(key, profile_id, json.dumps(existing_data))
            logger.info(f"Data for {profile_id} has been updated in {key}: {filtered_data}")
        except Exception as e:
            logger.error(f"Failed to set or update data for {profile_id} in {key}", e)

    def set_client_data(self, profile_id: str, client_data: dict) -> None:
        allowed_fields = [
            "name",
            "gender",
            "birth_date",
            "workout_experience",
            "workout_goals",
            "health_notes",
            "weight",
            "assigned_to",
            "tg_id",
        ]
        self._set_data("clients", profile_id, client_data, allowed_fields)

    def get_client_by_id(self, profile_id: int) -> Client | None:
        try:
            client_data = self.redis.hget("clients", str(profile_id))
            if client_data:
                data = json.loads(client_data)
                data["id"] = profile_id
                return Client.from_dict(data)
            else:
                logger.info(f"No client data found for client ID {profile_id}")
                raise UserServiceError
        except Exception as e:
            logger.error(f"Failed to get client data for client ID {profile_id}: {e}")
            raise UserServiceError

    def set_coach_data(self, profile_id: str, profile_data: dict) -> None:
        allowed_fields = [
            "name",
            "work_experience",
            "additional_info",
            "payment_details",
            "profile_photo",
            "verified",
            "assigned_to",
            "tg_id",
        ]
        self._set_data("coaches", profile_id, profile_data, allowed_fields)

    def get_coach_by_id(self, profile_id: int) -> Coach | None:
        try:
            coach_data = self.redis.hget("coaches", str(profile_id))
            if coach_data:
                data = json.loads(coach_data)
                data["id"] = profile_id
                return Coach.from_dict(data)
            else:
                logger.error(f"No data found for profile_id {profile_id} in cache")
                raise UserServiceError
        except Exception as e:
            logger.error(f"Failed to get data for profile_id from cache {profile_id}: {e}")
            raise UserServiceError

    def save_program(self, client_id: str, program_data: dict) -> None:
        try:
            self.redis.hset("workout_plans:programs", client_id, json.dumps(program_data))
            self.reset_program_payment_status(client_id, "program")
            logger.info(f"Program for client {client_id} saved in cache")
        except Exception as e:
            logger.error(f"Failed to save program in cache for client {client_id}: {e}")

    def get_program(self, profile_id: str) -> Program | None:
        try:
            program_data = self.redis.hget("workout_plans:programs", profile_id)
            if program_data:
                data = json.loads(program_data)
                data["profile"] = profile_id
                return Program.from_dict(data)
            else:
                logger.info(f"No program data found for profile_id {profile_id}")
                return None
        except Exception as e:
            logger.error(f"Failed to get program for profile_id {profile_id}: {e}")
            return None

    def set_payment_status(self, profile_id: str, paid: bool, service_type: str) -> None:
        try:
            self.redis.hset(f"workout_plans:payments:{service_type}", profile_id, json.dumps({"paid": paid}))
            logger.info(f"Program status for profile_id {profile_id} set to {paid}")
        except Exception as e:
            logger.error(f"Failed to set payment status for profile_id {profile_id}: {e}")

    def reset_program_payment_status(self, profile_id: str, service_type: str) -> None:
        try:
            self.redis.hdel(f"workout_plans:payments:{service_type}", profile_id)
            logger.info(f"Payment status for profile_id {profile_id} has been reset")
        except Exception as e:
            logger.error(f"Failed to reset payment status for profile_id {profile_id}: {e}")

    def check_payment_status(self, profile_id: str, service_type: str) -> bool:
        try:
            payment_status = self.redis.hget(f"workout_plans:payments:{service_type}", profile_id)
            if payment_status:
                return json.loads(payment_status).get("paid", False)
            else:
                logger.info(f"No payment data found for profile_id {profile_id}")
                return False
        except Exception as e:
            logger.error(f"Failed to check payment status for profile_id {profile_id}: {e}")
            return False

    def delete_program(self, profile_id: str) -> bool:
        try:
            self.redis.hdel("workout_plans:programs", profile_id)
            logger.info(f"Program for profile_id {profile_id} deleted from cache")
            return True
        except Exception as e:
            logger.error(f"Failed to delete program for profile_id {profile_id}: {e}")
            return False

    def save_subscription(self, profile_id: str, subscription_data: dict) -> None:
        try:
            self.redis.hset("workout_plans:subscriptions", profile_id, json.dumps(subscription_data))
            self.reset_program_payment_status(profile_id, "subscription")
            logger.info(f"Subscription for profile {profile_id} saved in cache")
        except Exception as e:
            logger.error(f"Failed to save subscription in cache for profile {profile_id}: {e}")

    def get_subscription(self, profile_id: str) -> Subscription | None:
        try:
            subscription_data = self.redis.hget("workout_plans:subscriptions", profile_id)
            if subscription_data:
                data = json.loads(subscription_data)
                data["profile"] = profile_id
                if isinstance(data["payment_date"], str):
                    payment_date = parse(data["payment_date"])
                    data["payment_date"] = payment_date.timestamp()
                else:
                    data["payment_date"] = float(data["payment_date"])
                return Subscription.from_dict(data)
            else:
                logger.info(f"No subscription data found for profile_id {profile_id}")
                return None
        except Exception as e:
            logger.error(f"Failed to get subscription for profile_id {profile_id}: {e}")
            return None

    def get_clients_to_survey(self) -> list[int]:
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%A").lower()
        clients_with_workout = []

        all_clients = self.redis.hgetall("clients")
        for client_id, _ in all_clients.items():
            subscription = self.get_subscription(client_id)
            if (
                subscription
                and subscription.enabled
                and subscription.exercises
                and yesterday in [day.lower() for day in subscription.workout_days]
            ):
                clients_with_workout.append(client_id)

        return clients_with_workout

    def cache_gif_filename(self, exercise_name: str, filename: str) -> None:
        try:
            self.redis.hset("exercise_gif_map", exercise_name, filename)
        except Exception as e:
            logger.info(f"Failed to cache gif filename for exercise {exercise_name}: {e}")

    def get_exercise_gif(self, exercise_name: str) -> str | None:
        try:
            return self.redis.hget("exercise_gif_map", exercise_name)
        except Exception as e:
            logger.info(f"Failed to get gif filename for exercise {exercise_name}: {e}")
            return None

    def delete_profile(self, telegram_id: int | str, profile_id: int) -> bool:
        try:
            profiles_data = self._get_profile_data(telegram_id)
            updated_profiles_data = [p for p in profiles_data if p["id"] != profile_id]

            if not updated_profiles_data:
                self.redis.hdel("user_profiles", str(telegram_id))
            else:
                self._update_profile_data(telegram_id, updated_profiles_data)

            logger.info(f"Profile {profile_id} deleted for user {telegram_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete profile {profile_id} for user {telegram_id}: {e}")
            return False


class UserService:
    def __init__(self, storage: UserProfileManager):
        self._backend_url = os.environ.get("BACKEND_URL")
        self._api_key = os.environ.get("API_KEY")
        self._storage = storage
        self._client = httpx.AsyncClient()

    @property
    def backend_url(self) -> str:
        return self._backend_url

    @property
    def api_key(self) -> str:
        return self._api_key

    @property
    def storage(self) -> UserProfileManager:
        return self._storage

    @property
    def client(self) -> httpx.AsyncClient:
        return self._client

    async def close(self) -> None:
        await self.client.aclose()

    async def _api_request(self, method: str, url: str, data: dict = None, headers: dict = None) -> tuple:
        logger.info(f"Executing {method.upper()} request to {url} with data: {data} and headers: {headers}")
        try:
            response = await self.client.request(method, url, json=data, headers=headers)
            if response.status_code in (204, 200, 201):
                try:
                    json_data = response.json()
                    return response.status_code, json_data
                except JSONDecodeError:
                    return response.status_code, None
            else:
                logger.error(
                    f"Request to {url} failed with status code {response.status_code} and response: {response.text}"
                )
                return response.status_code, response.text
        except httpx.HTTPError as e:
            logger.error(f"HTTP error occurred: {e}")
            raise UserServiceError(f"HTTP request failed: {e}")
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            raise UserServiceError(f"Unexpected error occurred: {e}")

    async def sign_up(self, **kwargs) -> bool:
        url = f"{self.backend_url}/api/v1/persons/create/"
        status_code, response = await self._api_request(
            "post", url, data=kwargs, headers={"Authorization": f"Api-Key {self.api_key}"}
        )
        if status_code == 400 and "error" in response:
            if "already exists" in response:
                raise UsernameUnavailable(response)
            elif "email" in response:
                raise EmailUnavailable(response)
        return status_code == 201

    async def edit_profile(self, profile_id: int, data: dict, token: str | None = None) -> bool:
        fields = [
            "language",
            "name",
            "gender",
            "birth_date",
            "workout_experience",
            "work_experience",
            "additional_info",
            "payment_details",
            "profile_photo",
            "workout_goals",
            "health_notes",
            "weight",
            "verified",
            "assigned_to",
        ]
        filtered_data = {key: data[key] for key in fields if key in data and data[key] is not None}
        url = f"{self.backend_url}/api/v1/persons/{profile_id}/"
        status_code, _ = await self._api_request("put", url, filtered_data, headers={"Authorization": f"Token {token}"})
        return status_code == 200

    async def log_in(self, username: str, password: str) -> str | None:
        url = f"{self.backend_url}/auth/token/login/"
        status_code, response = await self._api_request("post", url, {"username": username, "password": password})
        if status_code == 200 and "auth_token" in response:
            return response["auth_token"]
        return None

    async def log_out(self, tg_user_id: int) -> bool:
        current_profile = self.storage.get_current_profile(tg_user_id)
        if current_profile:
            auth_token = self.storage.get_profile_info_by_key(tg_user_id, current_profile.id, "auth_token")
            url = f"{self.backend_url}/auth/token/logout/"
            status_code, _ = await self._api_request("post", url, headers={"Authorization": f"Token {auth_token}"})
            if status_code == 204:
                self.storage.deactivate_profiles(str(tg_user_id))
                logger.info(f"User with profile_id {current_profile.id} logged out")
                return True
        return False

    async def get_profile_by_username(self, username: str) -> Profile | None:
        url = f"{self.backend_url}/api/v1/persons/{username}/"
        status_code, user_data = await self._api_request(
            "get", url, headers={"Authorization": f"Api-Key {self.api_key}"}
        )
        if status_code == 200:
            return Profile.from_dict(user_data)
        logger.info(f"Failed to retrieve profile for {username}. HTTP status: {status_code}")
        return None

    async def get_user_data(self, token: str) -> dict[str, str] | None:
        url = f"{self.backend_url}/api/v1/current-user/"
        status_code, response = await self._api_request("get", url, headers={"Authorization": f"Token {token}"})
        if status_code == 200:
            return response
        logger.info(f"Failed to retrieve user data. HTTP status: {status_code}")
        return None

    async def reset_password(self, email: str, token: str) -> bool:
        headers = {"Authorization": f"Token {token}"}
        status_code, _ = await self._api_request(
            "post", f"{self.backend_url}/api/v1/auth/users/reset_password/", {"email": email}, headers
        )
        logger.info(f"Password reset requested for {email}")
        return status_code == 204

    async def send_feedback(self, email: str, username: str, feedback: str) -> bool:
        url = f"{self.backend_url}/api/v1/send-feedback/"
        headers = {"Authorization": f"Api-Key {self.api_key}"}
        status_code, _ = await self._api_request(
            "post",
            url,
            {
                "email": email,
                "username": username,
                "feedback": feedback,
            },
            headers,
        )
        return status_code == 200

    async def save_program(self, client_id: str, exercises: dict[int, Exercise], split_number: int) -> None:
        url = f"{self.backend_url}/api/v1/programs/"
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

        program_data = dict(
            id=response.get("id"),
            split_number=split_number,
            exercises_by_day=exercises,
            created_at=response.get("created_at"),
            profile=client_id,
        )
        self.storage.save_program(client_id, program_data)

    async def delete_program(self, profile_id: str) -> bool:
        url = f"{self.backend_url}/api/v1/programs/delete_by_profile/{profile_id}/"
        headers = {"Authorization": f"Api-Key {self.api_key}"}
        status, _ = await self._api_request("delete", url, headers=headers)
        return status == 204

    async def create_subscription(self, user_id: int, price: int, workout_days: list[str]) -> int | None:
        url = f"{self.backend_url}/api/v1/subscriptions/"
        data = {
            "user": user_id,
            "enabled": True,
            "price": price,
            "workout_days": workout_days,
            "exercises": {},
        }
        status_code, response = await self._api_request(
            "post", url, data, headers={"Authorization": f"Api-Key {self.api_key}"}
        )
        if status_code == 201 and response:
            return response.get("id")
        return None

    async def get_subscription(self, user_id: int) -> Subscription | None:
        url = f"{self.backend_url}/api/v1/subscriptions/?user={user_id}"
        status_code, subscriptions = await self._api_request(
            "get", url, headers={"Authorization": f"Api-Key {self.api_key}"}
        )
        if status_code == 200 and subscriptions:
            return Subscription.from_dict(subscriptions[0])
        logger.info(f"Failed to retrieve subscription for user {user_id}. HTTP status: {status_code}")
        return None

    async def update_subscription(self, subscription_id: int, data: dict) -> bool:
        url = f"{self.backend_url}/api/v1/subscriptions/{subscription_id}/"
        status_code, response = await self._api_request(
            "put", url, data, headers={"Authorization": f"Api-Key {self.api_key}"}
        )
        return status_code == 200

    async def delete_profile(self, telegram_id, profile_id: int, token: str | None = None) -> bool:
        url = f"{self.backend_url}/api/v1/persons/{profile_id}/delete/"
        headers = {"Authorization": f"Token {token}"} if token else {}
        status_code, _ = await self._api_request("delete", url, headers=headers)
        if status_code == 204:
            return self.storage.delete_profile(telegram_id, profile_id)


user_session = UserProfileManager(os.getenv("REDIS_URL"))
user_service = UserService(user_session)
