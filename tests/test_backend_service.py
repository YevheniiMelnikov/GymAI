from unittest.mock import patch

import httpx
import pytest
from httpx import Response

from common.exceptions import UserServiceError


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status_code, expected_result",
    [
        (200, True),
        (400, False),
    ],
)
async def test_send_feedback(backend_service, status_code, expected_result):
    async def mock_request(method, url, json, headers):
        assert method == "post"
        assert url == "http://testserver/api/v1/send-feedback/"
        assert json == {"email": "test@example.com", "username": "testuser", "feedback": "Great bot!"}
        assert headers == {"Authorization": "Api-Key test_api_key"}
        return Response(status_code, json={"message": "response"})

    with patch.object(backend_service.client, "request", side_effect=mock_request):
        result = await backend_service.send_feedback("test@example.com", "testuser", "Great bot!")
        assert result == expected_result


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status_code, expected_result",
    [
        (200, True),
        (400, False),
    ],
)
async def test_send_welcome_email(backend_service, status_code, expected_result):
    async def mock_request(method, url, json, headers):
        assert method == "post"
        assert url == "http://testserver/api/v1/send-welcome-email/"
        assert json == {"email": "test@example.com", "username": "testuser"}
        assert headers == {"Authorization": "Api-Key test_api_key"}
        return Response(status_code, json={"message": "response"})

    with patch.object(backend_service.client, "request", side_effect=mock_request):
        result = await backend_service.send_welcome_email("test@example.com", "testuser")
        assert result == expected_result


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response_kwargs, expected_status_code, expected_data",
    [
        ({"status_code": 200, "json": {"data": "value"}}, 200, {"data": "value"}),
        ({"status_code": 200, "content": "Not a JSON"}, 200, None),
        ({"status_code": 404, "json": {"error": "Not found"}}, 404, {"error": "Not found"}),
        ({"status_code": 500, "content": "Internal Server Error"}, 500, {"error": "Internal Server Error"}),
    ],
)
async def test_api_request(backend_service, response_kwargs, expected_status_code, expected_data):
    async def mock_request(method, url, json, headers):
        return Response(**response_kwargs)

    with patch.object(backend_service.client, "request", side_effect=mock_request):
        status_code, data = await backend_service._api_request("get", "http://example.com")
        assert status_code == expected_status_code
        assert data == expected_data


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exception, expected_message",
    [
        (httpx.HTTPError("Connection error"), "HTTP request failed: Connection error"),
        (Exception("Unexpected error"), "Unexpected error occurred: Unexpected error"),
    ],
)
async def test_api_request_exceptions(backend_service, exception, expected_message):
    async def mock_request(method, url, json, headers):
        raise exception

    with patch.object(backend_service.client, "request", side_effect=mock_request):
        with pytest.raises(UserServiceError) as exc_info:
            await backend_service._api_request("get", "http://example.com")
        assert expected_message in str(exc_info.value)
