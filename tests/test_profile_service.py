from unittest.mock import patch

import pytest


@pytest.mark.asyncio
async def test_get_profile_success(profile_service):
    async def mock_api_request(method, url, headers):
        assert method == "get"
        assert url == "http://testserver/api/v1/profiles/1/"
        assert headers == {"Authorization": "Api-Key test_api_key"}
        return 200, {"id": 1, "name": "Test User"}

    with patch.object(profile_service, "_api_request", side_effect=mock_api_request):
        user_data = await profile_service.get_profile(profile_id=1)
        assert user_data == {"id": 1, "name": "Test User"}


@pytest.mark.asyncio
async def test_get_profile_failure(profile_service):
    async def mock_api_request(method, url, headers):
        return 404, None

    with patch.object(profile_service, "_api_request", side_effect=mock_api_request):
        user_data = await profile_service.get_profile(profile_id=1)
        assert user_data is None


@pytest.mark.asyncio
async def test_get_profile_by_username_not_found(profile_service):
    async def mock_api_request(method, url, headers):
        return 404, None

    with patch.object(profile_service, "_api_request", side_effect=mock_api_request):
        profile = await profile_service.get_profile_by_username(username="testuser")
        assert profile is None


@pytest.mark.asyncio
async def test_get_profile_by_telegram_id_success(profile_service):
    async def mock_api_request(method, url, headers):
        return 200, {"id": 1, "name": "Test User"}

    with patch.object(profile_service, "_api_request", side_effect=mock_api_request):
        profile_data = await profile_service.get_profile_by_telegram_id(telegram_id=123456)
        assert profile_data == {"id": 1, "name": "Test User"}


@pytest.mark.asyncio
async def test_get_profile_by_telegram_id_failure(profile_service):
    async def mock_api_request(method, url, headers):
        return 404, None

    with patch.object(profile_service, "_api_request", side_effect=mock_api_request):
        profile_data = await profile_service.get_profile_by_telegram_id(telegram_id=123456)
        assert profile_data is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status_code, expected_result",
    [
        (204, True),
        (400, False),
    ],
)
async def test_delete_profile(profile_service, status_code, expected_result):
    async def mock_api_request(method, url, headers):
        return status_code, None

    with patch.object(profile_service, "_api_request", side_effect=mock_api_request):
        result = await profile_service.delete_profile(profile_id=1)
        assert result == expected_result


@pytest.mark.asyncio
async def test_delete_profile_with_token(profile_service):
    async def mock_api_request(method, url, headers):
        assert headers == {"Authorization": "Token test_token"}
        return 204, None

    with patch.object(profile_service, "_api_request", side_effect=mock_api_request):
        result = await profile_service.delete_profile(profile_id=1, token="test_token")
        assert result is True


@pytest.mark.asyncio
async def test_edit_profile_success(profile_service):
    data = {
        "current_tg_id": 123456,
        "language": "en",
        "name": "New Name",
        "assigned_to": "coach1",
        "extra_field": "should be ignored",
    }

    async def mock_api_request(method, url, data, headers):
        expected_data = {
            "current_tg_id": 123456,
            "language": "en",
            "name": "New Name",
            "assigned_to": "coach1",
        }
        assert data == expected_data
        return 200, None

    with patch.object(profile_service, "_api_request", side_effect=mock_api_request):
        result = await profile_service.edit_profile(profile_id=1, data=data)
        assert result is True


@pytest.mark.asyncio
async def test_edit_profile_failure(profile_service):
    data = {"name": "New Name"}

    async def mock_api_request(method, url, data, headers):
        return 400, None

    with patch.object(profile_service, "_api_request", side_effect=mock_api_request):
        result = await profile_service.edit_profile(profile_id=1, data=data)
        assert result is False


@pytest.mark.asyncio
async def test_edit_client_profile_success(profile_service):
    data = {
        "gender": "male",
        "born_in": "1990-01-01",
        "workout_experience": "2 years",
        "workout_goals": "Build muscle",
        "health_notes": "None",
        "weight": 80,
        "coach": "coach1",
        "extra_field": "should be ignored",
    }

    async def mock_api_request(method, url, data, headers):
        expected_data = {
            "gender": "male",
            "born_in": "1990-01-01",
            "workout_experience": "2 years",
            "workout_goals": "Build muscle",
            "health_notes": "None",
            "weight": 80,
            "coach": "coach1",
            "profile_id": 1,
        }
        assert data == expected_data
        return 200, None

    with patch.object(profile_service, "_api_request", side_effect=mock_api_request):
        result = await profile_service.edit_client_profile(profile_id=1, data=data)
        assert result is True


@pytest.mark.asyncio
async def test_edit_client_profile_failure(profile_service):
    data = {"gender": "male"}

    async def mock_api_request(method, url, data, headers):
        return 400, None

    with patch.object(profile_service, "_api_request", side_effect=mock_api_request):
        result = await profile_service.edit_client_profile(profile_id=1, data=data)
        assert result is False


@pytest.mark.asyncio
async def test_edit_coach_profile_success(profile_service):
    data = {
        "surname": "Doe",
        "payment_details": "account info",
        "verified": True,
        "extra_field": "should be ignored",
    }

    async def mock_api_request(method, url, data, headers):
        expected_data = {
            "surname": "Doe",
            "payment_details": "encrypted_account info",
            "verified": True,
            "profile_id": 1,
        }
        assert data == expected_data
        return 200, None

    with patch.object(profile_service, "_api_request", side_effect=mock_api_request):
        result = await profile_service.edit_coach_profile(profile_id=1, data=data)
        assert result is True


@pytest.mark.asyncio
async def test_edit_coach_profile_failure(profile_service):
    data = {"surname": "Doe"}

    async def mock_api_request(method, url, data, headers):
        return 400, None

    with patch.object(profile_service, "_api_request", side_effect=mock_api_request):
        result = await profile_service.edit_coach_profile(profile_id=1, data=data)
        assert result is False


@pytest.mark.asyncio
async def test_get_coach_profile_success(profile_service):
    async def mock_api_request(method, url, headers):
        return 200, {"id": 1, "name": "Coach Name"}

    with patch.object(profile_service, "_api_request", side_effect=mock_api_request):
        response_data = await profile_service.get_coach_profile(profile_id=1)
        assert response_data == {"id": 1, "name": "Coach Name"}


@pytest.mark.asyncio
async def test_get_coach_profile_failure(profile_service):
    async def mock_api_request(method, url, headers):
        return 404, None

    with patch.object(profile_service, "_api_request", side_effect=mock_api_request):
        with pytest.raises(ValueError) as exc_info:
            await profile_service.get_coach_profile(profile_id=1)
        assert "Failed to get coach profile for profile_id 1" in str(exc_info.value)


@pytest.mark.asyncio
async def test_reset_telegram_id_success(profile_service):
    async def mock_api_request(method, url, data, headers):
        expected_data = {"telegram_id": 123456}
        assert data == expected_data
        return 200, None

    with patch.object(profile_service, "_api_request", side_effect=mock_api_request):
        result = await profile_service.reset_telegram_id(profile_id=1, telegram_id=123456)
        assert result is True


@pytest.mark.asyncio
async def test_reset_telegram_id_failure(profile_service):
    async def mock_api_request(method, url, data, headers):
        return 400, None

    with patch.object(profile_service, "_api_request", side_effect=mock_api_request):
        result = await profile_service.reset_telegram_id(profile_id=1, telegram_id=123456)
        assert result is False
