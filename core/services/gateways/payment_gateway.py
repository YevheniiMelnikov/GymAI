from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import urlencode, urljoin

from liqpay import LiqPay

from config.env_settings import settings


class PaymentGateway(ABC):
    """Abstract payment gateway interface."""

    @abstractmethod
    async def get_payment_link(
        self,
        action: str,
        amount: Decimal,
        order_id: str,
        payment_type: str,
        client_id: int,
    ) -> str:
        """Return URL to perform the payment."""


class LiqPayGateway(PaymentGateway):
    """Implementation of :class:`PaymentGateway` for LiqPay."""

    def __init__(self, public_key: str, private_key: str) -> None:
        self.client = LiqPay(public_key, private_key)

    async def get_payment_link(
        self,
        action: str,
        amount: Decimal,
        order_id: str,
        payment_type: str,
        client_id: int,
    ) -> str:
        params = {
            "action": action,
            "amount": str(amount.quantize(Decimal("0.01"), ROUND_HALF_UP)),
            "currency": "UAH",
            "description": f"{payment_type} payment from client {client_id}",
            "order_id": order_id,
            "version": "3",
            "server_url": settings.PAYMENT_CALLBACK_URL,
            "result_url": settings.BOT_LINK,
            "rro_info": {"delivery_emails": [settings.EMAIL]},
        }
        data = self.client.cnb_data(params)
        signature = self.client.cnb_signature(params)
        query_string = urlencode({"data": data, "signature": signature})
        return urljoin(settings.CHECKOUT_URL, f"?{query_string}")
