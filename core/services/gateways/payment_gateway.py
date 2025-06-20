from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import urlencode, urljoin

from liqpay import LiqPay
from loguru import logger

from config.env_settings import settings


class PaymentGateway(ABC):
    """Abstract payment gateway interface."""

    @abstractmethod
    def build_payment_params(
        self,
        action: str,
        amount: Decimal,
        order_id: str,
        payment_type: str,
        client_id: int,
        emails: list[str],
    ) -> dict:
        """Construct gateway specific payment parameters."""

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

    @abstractmethod
    async def unsubscribe(self, order_id: str) -> bool:
        """Cancel subscription by order id."""


class LiqPayGateway(PaymentGateway):
    """Implementation of :class:`PaymentGateway` for LiqPay."""

    def __init__(self, public_key: str, private_key: str) -> None:
        self.client = LiqPay(public_key, private_key)

    def build_payment_params(
        self,
        action: str,
        amount: Decimal,
        order_id: str,
        payment_type: str,
        client_id: int,
        emails: list[str],
    ) -> dict:
        params = {
            "action": action,
            "amount": str(amount.quantize(Decimal("0.01"), ROUND_HALF_UP)),
            "currency": "UAH",
            "description": f"{payment_type} payment from client {client_id}",
            "order_id": order_id,
            "version": "3",
            "server_url": settings.PAYMENT_CALLBACK_URL,
            "result_url": settings.BOT_LINK,
            "rro_info": {"delivery_emails": emails},
        }

        return params

    async def get_payment_link(
        self,
        action: str,
        amount: Decimal,
        order_id: str,
        payment_type: str,
        client_id: int,
    ) -> str:
        params = self.build_payment_params(
            action=action,
            amount=amount,
            order_id=order_id,
            payment_type=payment_type,
            client_id=client_id,
            emails=[settings.EMAIL],
        )
        data = self.client.cnb_data(params)
        signature = self.client.cnb_signature(params)
        query_string = urlencode({"data": data, "signature": signature})
        return urljoin(settings.CHECKOUT_URL, f"?{query_string}")

    async def unsubscribe(self, order_id: str) -> bool:
        logger.info("Unsubscribe is not supported in credits mode")
        return True
