import datetime
from dataclasses import dataclass
from urllib.parse import urljoin, urlencode
from typing import Any

import loguru
from liqpay import LiqPay

from services.api_service import APIClient
from core.models import Payment
from common.settings import settings

logger = loguru.logger


@dataclass
class PaymentConfig:
    checkout_url: str
    public_key: str
    private_key: str
    callback_url: str
    bot_link: str
    email_host: str


class PaymentClient(APIClient):
    API_BASE_PATH = "api/v1/payments/"
    SUBSCRIPTIONS_PATH = "api/v1/subscriptions/"

    def __init__(self, config: PaymentConfig):
        super().__init__()
        self.config = config
        self.payment_client = LiqPay(self.config.public_key, self.config.private_key)

    @staticmethod
    def from_env() -> "PaymentClient":
        return PaymentClient(payment_config)

    def _build_payment_params(
        self, action: str, amount: str, order_id: str, payment_type: str, profile_id: int, emails: list[str]
    ) -> dict:
        params = {
            "action": action,
            "amount": amount,
            "currency": "UAH",
            "description": f"{payment_type} payment from profile {profile_id}",
            "order_id": order_id,
            "version": "3",
            "server_url": self.config.callback_url,
            "result_url": self.config.bot_link,
            "rro_info": {"delivery_emails": emails},
        }

        if action == "subscribe":
            params.update(
                {
                    "subscribe_date_start": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "subscribe_periodicity": "month",
                }
            )
        return params

    async def get_payment_link(
        self, action: str, amount: str, order_id: str, payment_type: str, client_email: str, profile_id: int
    ) -> str:
        emails = [email for email in [client_email, self.config.email_host] if email]
        params = self._build_payment_params(
            action=action,
            amount=amount,
            order_id=order_id,
            payment_type=payment_type,
            profile_id=profile_id,
            emails=emails,
        )

        data = self.payment_client.cnb_data(params)
        signature = self.payment_client.cnb_signature(params)
        query_string = urlencode({"data": data, "signature": signature})
        return urljoin(self.config.checkout_url, f"?{query_string}")

    async def unsubscribe(self, order_id: str) -> bool:
        try:
            response = self.payment_client.api(
                "request",
                {
                    "action": "unsubscribe",
                    "version": "3",
                    "order_id": order_id,
                },
            )

            if response.get("status") == "unsubscribed":
                logger.info(f"Successfully unsubscribed order {order_id}")
                return True

            logger.error(f"Unsubscribe failed for order {order_id}: {response}")
            return False

        except Exception as e:
            logger.error(f"Unsubscribe error for {order_id}: {e}")
            return False

    async def _handle_payment_api_request(
        self,
        method: str,
        endpoint: str,
        data: dict | None = None,
    ) -> tuple[int, dict[str, Any]]:
        url = urljoin(self.api_url, endpoint)
        try:
            status_code, response = await self._api_request(
                method=method, url=url, data=data, headers={"Authorization": f"Api-Key {self.api_key}"}
            )
            return status_code, response
        except Exception as e:
            logger.error(f"API {method.upper()} request to {endpoint} failed with error: {e}")
            return 500, {}

    async def create_payment(self, profile_id: int, payment_option: str, order_id: str, amount: int) -> bool:
        status_code, _ = await self._handle_payment_api_request(
            method="post",
            endpoint=urljoin(self.API_BASE_PATH, "create/"),
            data={
                "profile": profile_id,
                "handled": False,
                "order_id": order_id,
                "payment_type": payment_option,
                "amount": amount,
                "status": "pending",
            },
        )
        return status_code == 201

    async def update_payment(self, payment_id: int, data: dict) -> bool:
        status_code, _ = await self._handle_payment_api_request(
            method="put", endpoint=f"{self.API_BASE_PATH}{payment_id}/", data=data
        )
        return status_code == 200

    async def _get_filtered_payments(self, filter_func) -> list[Payment]:
        status_code, response = await self._handle_payment_api_request(method="get", endpoint=self.API_BASE_PATH)

        if status_code != 200:
            return []

        payments = response.get("results", [])
        return [Payment.from_dict(p) for p in payments if filter_func(p)]

    async def get_unhandled_payments(self) -> list[Payment]:
        return await self._get_filtered_payments(lambda p: not p.get("handled"))

    async def get_unclosed_payments(self) -> list[Payment]:
        return await self._get_filtered_payments(lambda p: p.get("status") == settings.SUCCESS_PAYMENT_STATUS)

    async def get_expired_subscriptions(self, expired_before: str) -> list[dict]:
        status_code, response = await self._handle_payment_api_request(
            method="get",
            endpoint=self.SUBSCRIPTIONS_PATH,
            data={"enabled": "True", "payment_date__lte": expired_before},
        )

        if status_code != 200:
            logger.error(f"Failed to get expired subscriptions: HTTP {status_code}")
            return []

        return response.get("results", [])

    async def get_last_subscription_payment(self, profile_id: int) -> str | None:
        status_code, response = await self._handle_payment_api_request(
            method="get", endpoint=self.API_BASE_PATH, data={"profile": profile_id, "payment_type": "subscription"}
        )

        if status_code != 200 or not response.get("results"):
            return None

        payments = response["results"]
        last_payment = max(payments, key=lambda x: x["created_at"])
        return last_payment["order_id"]


payment_config = PaymentConfig(
    checkout_url=settings.CHECKOUT_URL,
    public_key=settings.PAYMENT_PUB_KEY,
    private_key=settings.PAYMENT_PRIVATE_KEY,
    callback_url=settings.PAYMENT_CALLBACK_URL,
    bot_link=settings.BOT_LINK,
    email_host=settings.EMAIL_HOST_USER,
)
payment_service = PaymentClient.from_env()
