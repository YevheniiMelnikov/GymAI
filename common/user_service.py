import json
import os

import httpx
import loguru
import redis

from common.exeptions import UserServiceError
from common.models import Profile

logger = loguru.logger


class UserProfileManager:
    def __init__(self, redis_url: str):
        self.redis_pool = redis.ConnectionPool.from_url(f"{redis_url}/1")

    def get_redis_connection(self):
        return redis.Redis(connection_pool=self.redis_pool)

    def close_pool(self) -> None:
        self.redis_pool.disconnect()

    def set_profile(
        self,
        profile: Profile,
        username: str,
        auth_token: str,
        telegram_id: int,
        email: str | None = None,
        is_current: bool = True,
    ) -> None:
        redis_conn = self.get_redis_connection()
        existing_data = redis_conn.hget("profiles", str(profile.id))
        if existing_data:
            existing_data = json.loads(existing_data)
            email = email or existing_data.get("email")

        session_data = {
            "profile": profile.to_dict(),
            "username": username,
            "auth_token": auth_token,
            "telegram_id": telegram_id,
            "email": email,
            "is_current": is_current,
        }
        redis_conn.hset("profiles", str(profile.id), json.dumps(session_data))

    def get_current_profile_by_tg_id(self, telegram_id: int) -> Profile | None:
        profiles = self.get_profiles(telegram_id)
        return next((profile for profile in profiles if getattr(profile, "is_current", True)), None)

    def get_profiles(self, telegram_id: int) -> list[Profile]:
        redis_conn = self.get_redis_connection()
        all_profiles = []
        for profile_id in redis_conn.hkeys("profiles"):
            session_data = redis_conn.hget("profiles", profile_id)
            if session_data:
                profile_data = json.loads(session_data)
                if profile_data.get("telegram_id") == telegram_id:
                    profile = Profile.from_dict(profile_data["profile"])
                    all_profiles.append(profile)
        return all_profiles

    def get_profile_info_by_key(self, profile_id: int, key: str) -> str | None:
        redis_conn = self.get_redis_connection()
        session_data = redis_conn.hget("profiles", str(profile_id))
        if session_data:
            session_data = json.loads(session_data)
            return session_data.get(key)
        return None

    def get_auth_token(self, profile_id: int) -> str | None:
        redis_conn = self.get_redis_connection()
        session_data = redis_conn.hget("profiles", str(profile_id))
        if session_data:
            return json.loads(session_data)["auth_token"]
        return None

    def deactivate_profile(self, profile_id: int) -> None:
        redis_conn = self.get_redis_connection()
        session_data = redis_conn.hget("profiles", str(profile_id))
        if session_data:
            profile_data = json.loads(session_data)
            profile_data["is_current"] = False
            redis_conn.hset("profiles", str(profile_id), json.dumps(profile_data))


class UserService:
    def __init__(self, session: UserProfileManager):
        self.backend_url = os.environ.get("BACKEND_URL")
        self.session = session
        self.client = httpx.AsyncClient()

    async def close(self):
        await self.client.aclose()

    async def api_request(self, method: str, url: str, data: dict = None, headers: dict = None) -> tuple:
        logger.info(f"Executing {method.upper()} request to {url} with data: {data} and headers: {headers}")
        try:
            response = await self.client.request(method, url, data=data, headers=headers)
            if response.status_code == 204:
                return response.status_code, None

            return response.status_code, response.json()

        except httpx.HTTPError as e:
            logger.error(f"HTTP error occurred: {str(e)}")
            raise UserServiceError(f"HTTP request failed: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            raise UserServiceError(f"Unexpected error occurred: {str(e)}")

    async def sign_up(self, **kwargs) -> Profile | None:
        url = f"{self.backend_url}/api/v1/persons/create/"
        status_code, response = await self.api_request("post", url, kwargs)
        if status_code == 201:
            return Profile.from_dict(response)
        elif status_code == 400 and "error" in response:
            error_message = response["error"]
            if "already exists" in error_message:
                raise UserServiceError(error_message)
        return None

    async def edit_profile(self, user_id: int, data: dict, token: str) -> bool:
        url = f"{self.backend_url}/api/v1/persons/{user_id}/"
        status_code, _ = await self.api_request("put", url, data, headers={"Authorization": f"Token {token}"})
        return status_code == 200

    async def log_in(self, username: str, password: str) -> str | None:
        url = f"{self.backend_url}/auth/token/login/"
        status_code, response = await self.api_request("post", url, {"username": username, "password": password})
        if status_code == 200 and "auth_token" in response:
            return response["auth_token"]
        return None

    async def log_out(self, tg_user_id: int) -> bool:
        current_profile = self.session.get_current_profile_by_tg_id(tg_user_id)
        if current_profile:
            auth_token = self.session.get_auth_token(current_profile.id)
            url = f"{self.backend_url}/auth/token/logout/"
            status_code, _ = await self.api_request("post", url, headers={"Authorization": f"Token {auth_token}"})
            if status_code == 204:
                self.session.deactivate_profile(current_profile.id)
                logger.info(f"User with profile_id {current_profile.id} logged out")
                return True
        return False

    async def get_profile_by_username(self, username: str, token: str) -> Profile | None:
        url = f"{self.backend_url}/api/v1/persons/{username}/"
        status_code, user_data = await self.api_request("get", url, headers={"Authorization": f"Token {token}"})
        if status_code == 200:
            return Profile.from_dict(user_data)
        logger.info(f"Failed to retrieve profile for {username}. HTTP status: {status_code}")
        return None

    async def request_password_reset(self, email: str) -> bool:  # TODO: IMPLEMENT
        url = f"{self.backend_url}/auth/users/reset_password/"
        data = {"email": email}
        status_code, _ = await self.api_request("post", url, data)
        return status_code == 204

    async def delete_profile(self, user_id: int) -> bool:  # TODO: NOT USED YET
        url = f"{self.backend_url}/api/v1/persons/{user_id}/"
        status_code, _ = await self.api_request("delete", url)
        return status_code == 404 if status_code else False


user_session = UserProfileManager(os.getenv("REDIS_URL"))
user_service = UserService(user_session)
