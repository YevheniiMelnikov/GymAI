import json
import os

import httpx
import loguru
import redis

from common.exeptions import UsernameUnavailable
from common.models import Profile

logger = loguru.logger


class UserSession:
    def __init__(self):
        self.redis_pool = redis.Redis.from_url("redis://redis")  # TODO: SEPARATE TO DB1

    def close_pool(self) -> None:
        self.redis_pool.close()

    def set_profile(self, profile: Profile, auth_token: str) -> None:
        session_data = {"profile": profile.to_dict(), "auth_token": auth_token}
        self.redis_pool.hset("profiles", str(profile.id), json.dumps(session_data))

    def get_profile(self, profile_id: int) -> Profile | None:
        session_data = self.redis_pool.hget("profiles", str(profile_id))
        if session_data:
            return Profile.from_dict(json.loads(session_data)["profile"])
        else:
            return None

    def get_auth_token(self, profile_id: int) -> str | None:
        session_data = self.redis_pool.hget("profiles", str(profile_id))
        if session_data:
            return json.loads(session_data)["auth_token"]
        else:
            return None


class UserService:
    def __init__(self, session: UserSession):
        self.backend_url = os.environ.get("BACKEND_URL")
        self.session = session

    async def api_request(self, method: str, url: str, data: dict = None, headers: dict = None) -> tuple:
        logger.info(f"METHOD: {method.upper()} URL: {url} data: {data}")
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

    async def log_out(self, token: str) -> bool:
        url = f"{self.backend_url}/auth/token/logout/"
        status_code, _ = await self.api_request("post", url, headers={"Token": token})
        return status_code == 204


user_session = UserSession()
user_service = UserService(user_session)
