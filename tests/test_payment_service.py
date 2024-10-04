from unittest.mock import patch
from urllib.parse import urlencode

import pytest

from tests.conftest import MockLiqPay


@pytest.mark.asyncio
async def test_get_payment_link(payment_service):
    action = "pay"
    amount = "100"
    order_id = "order123"
    payment_type = "program"
    client_email = "client@example.com"
    profile_id = 1

    link = await payment_service.get_payment_link(action, amount, order_id, payment_type, client_email, profile_id)
    expected_params = {"data": "mocked_data", "signature": "mocked_signature"}
    expected_query = urlencode(expected_params)
    expected_url = f"http://checkout.test/?{expected_query}"

    assert link == expected_url


@pytest.mark.asyncio
async def test_unsubscribe_success(payment_service):
    order_id = "order123"
    result = await payment_service.unsubscribe(order_id)
    assert result is True


@pytest.mark.asyncio
async def test_unsubscribe_failure(payment_service):
    original_api = MockLiqPay.api

    def mock_api(self, path, params):
        return {"status": "error"}

    MockLiqPay.api = mock_api

    order_id = "order123"
    result = await payment_service.unsubscribe(order_id)
    assert result is False

    MockLiqPay.api = original_api


@pytest.mark.asyncio
async def test_create_payment_success(payment_service):
    profile_id = 1
    payment_option = "subscription"
    order_id = "order123"
    amount = 100

    async def mock_api_request(method, url, data, headers):
        assert method == "post"
        assert url == "http://testserver/api/v1/payments/create/"
        assert data == {
            "profile": profile_id,
            "handled": False,
            "order_id": order_id,
            "payment_type": payment_option,
            "amount": amount,
            "status": "pending",
        }
        return 201, {}

    with patch.object(payment_service, "_api_request", side_effect=mock_api_request):
        result = await payment_service.create_payment(profile_id, payment_option, order_id, amount)
        assert result is True


@pytest.mark.asyncio
async def test_create_payment_failure(payment_service):
    async def mock_api_request(method, url, data, headers):
        return 400, {}

    with patch.object(payment_service, "_api_request", side_effect=mock_api_request):
        result = await payment_service.create_payment(1, "subscription", "order123", 100)
        assert result is False


@pytest.mark.asyncio
async def test_update_payment_success(payment_service):
    payment_id = 1
    data = {"status": "success"}

    async def mock_api_request(method, url, data, headers):
        assert method == "put"
        assert url == f"http://testserver/api/v1/payments/{payment_id}/"
        return 200, {}

    with patch.object(payment_service, "_api_request", side_effect=mock_api_request):
        result = await payment_service.update_payment(payment_id, data)
        assert result is True


@pytest.mark.asyncio
async def test_update_payment_failure(payment_service):
    async def mock_api_request(method, url, data, headers):
        return 400, {}

    with patch.object(payment_service, "_api_request", side_effect=mock_api_request):
        result = await payment_service.update_payment(1, {"status": "success"})
        assert result is False


@pytest.mark.asyncio
async def test_get_unhandled_payments(payment_service):
    async def mock_api_request(method, url, headers):
        return 200, {
            "results": [
                {
                    "id": 1,
                    "profile": 1,
                    "payment_type": "subscription",
                    "order_id": "order1",
                    "amount": 100,
                    "status": "pending",
                    "created_at": 1633036800.0,
                    "updated_at": 1633036800.0,
                    "handled": False,
                    "error": None,
                },
            ]
        }

    with patch.object(payment_service, "_api_request", side_effect=mock_api_request):
        payments = await payment_service.get_unhandled_payments()
        assert len(payments) == 1
        assert all(not p.handled for p in payments)


@pytest.mark.asyncio
async def test_get_unclosed_payments(payment_service):
    SUCCESS_PAYMENT_STATUS = "success"

    async def mock_api_request(method, url, headers):
        return 200, {
            "results": [
                {
                    "id": 1,
                    "profile": 1,
                    "payment_type": "subscription",
                    "order_id": "order1",
                    "amount": 100,
                    "status": SUCCESS_PAYMENT_STATUS,
                    "created_at": 1633036800.0,
                    "updated_at": 1633036800.0,
                    "handled": False,
                    "error": None,
                },
            ]
        }

    with patch.object(payment_service, "_api_request", side_effect=mock_api_request):
        payments = await payment_service.get_unclosed_payments()
        assert len(payments) == 1
        assert all(p.status == SUCCESS_PAYMENT_STATUS for p in payments)


@pytest.mark.asyncio
async def test_get_expired_subscriptions(payment_service):
    expired_before = "2023-09-28"

    async def mock_api_request(method, url, headers):
        assert "enabled=True" in url
        assert f"payment_date__lte={expired_before}" in url
        return 200, [{"id": 1}, {"id": 2}]

    with patch.object(payment_service, "_api_request", side_effect=mock_api_request):
        subscriptions = await payment_service.get_expired_subscriptions(expired_before)
        assert len(subscriptions) == 2


@pytest.mark.asyncio
async def test_get_last_subscription_payment(payment_service):
    profile_id = 1

    async def mock_api_request(method, url, data, headers):
        assert data == {"profile": profile_id, "payment_type": "subscription"}
        return 200, {
            "results": [
                {"order_id": "order1", "created_at": "2023-09-27T12:00:00Z"},
                {"order_id": "order2", "created_at": "2023-09-28T12:00:00Z"},
            ]
        }

    with patch.object(payment_service, "_api_request", side_effect=mock_api_request):
        order_id = await payment_service.get_last_subscription_payment(profile_id)
        assert order_id == "order2"


@pytest.mark.asyncio
async def test_get_last_subscription_payment_no_payments(payment_service):
    async def mock_api_request(method, url, data, headers):
        return 200, {"results": []}

    with patch.object(payment_service, "_api_request", side_effect=mock_api_request):
        order_id = await payment_service.get_last_subscription_payment(1)
        assert order_id is None
