from datetime import datetime
from unittest.mock import patch

import pytest

from common.exceptions import UserServiceError


@pytest.mark.asyncio
async def test_save_program_success(workout_service):
    client_id = 1
    exercises = {1: "Exercise 1", 2: "Exercise 2"}
    split_number = 3

    async def mock_api_request(method, url, data, headers):
        assert method == "post"
        assert url == "http://testserver/api/v1/programs/"
        assert data == {
            "profile": client_id,
            "exercises_by_day": exercises,
            "split_number": split_number,
        }
        assert headers == {"Authorization": "Api-Key test_api_key"}
        return 201, {
            "id": 10,
            "created_at": "2023-09-28T12:00:00Z",
        }

    with patch.object(workout_service, "_api_request", side_effect=mock_api_request):
        result = await workout_service.save_program(client_id, exercises, split_number)
        assert result == {
            "id": 10,
            "split_number": split_number,
            "exercises_by_day": exercises,
            "created_at": "2023-09-28T12:00:00Z",
            "profile": client_id,
        }


@pytest.mark.asyncio
async def test_save_program_failure(workout_service):
    client_id = 1
    exercises = {1: "Exercise 1", 2: "Exercise 2"}
    split_number = 3

    async def mock_api_request(method, url, data, headers):
        return 400, {"error": "Invalid data"}

    with patch.object(workout_service, "_api_request", side_effect=mock_api_request):
        with pytest.raises(UserServiceError) as exc_info:
            await workout_service.save_program(client_id, exercises, split_number)
        assert "Failed to save program" in str(exc_info.value)


@pytest.mark.asyncio
async def test_update_program_success(workout_service):
    program_id = 10
    data = {"field": "value"}

    async def mock_api_request(method, url, data, headers):
        assert method == "put"
        assert url == f"http://testserver/api/v1/programs/{program_id}/"
        assert headers == {"Authorization": "Api-Key test_api_key"}
        return 200, {}

    with patch.object(workout_service, "_api_request", side_effect=mock_api_request):
        result = await workout_service.update_program(program_id, data)
        assert result is True


@pytest.mark.asyncio
async def test_update_program_failure(workout_service):
    program_id = 10
    data = {"field": "value"}

    async def mock_api_request(method, url, data, headers):
        return 400, {}

    with patch.object(workout_service, "_api_request", side_effect=mock_api_request):
        result = await workout_service.update_program(program_id, data)
        assert result is False


@pytest.mark.asyncio
async def test_create_subscription_success(workout_service):
    profile_id = 1
    workout_days = ["Monday", "Wednesday", "Friday"]
    wishes = "Gain muscle"
    amount = 100
    auth_token = "test_auth_token"

    async def mock_api_request(method, url, data, headers):
        assert method == "post"
        assert url == "http://testserver/api/v1/subscriptions/"
        assert headers == {"Authorization": f"Token {auth_token}"}
        assert data == {
            "client_profile": profile_id,
            "enabled": False,
            "price": amount,
            "workout_days": workout_days,
            "payment_date": datetime.today().strftime("%Y-%m-%d"),
            "wishes": wishes,
            "exercises": {},
        }
        return 201, {"id": 20}

    with patch.object(workout_service, "_api_request", side_effect=mock_api_request):
        subscription_id = await workout_service.create_subscription(
            profile_id, workout_days, wishes, amount, auth_token
        )
        assert subscription_id == 20


@pytest.mark.asyncio
async def test_create_subscription_failure(workout_service):
    profile_id = 1
    workout_days = ["Monday", "Wednesday", "Friday"]
    wishes = "Gain muscle"
    amount = 100
    auth_token = "test_auth_token"

    async def mock_api_request(method, url, data, headers):
        return 400, {}

    with patch.object(workout_service, "_api_request", side_effect=mock_api_request):
        subscription_id = await workout_service.create_subscription(
            profile_id, workout_days, wishes, amount, auth_token
        )
        assert subscription_id is None


@pytest.mark.asyncio
async def test_update_subscription_success(workout_service):
    subscription_id = 20
    data = {"enabled": True}
    auth_token = "test_auth_token"

    async def mock_api_request(method, url, data, headers):
        assert method == "put"
        assert url == f"http://testserver/api/v1/subscriptions/{subscription_id}/"
        assert headers == {"Authorization": f"Token {auth_token}"}
        assert data == {"enabled": True}
        return 200, {}

    with patch.object(workout_service, "_api_request", side_effect=mock_api_request):
        result = await workout_service.update_subscription(subscription_id, data, auth_token)
        assert result is True


@pytest.mark.asyncio
async def test_update_subscription_failure(workout_service):
    subscription_id = 20
    data = {"enabled": True}
    auth_token = "test_auth_token"

    async def mock_api_request(method, url, data, headers):
        return 400, {}

    with patch.object(workout_service, "_api_request", side_effect=mock_api_request):
        result = await workout_service.update_subscription(subscription_id, data, auth_token)
        assert result is False
