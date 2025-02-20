import os
from unittest.mock import patch

os.environ["CRYPTO_KEY"] = "Wji_cPHkdgZnPwmL-jiuB-uhkDCKW3yRTUqHfOLWc2Y="

from services.payment_service import PaymentClient
from services.workout_service import WorkoutClient


import pytest

from services.api_service import APIClient
from services.user_service import UserClient


class MockLiqPay:
    def __init__(self, public_key, private_key):
        self.public_key = public_key
        self.private_key = private_key

    def cnb_data(self, params):
        return "mocked_data"

    def cnb_signature(self, params):
        return "mocked_signature"

    def api(self, path, params):
        if params.get("action") == "p2pcredit":
            return {"status": "success"}
        elif params.get("action") == "unsubscribe":
            return {"status": "unsubscribed"}
        else:
            return {"status": "error"}


class MockEncrypter:
    def encrypt(self, data):
        return f"encrypted_{data}"


with patch("schedulers.encrypter.Encrypter", new=MockEncrypter):
    from services.profile_service import ProfileClient


@pytest.fixture
def api_service(monkeypatch) -> APIClient:
    monkeypatch.setenv("api_url", "http://testserver/")
    monkeypatch.setenv("API_KEY", "test_api_key")
    return APIClient()


@pytest.fixture
def user_service(monkeypatch) -> UserClient:
    monkeypatch.setenv("api_url", "http://testserver/")
    monkeypatch.setenv("API_KEY", "test_api_key")
    return UserClient()


@pytest.fixture
def profile_service(monkeypatch) -> ProfileClient:
    monkeypatch.setenv("api_url", "http://testserver/")
    monkeypatch.setenv("API_KEY", "test_api_key")
    encrypter = MockEncrypter()
    return ProfileClient(encrypter=encrypter)  # type: ignore


@pytest.fixture
def workout_service(monkeypatch) -> WorkoutClient:
    monkeypatch.setenv("api_url", "http://testserver/")
    monkeypatch.setenv("API_KEY", "test_api_key")
    return WorkoutClient()


@pytest.fixture
def payment_service(monkeypatch) -> PaymentClient:
    monkeypatch.setenv("api_url", "http://testserver/")
    monkeypatch.setenv("API_KEY", "test_api_key")
    monkeypatch.setenv("CHECKOUT_URL", "http://checkout.test/")
    monkeypatch.setenv("PAYMENT_PUB_KEY", "test_pub_key")
    monkeypatch.setenv("PAYMENT_PRIVATE_KEY", "test_private_key")
    monkeypatch.setenv("EMAIL_HOST_USER", "host@example.com")
    monkeypatch.setenv("PAYMENT_CALLBACK_URL", "http://callback.test/")
    monkeypatch.setenv("BOT_LINK", "http://bot.test/")

    with patch("services.payment_service.LiqPay", new=MockLiqPay):
        return PaymentClient()
