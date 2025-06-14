import asyncio
from decimal import Decimal

import pytest

from core.services.gateways.payment_gateway import LiqPayGateway


class DummyLiqPay:
    def __init__(self, pub, priv):
        self.pub = pub
        self.priv = priv
        self.params = None

    def cnb_data(self, params):
        self.params = params
        return "data"

    def cnb_signature(self, params):
        assert params is self.params
        return "sig"


@pytest.fixture(autouse=True)
def patch_liqpay(monkeypatch):
    monkeypatch.setattr(
        "core.services.gateways.payment_gateway.LiqPay",
        DummyLiqPay,
    )


def test_build_payment_params_subscribe():
    gateway = LiqPayGateway("pub", "priv")
    params = gateway.build_payment_params(
        "subscribe",
        Decimal("10"),
        "order",
        "subscription",
        1,
        ["a@example.com"],
    )
    assert params["action"] == "subscribe"
    assert params["amount"] == "10.00"
    assert params["order_id"] == "order"
    assert params["rro_info"] == {"delivery_emails": ["a@example.com"]}
    assert "subscribe_date_start" in params


def test_get_payment_link(monkeypatch):
    gateway = LiqPayGateway("pub", "priv")
    url = asyncio.run(
        gateway.get_payment_link(
            "pay",
            Decimal("5"),
            "ord",
            "program",
            2,
        )
    )
    assert url.endswith("?data=data&signature=sig")
    assert gateway.client.params["order_id"] == "ord"
