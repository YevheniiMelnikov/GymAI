import asyncio
import base64
import json
from decimal import Decimal
from typing import Any

import pytest

from core.services.external.payments.liqpay import LiqPayGateway, ParamValidationError


class DummyLiqPay:
    def __init__(self, pub, priv):
        self.pub = pub
        self.priv = priv
        self.params = None

    def cnb_data(self, params: dict[str, Any]) -> str:
        required_fields = {"version", "amount", "currency", "action", "order_id", "description"}
        for field in required_fields:
            if field not in params:
                raise ParamValidationError(f"Missing {field}")
        if params["currency"] not in {"UAH", "USD", "EUR"}:
            raise ParamValidationError("Invalid currency")
        if str(params["version"]) not in {"3"}:
            raise ParamValidationError("Invalid version")
        self.params = params
        return base64.b64encode(json.dumps(params, sort_keys=True).encode()).decode()

    def cnb_signature(self, params: dict[str, Any]) -> str:
        assert params is self.params
        return "sig"

    def decode_data_from_str(self, data: str, signature: str | None = None) -> dict[str, Any]:
        decoded = json.loads(base64.b64decode(data.encode()).decode())
        if signature and signature != "sig":
            raise ParamValidationError("Invalid signature")
        return decoded


@pytest.fixture(autouse=True)
def patch_liqpay(monkeypatch):
    monkeypatch.setattr(
        "core.services.external.payments.payment_gateway.LiqPay",
        DummyLiqPay,
    )


def test_get_payment_link():
    gateway = LiqPayGateway("pub", "priv")
    url = asyncio.run(
        gateway.get_payment_link(
            "pay",
            Decimal("5"),
            "ord-123",
            "credits",
            1,
        )
    )
    assert url.startswith("https://")
    assert "data=" in url
    assert "signature=" in url


@pytest.mark.parametrize(
    "field",
    [
        "version",
        "amount",
        "currency",
        "action",
        "order_id",
        "description",
    ],
)
def test_required_fields_validation(field):
    gateway = LiqPayGateway("pub", "priv")
    valid = {
        "version": 3,
        "amount": "10",
        "currency": "UAH",
        "action": "pay",
        "order_id": "order-1",
        "description": "test",
    }
    del valid[field]
    with pytest.raises(ParamValidationError):
        gateway.client.cnb_data(valid)


def test_invalid_currency():
    gateway = LiqPayGateway("pub", "priv")
    params = {
        "version": 3,
        "amount": "10",
        "currency": "ZZZ",
        "action": "pay",
        "order_id": "order-1",
        "description": "Invalid",
    }
    with pytest.raises(ParamValidationError):
        gateway.client.cnb_data(params)


def test_invalid_version():
    gateway = LiqPayGateway("pub", "priv")
    params = {
        "version": 2,
        "amount": "10",
        "currency": "UAH",
        "action": "pay",
        "order_id": "order-1",
        "description": "Bad version",
    }
    with pytest.raises(ParamValidationError):
        gateway.client.cnb_data(params)


def test_valid_payment_params():
    gateway = LiqPayGateway("pub", "priv")
    params = {
        "version": 3,
        "amount": "15",
        "currency": "EUR",
        "action": "pay",
        "order_id": "test123",
        "description": "Testing",
    }
    encoded = gateway.client.cnb_data(params)
    decoded = gateway.client.decode_data_from_str(encoded, "sig")
    assert decoded == params
