import os
from json import JSONDecodeError
from typing import Any

import httpx
import loguru
from cryptography.fernet import InvalidToken

from common.cache_manager import CacheManager
from common.encrypter import encrypter
from common.exceptions import EmailUnavailable, UsernameUnavailable, UserServiceError
from common.models import Exercise, Profile, Subscription

logger = loguru.logger


class BackendService:
    def __init__(self, storage: CacheManager):
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
    def cache(self) -> CacheManager:
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
        url = f"{self.backend_url}api/v1/persons/create/"
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
            "current_tg_id",
            "language",
            "name",
            "gender",
            "born_in",
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
        if "payment_details" in data:
            data["payment_details"] = self.cache.encrypter.encrypt(data["payment_details"])
        filtered_data = {key: data[key] for key in fields if key in data and data[key] is not None}
        url = f"{self.backend_url}api/v1/persons/{profile_id}/"
        status_code, _ = await self._api_request("put", url, filtered_data, headers={"Authorization": f"Token {token}"})
        return status_code == 200

    async def get_user_token(self, profile_id: int) -> str | None:
        url = f"{self.backend_url}api/v1/get-user-token/"
        data = {"profile_id": profile_id}
        status_code, response = await self._api_request(
            "post", url, data=data, headers={"Authorization": f"Api-Key {self.api_key}"}
        )

        if status_code == 200 and "auth_token" in response:
            return response["auth_token"]
        else:
            logger.error(
                f"Failed to retrieve token for profile_id {profile_id}. Status code: {status_code}, response: {response}"
            )
            return None

    async def log_in(self, username: str, password: str) -> str | None:
        url = f"{self.backend_url}auth/token/login/"
        status_code, response = await self._api_request(
            "post", url, {"username": username, "password": password}, {"Authorization": f"Api-Key {self.api_key}"}
        )
        if status_code == 200 and "auth_token" in response:
            return response["auth_token"]
        logger.error(f"Failed to log in with username: {username}, status code: {status_code}, response: {response}")
        return None

    async def log_out(self, tg_user_id: int) -> bool:
        current_profile = self.cache.get_current_profile(tg_user_id)
        if current_profile:
            if auth_token := self.cache.get_profile_info_by_key(tg_user_id, current_profile.id, "auth_token"):
                url = f"{self.backend_url}auth/token/logout/"
                status_code, _ = await self._api_request("post", url, headers={"Authorization": f"Token {auth_token}"})
                if status_code == 204:
                    self.cache.deactivate_profiles(str(tg_user_id))
                    logger.info(f"User with profile_id {current_profile.id} logged out")
                    return True
        return False

    async def get_profile_by_username(self, username: str) -> Profile | None:
        url = f"{self.backend_url}api/v1/persons/{username}/"
        status_code, user_data = await self._api_request(
            "get", url, headers={"Authorization": f"Api-Key {self.api_key}"}
        )
        if status_code == 200:
            if "payment_details" in user_data and user_data["payment_details"]:
                try:
                    user_data["payment_details"] = self.cache.encrypter.decrypt(user_data["payment_details"])
                except InvalidToken:
                    logger.error(f"Failed to decrypt payment details for user {username}")
                    user_data["payment_details"] = "Invalid encrypted data"
            return Profile.from_dict(user_data)
        logger.info(f"Failed to retrieve profile for {username}. HTTP status: {status_code}")
        return None

    async def get_user_data(self, token: str) -> dict[str, str] | None:
        url = f"{self.backend_url}api/v1/current-user/"
        status_code, response = await self._api_request("get", url, headers={"Authorization": f"Token {token}"})
        if status_code == 200:
            return response
        logger.info(f"Failed to retrieve user data. HTTP status: {status_code}")
        return None

    async def reset_password(self, email: str, token: str) -> bool:
        headers = {"Authorization": f"Token {token}"}
        status_code, _ = await self._api_request(
            "post", f"{self.backend_url}api/v1/auth/users/reset_password/", {"email": email}, headers
        )
        logger.info(f"Password reset requested for {email}")
        return status_code == 204

    async def send_feedback(self, email: str, username: str, feedback: str) -> bool:
        url = f"{self.backend_url}api/v1/send-feedback/"
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
        url = f"{self.backend_url}api/v1/programs/"
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
        self.cache.save_program(client_id, program_data)

    async def delete_program(self, profile_id: str) -> bool:
        url = f"{self.backend_url}api/v1/programs/delete_by_profile/{profile_id}/"
        headers = {"Authorization": f"Api-Key {self.api_key}"}
        status, _ = await self._api_request("delete", url, headers=headers)
        return status == 204

    async def create_subscription(self, user_id: int, price: int, workout_days: list[str]) -> int | None:
        url = f"{self.backend_url}api/v1/subscriptions/"
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
        logger.error(f"Failed to create subscription for user {user_id}. HTTP status: {status_code}")
        return None

    async def get_subscription(self, user_id: int) -> Subscription | None:
        url = f"{self.backend_url}api/v1/subscriptions/?user={user_id}"
        status_code, subscriptions = await self._api_request(
            "get", url, headers={"Authorization": f"Api-Key {self.api_key}"}
        )
        if status_code == 200 and subscriptions:
            return Subscription.from_dict(subscriptions[0])
        logger.info(f"Failed to retrieve subscription for user {user_id}. HTTP status: {status_code}")
        return None

    async def update_subscription(self, subscription_id: int, data: dict) -> bool:
        url = f"{self.backend_url}api/v1/subscriptions/{subscription_id}/"
        status_code, response = await self._api_request(
            "put", url, data, headers={"Authorization": f"Api-Key {self.api_key}"}
        )
        if status_code == 200:
            return True
        logger.error(f"Failed to update subscription {subscription_id}. HTTP status: {status_code}")
        return False

    async def delete_profile(self, telegram_id, profile_id: int, token: str | None = None) -> bool:
        url = f"{self.backend_url}api/v1/persons/{profile_id}/delete/"
        headers = {"Authorization": f"Token {token}"} if token else {}
        status_code, _ = await self._api_request("delete", url, headers=headers)
        if status_code == 204:
            return self.cache.delete_profile(telegram_id, profile_id)

    async def get_user_email(self, profile_id: int) -> str | None:
        url = f"{self.backend_url}api/v1/persons/{profile_id}/"
        status_code, user_data = await self._api_request(
            "get", url, headers={"Authorization": f"Api-Key {self.api_key}"}
        )
        if status_code == 200 and user_data:
            user = user_data.get("user")
            if user:
                return user.get("email")
        logger.info(f"Failed to retrieve email for profile_id {profile_id}. HTTP status: {status_code}")
        return None

    async def get_profile_data(self, profile_id: int) -> dict[str, Any] | None:
        url = f"{self.backend_url}api/v1/persons/{profile_id}/"
        status_code, user_data = await self._api_request(
            "get", url, headers={"Authorization": f"Api-Key {self.api_key}"}
        )
        if status_code == 200 and user_data:
            return user_data

        logger.info(f"Failed to retrieve email for profile_id {profile_id}. HTTP status: {status_code}")
        return None

    async def send_welcome_email(self, email: str, username: str) -> bool:
        url = f"{self.backend_url}/api/v1/send-welcome-email/"
        data = {
            "email": email,
            "username": username
        }
        status_code, response = await self._api_request(
            "post", url, data=data, headers={"Authorization": f"Api-Key {self.api_key}"}
        )
        if status_code == 200:
            return True
        logger.error(f"Failed to send welcome email. Status code: {status_code}, response: {response}")
        return False

    async def create_payment(self, profile_id: int, payment_option: str, order_number: str, amount: int) -> bool:
        url = f"{self.backend_url}/api/v1/payments/"
        data = {
            "profile": profile_id,
            "order_number": order_number,
            "payment_option": payment_option,
            "amount": amount,
            "status": "PENDING",
        }
        status_code, response = await self._api_request(
            "post", url, data, headers={"Authorization": f"Api-Key {self.api_key}"}
        )
        return status_code == 201


cache_manager = CacheManager(os.getenv("REDIS_URL"), encrypter)
backend_service = BackendService(cache_manager)
