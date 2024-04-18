import json
import os

import httpx
import loguru
import redis

from common.models import Profile

logger = loguru.logger


class UserSession:
    def __init__(self):
        self.redis_pool = None

    def init_redis(self) -> None:
        self.redis_pool = redis.from_url("redis://redis")

    def close_redis(self) -> None:
        self.redis_pool.close()
        self.redis_pool.wait_closed()

    def set_profile(self, profile_id: int, profile: Profile, auth_token: str) -> None:
        session_data = {
            'profile': profile,
            'auth_token': auth_token
        }
        with self.redis_pool.get() as conn:
            conn.set(profile_id, json.dumps(session_data))

    def get_profile(self, profile_id: int) -> Profile | None:
        with self.redis_pool.get() as conn:
            session_data = conn.get(profile_id)
            if session_data:
                return Profile.from_dict(json.loads(session_data.decode('utf-8'))['profile'])
            else:
                return None

    def get_auth_token(self, profile_id: int) -> str | None:
        with self.redis_pool.get() as conn:
            session_data = conn.get(profile_id)
            if session_data:
                return json.loads(session_data.decode('utf-8'))['auth_token']
            else:
                return None


class UserService:
    def __init__(self, session: UserSession):
        self.backend_url = os.environ.get("BACKEND_URL")
        self.session = session

    async def api_request(self, method: str, url: str, data: dict = None, headers: dict = None) -> tuple:
        # headers = {"Authorization": f"Api-Key {self.API_KEY_SECRET}"}
        logger.info(f"METHOD: {method.upper()} URL: {url} data: {data}")
        try:
            async with httpx.AsyncClient() as client:
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

    async def sign_up(self, data: dict) -> bool:
        url = f"{self.backend_url}/api/v1/persons/create/"
        status_code, _ = await self.api_request("post", url, data)
        return status_code == 201 if status_code else False

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

    async def current_user(self) -> Profile | None:
        pass
        # url = f"{self.backend_url}/api/v1/current-user/"

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
user_session.init_redis()
user_service = UserService(user_session)
