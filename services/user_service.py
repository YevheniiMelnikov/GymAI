from urllib.parse import urljoin

from common.logger import logger

from services.api_service import APIClient
from core.exceptions import UsernameUnavailable, EmailUnavailable
from core.models import Profile


class UserService(APIClient):
    @classmethod
    async def sign_up(cls, **kwargs) -> bool:
        url = urljoin(cls.api_url, "api/v1/profiles/create/")
        status_code, response = await cls._api_request(
            "post", url, data=kwargs, headers={"Authorization": f"Api-Key {cls.api_key}"}
        )
        if status_code == 400 and "error" in response:
            error_message = response["error"]
            if error_message == "Username already exists":
                username = kwargs.get("username", "Unknown")
                logger.error(f"Username {username} already exists.")
                raise UsernameUnavailable(username)
            elif error_message == "This email already taken":
                email = kwargs.get("email", "Unknown")
                logger.error(f"Email {email} already taken.")
                raise EmailUnavailable(email)
            else:
                logger.error(f"Sign up failed with error: {error_message}, response: {response}")
                return False

        return status_code == 201

    @classmethod
    async def get_user_token(cls, profile_id: int) -> str | None:
        url = urljoin(cls.api_url, "api/v1/get-user-token/")
        data = {"profile_id": profile_id}
        status, response = await cls._api_request(
            "post", url, data=data, headers={"Authorization": f"Api-Key {cls.api_key}"}
        )

        if status == 200 and "auth_token" in response:
            return response["auth_token"]

        logger.error(f"Failed to retrieve token for profile {profile_id}. Status code: {status}, response: {response}")
        return None

    @classmethod
    async def log_in(cls, username: str, password: str) -> str | None:
        url = urljoin(cls.api_url, "auth/token/login/")
        status_code, response = await cls._api_request(
            "post", url, {"username": username, "password": password}, {"Authorization": f"Api-Key {cls.api_key}"}
        )
        if status_code == 200 and "auth_token" in response:
            return response["auth_token"]

        logger.error(f"Failed to log in with username: {username}, status code: {status_code}, response: {response}")
        return None

    @classmethod
    async def log_out(cls, profile: Profile, auth_token: str) -> bool:
        if auth_token:
            url = urljoin(cls.api_url, "auth/token/logout/")
            status_code, _ = await cls._api_request("post", url, headers={"Authorization": f"Token {auth_token}"})
            if status_code == 204:
                logger.info(f"User with profile_id {profile.id} logged out")
                return True

        return False

    @classmethod
    async def get_user_data(cls, token: str) -> dict[str, str] | None:
        url = urljoin(cls.api_url, "api/v1/current-user/")
        status_code, response = await cls._api_request("get", url, headers={"Authorization": f"Token {token}"})
        if status_code == 200:
            return response

        logger.debug(f"Failed to retrieve user data. HTTP status: {status_code}")
        return None

    @classmethod
    async def get_user_email(cls, profile_id: int) -> str | None:
        url = urljoin(cls.api_url, f"api/v1/profiles/{profile_id}/")
        status_code, user_data = await cls._api_request("get", url, headers={"Authorization": f"Api-Key {cls.api_key}"})
        if status_code == 200 and user_data:
            user = user_data.get("user")
            if user:
                return user.get("email")

        logger.info(f"Failed to retrieve email for profile_id {profile_id}. HTTP status: {status_code}")
        return None

    @classmethod
    async def reset_password(cls, email: str, token: str) -> bool:
        url = urljoin(cls.api_url, "api/v1/auth/users/reset_password/")
        headers = {"Authorization": f"Token {token}"}
        status_code, _ = await cls._api_request("post", url, {"email": email}, headers)
        logger.debug(f"Password reset requested for {email}")
        return status_code == 204
