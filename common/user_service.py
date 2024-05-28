import json
import os
import random
import time
from json import JSONDecodeError
from typing import Any

import httpx
import loguru
import redis

from common.exceptions import UsernameUnavailable, UserServiceError
from common.models import Client, Coach, Profile, Subscription

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
            current_profiles_data = self.redis.hget("user_profiles", telegram_id)
            current_profiles = json.loads(current_profiles_data) if current_profiles_data else []

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

            self.redis.hset("user_profiles", telegram_id, json.dumps(current_profiles))
            logger.info(f"Profile {profile.id} set for user {telegram_id}")

        except Exception as e:
            logger.error(f"Failed to set profile for user {telegram_id}: {e}")

    def get_current_profile(self, telegram_id: int) -> Profile | None:
        try:
            profiles_data = json.loads(self.redis.hget("user_profiles", str(telegram_id)) or "[]")
            current_profiles = [Profile.from_dict(data) for data in profiles_data if data.get("is_current", True)]
            if current_profiles:
                return max(current_profiles, key=lambda p: p.last_used)
            return None
        except Exception as e:
            logger.error(f"Failed to get current profile for user {telegram_id}: {e}")
            return None

    def get_profiles(self, telegram_id: str) -> list[Profile]:
        profiles_data = json.loads(self.redis.hget("user_profiles", telegram_id) or "[]")
        return [Profile.from_dict(data) for data in profiles_data]

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
            profiles_data = json.loads(self.redis.hget("user_profiles", telegram_id) or "[]")
            for profile_data in profiles_data:
                profile_data["is_current"] = False
            self.redis.hset("user_profiles", telegram_id, json.dumps(profiles_data))
            logger.info(f"Profiles of user {telegram_id} deactivated")
        except Exception as e:
            logger.error(f"Failed to deactivate profiles of user {telegram_id}: {e}")

    def get_profile_info_by_key(self, telegram_id: int | str, profile_id: int, key: str) -> str | None:
        profiles = json.loads(self.redis.hget("user_profiles", str(telegram_id)) or "[]")
        for profile_data in profiles:
            if profile_data.get("id") == int(profile_id):
                return profile_data.get(key)
        return None

    def set_profile_info_by_key(self, telegram_id: str, profile_id: str, key: str, value: Any) -> bool:
        try:
            profiles_data = json.loads(self.redis.hget("user_profiles", telegram_id) or "[]")
            for profile_data in profiles_data:
                if profile_data.get("id") == profile_id:
                    profile_data[key] = value
                    break
            else:
                return False
            self.redis.hset("user_profiles", telegram_id, json.dumps(profiles_data))
            return True
        except Exception as e:
            logger.error(f"Failed to set profile info for user {telegram_id} and profile {profile_id}: {e}")
            return False

    def set_client_data(self, profile_id: str, client_data: dict) -> None:
        try:
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
            filtered_client_data = {key: client_data[key] for key in allowed_fields if key in client_data}
            existing_data = json.loads(self.redis.hget("clients", profile_id) or "{}")
            existing_data.update(filtered_client_data)
            self.redis.hset("clients", profile_id, json.dumps(existing_data))
            logger.info(f"Client data for profile_id {profile_id} has been updated: {client_data}")
        except Exception as e:
            logger.error(f"Failed to set or update client data for {profile_id}: {e}")

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
        try:
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
            filtered_coach_data = {key: profile_data[key] for key in allowed_fields if key in profile_data}
            existing_data = json.loads(self.redis.hget("coaches", profile_id) or "{}")
            existing_data.update(filtered_coach_data)
            self.redis.hset("coaches", profile_id, json.dumps(existing_data))
            logger.info(f"Updated profile_data {profile_id}: {profile_data}")
        except Exception as e:
            logger.error(f"Failed to set data for profile_data {profile_id}: {e}")

    def get_coach_by_id(self, profile_id: int) -> Coach | None:
        try:
            coach_data = self.redis.hget("coaches", str(profile_id))
            if coach_data:
                data = json.loads(coach_data)
                data["id"] = profile_id
                return Coach.from_dict(data)
            else:
                logger.info(f"No data found for profile_id {profile_id} in cache")
                raise UserServiceError
        except Exception as e:
            logger.error(f"Failed to get data for profile_id from cache {profile_id}: {e}")
            raise UserServiceError

    def save_program(self, client_id: str, exercises: list[str]) -> None:
        try:
            self.redis.hset("programs", client_id, json.dumps({"exercises": exercises}))
            logger.info(f"Program for client {client_id} saved in cache")
        except Exception as e:
            logger.error(f"Failed to save program in cache for client {client_id}: {e}")

    def get_program(self, profile_id: str) -> dict | None:
        try:
            program_data = self.redis.hget("programs", profile_id)
            if program_data:
                data = json.loads(program_data)
                data["profile"] = profile_id
                return data
            else:
                logger.info(f"No program data found for profile_id {profile_id}")
                return None
        except Exception as e:
            logger.error(f"Failed to get program for profile_id {profile_id}: {e}")
            return None

    def cache_gif_filename(self, exercise: str, filename: str) -> None:
        try:
            self.redis.hset("exercise_gif_map", exercise, filename)
        except Exception as e:
            logger.info(f"Failed to cache gif filename for exercise {exercise}: {e}")

    def get_exercise_gif(self, exercise: str) -> str | None:
        try:
            return self.redis.hget("exercise_gif_map", exercise)
        except Exception as e:
            logger.info(f"Failed to get gif filename for exercise {exercise}: {e}")
            return None

    def get_subscription(self, profile_id: int) -> Subscription | None:  # TODO: IMPLEMENT
        pass


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

    async def api_request(self, method: str, url: str, data: dict = None, headers: dict = None) -> tuple:
        logger.info(f"Executing {method.upper()} request to {url} with data: {data} and headers: {headers}")
        try:
            response = await self.client.request(method, url, json=data, headers=headers)
            if response.status_code in (204, 200):
                try:
                    json_data = response.json()
                    return response.status_code, json_data
                except JSONDecodeError:
                    return response.status_code, None
            else:
                return response.status_code, response.text
        except httpx.HTTPError as e:
            logger.error(f"HTTP error occurred: {e}")
            raise UserServiceError(f"HTTP request failed: {e}")
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            raise UserServiceError(f"Unexpected error occurred: {e}")

    async def sign_up(self, **kwargs) -> bool:
        url = f"{self.backend_url}/api/v1/persons/create/"
        status_code, response = await self.api_request(
            "post", url, data=kwargs, headers={"Authorization": f"Api-Key {self.api_key}"}
        )
        if status_code == 400 and "error" in response:
            if "already exists" in response:
                raise UsernameUnavailable(response)

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
        status_code, _ = await self.api_request("put", url, filtered_data, headers={"Authorization": f"Token {token}"})
        return status_code == 200

    async def log_in(self, username: str, password: str) -> str | None:
        url = f"{self.backend_url}/auth/token/login/"
        status_code, response = await self.api_request("post", url, {"username": username, "password": password})
        if status_code == 200 and "auth_token" in response:
            return response["auth_token"]
        return None

    async def log_out(self, tg_user_id: int) -> bool:
        current_profile = self.storage.get_current_profile(tg_user_id)
        if current_profile:
            auth_token = self.storage.get_profile_info_by_key(tg_user_id, current_profile.id, "auth_token")
            url = f"{self.backend_url}/auth/token/logout/"
            status_code, _ = await self.api_request("post", url, headers={"Authorization": f"Token {auth_token}"})
            if status_code == 204:
                self.storage.deactivate_profiles(str(tg_user_id))
                logger.info(f"User with profile_id {current_profile.id} logged out")
                return True
        return False

    async def get_profile_by_username(self, username: str) -> Profile | None:
        url = f"{self.backend_url}/api/v1/persons/{username}/"
        status_code, user_data = await self.api_request(
            "get", url, headers={"Authorization": f"Api-Key {self.api_key}"}
        )
        if status_code == 200:
            return Profile.from_dict(user_data)
        logger.info(f"Failed to retrieve profile for {username}. HTTP status: {status_code}")
        return None

    async def get_user_data(self, token: str) -> dict[str, str] | None:
        url = f"{self.backend_url}/api/v1/current-user/"
        status_code, response = await self.api_request("get", url, headers={"Authorization": f"Token {token}"})
        if status_code == 200:
            return response
        logger.info(f"Failed to retrieve user data. HTTP status: {status_code}")
        return None

    async def reset_password(self, email: str, token: str) -> bool:
        headers = {"Authorization": f"Token {token}"}
        status_code, _ = await self.api_request(
            "post", f"{self.backend_url}/api/v1/auth/users/reset_password/", {"email": email}, headers
        )
        logger.info(f"Password reset requested for {email}")
        return status_code == 204

    async def send_feedback(self, email: str, username: str, feedback: str) -> bool:
        url = f"{self.backend_url}/api/v1/send-feedback/"
        status_code, _ = await self.api_request(
            "post",
            url,
            {
                "email": email,
                "username": username,
                "feedback": feedback,
            },
        )
        return status_code == 200

    async def save_program(self, client_id: str, exercises: list[str]) -> None:
        self.storage.save_program(client_id, exercises)
        url = f"{self.backend_url}/api/v1/programs/"
        data = {
            "profile": client_id,
            "exercises": exercises,
        }
        status_code, response = await self.api_request(
            "post", url, data, headers={"Authorization": f"Api-Key {self.api_key}"}
        )
        if status_code != 201:
            logger.error(f"Failed to save program for client {client_id}: {response}")
            raise UserServiceError(f"Failed to save program: {response}")

    async def delete_profile(self, profile_id: int) -> bool:  # TODO: NOT USED YET
        url = f"{self.backend_url}/api/v1/persons/{profile_id}/"
        status_code, _ = await self.api_request("delete", url, headers={"Authorization": f"Api-Key {self.api_key}"})
        return status_code == 404 if status_code else False


user_session = UserProfileManager(os.getenv("REDIS_URL"))
user_service = UserService(user_session)
