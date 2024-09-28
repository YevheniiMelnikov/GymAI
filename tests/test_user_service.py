from unittest.mock import patch, MagicMock

import pytest

from common.exceptions import UsernameUnavailable, EmailUnavailable


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status_code, response_json, expected_result, expected_exception",
    [
        (201, {}, True, None),
        (400, {"error": "Username already exists"}, False, UsernameUnavailable),
        (400, {"error": "Email already in use"}, False, EmailUnavailable),
        (500, {}, False, None),
    ],
)
async def test_sign_up(user_service, status_code, response_json, expected_result, expected_exception):
    async def mock_api_request(method, url, data, headers):
        return status_code, response_json

    with patch.object(user_service, "_api_request", side_effect=mock_api_request):
        if expected_exception:
            with pytest.raises(expected_exception):
                await user_service.sign_up(username="testuser", email="test@example.com", password="password")
        else:
            result = await user_service.sign_up(username="testuser", email="test@example.com", password="password")
            assert result == expected_result


@pytest.mark.asyncio
async def test_get_user_token_success(user_service):
    async def mock_api_request(method, url, data, headers):
        return 200, {"auth_token": "test_token"}

    with patch.object(user_service, "_api_request", side_effect=mock_api_request):
        token = await user_service.get_user_token(profile_id=1)
        assert token == "test_token"


@pytest.mark.asyncio
async def test_get_user_token_failure(user_service):
    async def mock_api_request(method, url, data, headers):
        return 400, {}

    with patch.object(user_service, "_api_request", side_effect=mock_api_request):
        token = await user_service.get_user_token(profile_id=1)
        assert token is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status_code, response_json, expected_token",
    [
        (200, {"auth_token": "test_token"}, "test_token"),
        (400, {}, None),
    ],
)
async def test_log_in(user_service, status_code, response_json, expected_token):
    async def mock_api_request(method, url, data, headers):
        return status_code, response_json

    with patch.object(user_service, "_api_request", side_effect=mock_api_request):
        token = await user_service.log_in(username="testuser", password="password")
        assert token == expected_token


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status_code, expected_result",
    [
        (204, True),
        (400, False),
    ],
)
async def test_log_out(user_service, status_code, expected_result):
    async def mock_api_request(method, url, data=None, headers=None):
        return status_code, {}

    profile = MagicMock()
    profile.id = 1
    with patch.object(user_service, "_api_request", side_effect=mock_api_request):
        result = await user_service.log_out(profile=profile, auth_token="test_token")
        assert result == expected_result


@pytest.mark.asyncio
async def test_get_user_data_success(user_service):
    async def mock_api_request(method, url, data=None, headers=None):
        return 200, {"username": "testuser", "email": "test@example.com"}

    with patch.object(user_service, "_api_request", side_effect=mock_api_request):
        data = await user_service.get_user_data(token="test_token")
        assert data == {"username": "testuser", "email": "test@example.com"}


@pytest.mark.asyncio
async def test_get_user_data_failure(user_service):
    async def mock_api_request(method, url, data=None, headers=None):
        return 401, {}

    with patch.object(user_service, "_api_request", side_effect=mock_api_request):
        data = await user_service.get_user_data(token="test_token")
        assert data is None


@pytest.mark.asyncio
async def test_get_user_email_success(user_service):
    async def mock_api_request(method, url, data=None, headers=None):
        return 200, {"user": {"email": "test@example.com"}}

    with patch.object(user_service, "_api_request", side_effect=mock_api_request):
        email = await user_service.get_user_email(profile_id=1)
        assert email == "test@example.com"


@pytest.mark.asyncio
async def test_get_user_email_failure(user_service):
    async def mock_api_request(method, url, data=None, headers=None):
        return 404, {}

    with patch.object(user_service, "_api_request", side_effect=mock_api_request):
        email = await user_service.get_user_email(profile_id=1)
        assert email is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status_code, expected_result",
    [
        (204, True),
        (400, False),
    ],
)
async def test_reset_password(user_service, status_code, expected_result):
    async def mock_api_request(method, url, data, headers):
        return status_code, {}

    with patch.object(user_service, "_api_request", side_effect=mock_api_request):
        result = await user_service.reset_password(email="test@example.com", token="test_token")
        assert result == expected_result
