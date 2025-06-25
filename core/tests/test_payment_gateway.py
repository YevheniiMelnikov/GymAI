import asyncio
from decimal import Decimal

import pytest

from core.services.outer.gateways.payment_gateway import LiqPayGateway


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


def test_get_payment_link(monkeypatch):
    gateway = LiqPayGateway("pub", "priv")
    url = asyncio.run(
        gateway.get_payment_link(
            "pay",
            Decimal("5"),
            "ord",
            "credits",
            2,
        )
    )
    assert url.endswith("?data=data&signature=sig")
    assert gateway.client.params["order_id"] == "ord"
