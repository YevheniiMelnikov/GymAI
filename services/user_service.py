import loguru

from services.backend_service import BackendService
from common.exceptions import UsernameUnavailable, EmailUnavailable
from common.models import Profile


logger = loguru.logger


class UserService(BackendService):
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

    async def get_user_token(self, profile_id: int) -> str | None:
        url = f"{self.backend_url}api/v1/get-user-token/"
        data = {"profile_id": profile_id}
        status, response = await self._api_request(
            "post", url, data=data, headers={"Authorization": f"Api-Key {self.api_key}"}
        )

        if status == 200 and "auth_token" in response:
            return response["auth_token"]
        else:
            logger.error(
                f"Failed to retrieve token for profile {profile_id}. Status code: {status}, response: {response}"
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

    async def log_out(self, profile: Profile, auth_token: str) -> bool:
        if auth_token:
            url = f"{self.backend_url}auth/token/logout/"
            status_code, _ = await self._api_request("post", url, headers={"Authorization": f"Token {auth_token}"})
            if status_code == 204:
                logger.info(f"User with profile_id {profile.id} logged out")
                return True
        return False

    async def get_user_data(self, token: str) -> dict[str, str] | None:
        url = f"{self.backend_url}api/v1/current-user/"
        status_code, response = await self._api_request("get", url, headers={"Authorization": f"Token {token}"})
        if status_code == 200:
            return response
        logger.debug(f"Failed to retrieve user data. HTTP status: {status_code}")
        return None

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

    async def reset_password(self, email: str, token: str) -> bool:
        headers = {"Authorization": f"Token {token}"}
        status_code, _ = await self._api_request(
            "post", f"{self.backend_url}api/v1/auth/users/reset_password/", {"email": email}, headers
        )
        logger.debug(f"Password reset requested for {email}")
        return status_code == 204


user_service = UserService()
