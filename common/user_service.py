import os

import httpx
import loguru

from common.models import Person

logger = loguru.logger


class UserService:
    BACKEND_URL = os.environ.get("BACKEND_URL")
    # API_KEY_SECRET = os.environ.get("API_KEY_SECRET")

    async def api_request(self, method: str, url: str, data: dict = None) -> tuple:
        # headers = {"Authorization": f"Api-Key {self.API_KEY_SECRET}"}
        logger.info(f"METHOD: {method.upper()} URL: {url} data: {data}")
        try:
            async with httpx.AsyncClient() as client:
                if method == "get":
                    response = await client.get(url)
                elif method == "post":
                    response = await client.post(url, data=data)
                elif method == "put":
                    response = await client.put(url, data=data)
                elif method == "delete":
                    response = await client.delete(url)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")

                return response.status_code, response.json()

        except Exception as e:
            logger.error(e)
            return None, None

    async def sign_up(self, data: dict) -> bool:
        url = f"{self.BACKEND_URL}/persons/create/"
        status_code, _ = await self.api_request("post", url, data)
        return status_code == 201 if status_code else False

    async def get_person(self, user_id: int) -> Person | None:
        url = f"{self.BACKEND_URL}/persons/{user_id}/"
        status_code, user_data = await self.api_request("get", url)
        if user_data and "user_id" in user_data:
            return Person.from_dict(user_data)
        else:
            return None

    async def edit_person(self, user_id: int, data: dict) -> bool:
        url = f"{self.BACKEND_URL}/persons/{user_id}/"
        status_code, _ = await self.api_request("put", url, data)
        return status_code == 200 if status_code else False

    async def delete_person(self, user_id: int) -> bool:
        url = f"{self.BACKEND_URL}/persons/{user_id}/"
        status_code, _ = await self.api_request("delete", url)
        return status_code == 404 if status_code else False

    async def current_person(self) -> Person | None:
        pass

    async def sign_in(self, username: str, password: str) -> bool:
        pass


user_service = UserService()
