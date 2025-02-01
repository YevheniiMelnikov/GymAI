from urllib.parse import urljoin

import loguru

from services.api_service import APIService
from core.exceptions import UsernameUnavailable, EmailUnavailable
from core.models import Profile


logger = loguru.logger


class UserService(APIService):
    async def sign_up(self, **kwargs) -> bool:
        url = urljoin(self.api_url, "api/v1/profiles/create/")
        status_code, response = await self._api_request(
            "post", url, data=kwargs, headers={"Authorization": f"Api-Key {self.api_key}"}
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

    async def get_user_token(self, profile_id: int) -> str | None:
        url = urljoin(self.api_url, "api/v1/get-user-token/")
        data = {"profile_id": profile_id}
        status, response = await self._api_request(
            "post", url, data=data, headers={"Authorization": f"Api-Key {self.api_key}"}
        )

        if status == 200 and "auth_token" in response:
            return response["auth_token"]

        logger.error(f"Failed to retrieve token for profile {profile_id}. Status code: {status}, response: {response}")
        return None

    async def log_in(self, username: str, password: str) -> str | None:
        url = urljoin(self.api_url, "auth/token/login/")
        status_code, response = await self._api_request(
            "post", url, {"username": username, "password": password}, {"Authorization": f"Api-Key {self.api_key}"}
        )
        if status_code == 200 and "auth_token" in response:
            return response["auth_token"]

        logger.error(f"Failed to log in with username: {username}, status code: {status_code}, response: {response}")
        return None

    async def log_out(self, profile: Profile, auth_token: str) -> bool:
        if auth_token:
            url = urljoin(self.api_url, "auth/token/logout/")
            status_code, _ = await self._api_request("post", url, headers={"Authorization": f"Token {auth_token}"})
            if status_code == 204:
                logger.info(f"User with profile_id {profile.id} logged out")
                return True

        return False

    async def get_user_data(self, token: str) -> dict[str, str] | None:
        url = urljoin(self.api_url, "api/v1/current-user/")
        status_code, response = await self._api_request("get", url, headers={"Authorization": f"Token {token}"})
        if status_code == 200:
            return response

        logger.debug(f"Failed to retrieve user data. HTTP status: {status_code}")
        return None

    async def get_user_email(self, profile_id: int) -> str | None:
        url = urljoin(self.api_url, f"api/v1/profiles/{profile_id}/")
        status_code, user_data = await self._api_request(
            "get", url, headers={"Authorization": f"Api-Key {self.api_key}"}
        )
        if status_code == 200 and user_data:
            user = user_data.get("user")
            if user:
                return user.get("email")

        logger.info(f"Failed to retrieve email for profile_id {profile_id}. HTTP status: {status_code}")
        return None

    async def reset_password(self, email: str, token: str) -> bool:
        url = urljoin(self.api_url, "api/v1/auth/users/reset_password/")
        headers = {"Authorization": f"Token {token}"}
        status_code, _ = await self._api_request("post", url, {"email": email}, headers)
        logger.debug(f"Password reset requested for {email}")
        return status_code == 204


user_service = UserService()
