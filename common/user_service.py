import json
import os

import httpx
import loguru
import redis

from common.exeptions import UsernameUnavailable
from common.models import Profile

logger = loguru.logger


class UserProfileManager:
    def __init__(self):
        self.redis_pool = redis.Redis.from_url("redis://redis")  # TODO: SEPARATE TO DB1

    def close_pool(self) -> None:
        self.redis_pool.close()

    def set_profile(self, profile: Profile, auth_token: str, telegram_id: int, is_current: bool = True) -> None:
        session_data = {
            "profile": profile.to_dict(),
            "auth_token": auth_token,
            "is_current": is_current,
            "telegram_id": telegram_id
        }
        self.redis_pool.hset("profiles", str(profile.id), json.dumps(session_data))

    def current_profile(self, telegram_id: int) -> Profile | None:
        profiles = self.get_profiles(telegram_id)
        for profile in profiles:
            profile_data = self.redis_pool.hget("profiles", str(profile.id))
            if profile_data:
                profile_data = json.loads(profile_data)
                if profile_data.get("is_current", True):
                    return profile
        return None

    def get_profiles(self, telegram_id: int) -> list[Profile]:
        all_profiles = []
        for profile_id in self.redis_pool.hkeys("profiles"):
            profile_data = self.redis_pool.hget("profiles", profile_id)
            if profile_data:
                profile_data = json.loads(profile_data)
                if profile_data.get("telegram_id") == telegram_id:
                    all_profiles.append(Profile.from_dict(profile_data["profile"]))
        return all_profiles

    def get_auth_token(self, profile_id: int) -> str | None:
        session_data = self.redis_pool.hget("profiles", str(profile_id))
        if session_data:
            return json.loads(session_data)["auth_token"]
        else:
            return None

    def deactivate_profile(self, profile_id: int) -> None:
        session_data = self.redis_pool.hget("profiles", str(profile_id))
        if session_data:
            profile_data = json.loads(session_data)
            profile_data["is_current"] = False
            self.redis_pool.hset("profiles", str(profile_id), json.dumps(profile_data))


class UserService:
    def __init__(self, session: UserProfileManager):
        self.backend_url = os.environ.get("BACKEND_URL")
        self.session = session

    async def api_request(self, method: str, url: str, data: dict = None, headers: dict = None) -> tuple:
        logger.info(f"METHOD: {method.upper()} URL: {url} data: {data}, headers: {headers}")
        try:
            async with httpx.AsyncClient() as client:  # TODO: PASS API_KEY
                if method == "get":
                    response = await client.get(url)
                elif method == "post":
                    response = await client.post(url, data=data, headers=headers)
                elif method == "put":
                    response = await client.put(url, data=data, headers=headers)
                elif method == "delete":
                    response = await client.delete(url)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")

                if response.status_code == 204:
                    return response.status_code, None

                return response.status_code, response.json()

        except Exception as e:
            logger.error(e)
            return None, None

    async def sign_up(self, **kwargs) -> Profile | None:
        url = f"{self.backend_url}/api/v1/persons/create/"
        status_code, response = await self.api_request(
            "post",
            url,
            {
                "username": kwargs.get("username"),
                "password": kwargs.get("password"),
                "email": kwargs.get("email"),
                "status": kwargs.get("status"),
                "language": kwargs.get("language"),
            },
        )
        if status_code == 201:
            return Profile.from_dict(
                dict(id=response["id"], status=kwargs.get("status"), language=kwargs.get("language"))
            )
        elif status_code == 400 and "error" in response:
            error_message = response["error"]
            if "already exists" in error_message:
                raise UsernameUnavailable(error_message)
            return None
        else:
            return None

    async def get_user(self, user_id: int) -> Profile | None:
        url = f"{self.backend_url}/api/v1/persons/{user_id}/"
        status_code, user_data = await self.api_request("get", url)
        if user_data and "user_id" in user_data:
            return Profile.from_dict(user_data)
        else:
            return None

    async def edit_user(self, user_id: int, data: dict) -> bool:
        url = f"{self.backend_url}/api/v1/persons/{user_id}/"
        status_code, _ = await self.api_request("put", url, data)
        return status_code == 200 if status_code else False

    async def delete_user(self, user_id: int) -> bool:
        url = f"{self.backend_url}/api/v1/persons/{user_id}/"
        status_code, _ = await self.api_request("delete", url)
        return status_code == 404 if status_code else False

    async def current_user(self, token: str) -> Profile | None:
        url = f"{self.backend_url}/api/v1/current-user/"
        status_code, user_data = await self.api_request("get", url, headers={"Authorization": f"Token {token}"})
        if user_data and "user_id" in user_data:
            return Profile.from_dict(user_data)
        else:
            return None

    async def log_in(self, username: str, password: str) -> str | None:
        url = f"{self.backend_url}/auth/token/login/"
        status_code, response = await self.api_request("post", url, data={"username": username, "password": password})
        if status_code == 200 and response.get("auth_token"):
            logger.info(f"User {username} logged in")
            return response["auth_token"]
        else:
            return None

    async def log_out(self, tg_user_id: int) -> bool:
        if current_profile := self.session.current_profile(tg_user_id):
            auth_token = self.session.get_auth_token(current_profile.id)
            url = f"{self.backend_url}/auth/token/logout/"
            status_code, _ = await self.api_request("post", url, headers={"Authorization": f"Token {auth_token}"})
            if status_code == 204:
                user_service.session.deactivate_profile(current_profile.id)
                logger.info(f"User with profile_id {current_profile.id} logged out")
                return True
            else:
                return False


user_session = UserProfileManager()
user_service = UserService(user_session)
