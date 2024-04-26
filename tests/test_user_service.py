from unittest.mock import AsyncMock, MagicMock

import pytest

from common.user_service import UserService


@pytest.mark.asyncio
async def test_log_in_successful(user_service: UserService) -> None:
    response_mock = AsyncMock(status_code=200)
    response_mock.json = MagicMock(return_value={"auth_token": "abc123"})
    user_service.client.request = AsyncMock(return_value=response_mock)

    token = await user_service.log_in("username", "password")

    assert token == "abc123"
    user_service.client.request.assert_called_once_with(
        "post",
        f"{user_service.backend_url}/auth/token/login/",
        json={"username": "username", "password": "password"},
        headers=None,
    )


@pytest.mark.asyncio
async def test_log_in_failed(user_service: UserService) -> None:
    json_mock = AsyncMock(return_value={"auth_token": "abc123"})
    user_service.client.request = AsyncMock(return_value=AsyncMock(status_code=400, json=json_mock))
    token = await user_service.log_in("username", "password")
    assert token is None
    user_service.client.request.assert_called_once_with(
        "post",
        f"{user_service.backend_url}/auth/token/login/",
        json={"username": "username", "password": "password"},
        headers=None,
    )


@pytest.mark.asyncio
async def test_send_feedback_successful(user_service: UserService) -> None:
    user_service.client.request = AsyncMock(
        return_value=AsyncMock(status_code=200, json=AsyncMock(return_value={"auth_token": "abc123"}))
    )
    success = await user_service.send_feedback("test@example.com", "testuser", "Great service!")
    assert success
    user_service.client.request.assert_called_once_with(
        "post",
        f"{user_service.backend_url}/api/v1/send-feedback/",
        json={"email": "test@example.com", "username": "testuser", "feedback": "Great service!"},
        headers=None,
    )
