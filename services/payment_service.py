import os
import datetime
from urllib.parse import urljoin, urlencode

import loguru
from liqpay import LiqPay

from common.decorators import singleton
from services.backend_service import BackendService
from common.models import Payment
from common.settings import SUCCESS_PAYMENT_STATUS

logger = loguru.logger


@singleton
class PaymentService(BackendService):
    def __init__(self):
        super().__init__()
        self.checkout_url = os.getenv("CHECKOUT_URL")
        self.payment_client = LiqPay(os.getenv("PAYMENT_PUB_KEY"), os.getenv("PAYMENT_PRIVATE_KEY"))

    async def get_payment_link(
        self, action: str, amount: str, order_id: str, description: str, client_email: str
    ) -> str:
        emails = [email for email in [client_email, os.getenv("EMAIL_HOST_USER")] if email]
        params = {
            "action": action,
            "amount": amount,
            "currency": "UAH",
            "description": description,
            "order_id": order_id,
            "version": "3",
            "server_url": os.getenv("PAYMENT_CALLBACK_URL"),
            "result_url": os.getenv("BOT_LINK"),
            "rro_info": {
                "delivery_emails": emails,
            },
        }

        if action == "subscribe":
            params["subscribe_date_start"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            params["subscribe_periodicity"] = "month"

        data = self.payment_client.cnb_data(params)
        signature = self.payment_client.cnb_signature(params)
        query_string = urlencode({"data": data, "signature": signature})
        return urljoin(self.checkout_url, f"?{query_string}")

    async def unsubscribe(self, order_id: str) -> bool:
        try:
            params = {
                "action": "unsubscribe",
                "version": "3",
                "order_id": order_id,
            }

            response = self.payment_client.api("request", params)

            if response.get("status") == "unsubscribed":
                logger.info(f"Successfully unsubscribed for order {order_id}")
                return True
            else:
                logger.error(f"Unsubscribe failed for order {order_id}. Response: {response}")
                return False

        except Exception as e:
            logger.error(f"Error during unsubscribe: {e}")
            return False

    async def create_payment(self, profile_id: int, payment_option: str, order_id: str, amount: int) -> bool:
        url = urljoin(self.backend_url, "api/v1/payments/create/")
        data = {
            "profile": profile_id,
            "handled": False,
            "order_id": order_id,
            "payment_type": payment_option,
            "amount": amount,
            "status": "PENDING",
        }
        status_code, response = await self._api_request(
            "post", url, data, headers={"Authorization": f"Api-Key {self.api_key}"}
        )
        return status_code == 201

    async def get_payment_status(self, order_id: str) -> str | None:
        url = urljoin(self.backend_url, f"api/v1/payments/?order_id={order_id}")
        status_code, payment_data = await self._api_request(
            "get", url, headers={"Authorization": f"Api-Key {self.api_key}"}
        )

        if status_code == 200 and payment_data.get("results"):
            payment = payment_data["results"][0]
            return payment.get("status", "PENDING")
        else:
            logger.error(f"Payment {order_id} not found. HTTP status: {status_code}")
            return None

    async def update_payment(self, payment_id: int, data: dict) -> bool:
        url = urljoin(self.backend_url, f"api/v1/payments/{payment_id}/")
        status_code, _ = await self._api_request("put", url, data, headers={"Authorization": f"Api-Key {self.api_key}"})
        return status_code == 200

    async def get_unhandled_payments(self) -> list[Payment]:
        url = urljoin(self.backend_url, "api/v1/payments/")
        status_code, payments_data = await self._api_request(
            "get", url, headers={"Authorization": f"Api-Key {self.api_key}"}
        )
        if status_code == 200:
            payments_list = payments_data.get("results", [])
            return [Payment.from_dict(payment) for payment in payments_list if not payment.get("handled")]
        return []

    async def get_unclosed_payments(self) -> list[Payment]:
        url = urljoin(self.backend_url, "api/v1/payments/")
        status_code, payments_data = await self._api_request(
            "get", url, headers={"Authorization": f"Api-Key {self.api_key}"}
        )
        if status_code == 200:
            payments_list = payments_data.get("results", [])
            return [
                Payment.from_dict(payment)
                for payment in payments_list
                if payment.get("status") == SUCCESS_PAYMENT_STATUS
            ]
        return []

    async def get_expired_subscriptions(self, expired_before: str) -> list[dict]:
        base_path = "api/v1/subscriptions/"
        query_params = {"enabled": "True", "payment_date__lte": expired_before}
        url = urljoin(self.backend_url, base_path) + "?" + urlencode(query_params)
        status_code, subscriptions = await self._api_request(
            "get", url, headers={"Authorization": f"Api-Key {self.api_key}"}
        )

        if status_code == 200:
            return subscriptions
        logger.error("Failed to retrieve expired subscriptions. HTTP status: {}".format(status_code))
        return []

    async def get_last_subscription_payment(self, profile_id: int) -> str | None:
        url = urljoin(self.backend_url, "api/v1/payments/")
        data = {"profile": profile_id, "payment_type": "subscription"}

        status_code, payments_data = await self._api_request(
            "get", url, data=data, headers={"Authorization": f"Api-Key {self.api_key}"}
        )

        if status_code == 200:
            payments = payments_data.get("results", [])
            if payments:
                last_payment = sorted(payments, key=lambda x: x["created_at"], reverse=True)[0]
                return last_payment["order_id"]

        return None


payment_service = PaymentService()
