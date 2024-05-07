import json
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from common.user_service import UserProfileManager, UserService


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


@pytest.mark.asyncio
async def test_get_current_profile_by_tg_id(profile_manager: UserProfileManager) -> None:
    profile_manager.redis.hget.return_value = json.dumps(
        [{"id": 1, "status": "client", "is_current": True, "last_used": time.time()}]
    )
    profile = profile_manager.get_current_profile(12345)
    assert profile is not None
    assert profile.id == 1


@pytest.mark.asyncio
async def test_deactivate_profiles(profile_manager: UserProfileManager) -> None:
    profile_manager.redis.hget.return_value = json.dumps([{"id": 1, "status": "client", "is_current": True}])
    profile_manager.deactivate_profiles(12345)
    profile_manager.redis.hset.assert_called_once()
    args, kwargs = profile_manager.redis.hset.call_args
    updated_profiles = json.loads(args[2])
    assert all(not p["is_current"] for p in updated_profiles)


@pytest.mark.asyncio
async def test_set_profile_info_by_key(profile_manager: UserProfileManager) -> None:
    profile_manager.redis.hget.return_value = json.dumps([{"id": 1, "status": "client", "is_current": True}])
    success = profile_manager.set_profile_info_by_key(12345, 1, "language", "eng")
    assert success, "The function should successfully update the profile info."
    profile_manager.redis.hset.assert_called_once()
    args, kwargs = profile_manager.redis.hset.call_args
    updated_profiles = json.loads(args[2])
    assert updated_profiles[0]["language"] == "eng"
