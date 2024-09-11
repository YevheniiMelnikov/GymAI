import base64
import gzip
import json
import os
import uuid
import datetime

import loguru

from services.backend_service import BackendService
from common.models import Payment
from common.settings import PROGRAM_PRICE, SUBSCRIPTION_PRICE

logger = loguru.logger


class PaymentService(BackendService):
    def __init__(self):
        super().__init__()
        self.payee_id = os.environ.get("PORTMONE_PAYEE_ID")
        self.login = os.environ.get("PORTMONE_LOGIN")
        self.password = os.environ.get("PORTMONE_PASSWORD")
        self.gateway_url = os.environ.get("PAYMENT_GATEWAY_URL")
        self.key = os.environ.get("PORTMONE_KEY")

    async def get_program_link(self, order_number: str) -> str | None:
        payload = {
            "method": "getLinkInvoice",
            "params": {
                "data": {
                    "login": self.login,
                    "shopOrderNumber": order_number,
                    "password": self.password,
                    "payee_id": self.payee_id,
                    "amount": PROGRAM_PRICE,
                },
            },
            "id": str(uuid.uuid4()),
        }

        response = await self.client.post(self.gateway_url, json=payload)
        if response.status_code == 200:
            response_data = response.json()
            return response_data.get("result").get("linkInvoice")
        else:
            logger.error(f"Failed to get program link. HTTP status: {response.status_code}, response: {response.text}")
            return None

    async def get_subscription_link(self, email: str, order_number: str) -> str:
        today = datetime.date.today()
        current_day = today.day

        if current_day > 28:
            current_day = 1

        payload = {
            "v": "2",
            "payeeId": self.payee_id,
            "amount": SUBSCRIPTION_PRICE,
            "emailAddress": email,
            "billNumber": order_number,
            "successUrl": os.getenv("BOT_LINK"),
            "settings": {
                "period": "1",
                "payDate": str(current_day),
            },
        }

        encoded_payload = self.encode_payload(payload)
        subscription_link = f"{self.gateway_url}?i={encoded_payload}"
        return subscription_link

    @staticmethod
    def encode_payload(payload: dict) -> str:
        json_payload = json.dumps(payload)
        compressed_payload = gzip.compress(json_payload.encode("utf-8"))
        encoded_payload = base64.b64encode(compressed_payload).decode("utf-8")
        return encoded_payload

    async def create_payment(self, profile_id: int, payment_option: str, order_number: str, amount: int) -> bool:
        url = f"{self.backend_url}api/v1/payments/create/"
        data = {
            "profile": profile_id,
            "handled": False,
            "shop_order_number": order_number,
            "payment_type": payment_option,
            "amount": amount,
            "status": "PENDING",
        }
        status_code, response = await self._api_request(
            "post", url, data, headers={"Authorization": f"Api-Key {self.api_key}"}
        )
        return status_code == 201

    async def update_payment(self, payment_id: int, data: dict) -> bool:
        url = f"{self.backend_url}api/v1/payments/{payment_id}/"
        status_code, _ = await self._api_request("put", url, data, headers={"Authorization": f"Api-Key {self.api_key}"})
        return status_code == 200

    async def get_all_payments(self) -> list[Payment]:
        url = f"{self.backend_url}api/v1/payments/"
        status_code, payments_data = await self._api_request(
            "get", url, headers={"Authorization": f"Api-Key {self.api_key}"}
        )
        if status_code == 200:
            payments_list = payments_data.get("results", [])
            return [Payment.from_dict(payment) for payment in payments_list]
        return []

    async def get_expired_subscriptions(self, expired_before: str) -> list[dict]:
        url = f"{self.backend_url}api/v1/subscriptions/?enabled=True&payment_date__lte={expired_before}"
        status_code, subscriptions = await self._api_request(
            "get", url, headers={"Authorization": f"Api-Key {self.api_key}"}
        )

        if status_code == 200:
            return subscriptions
        logger.error(f"Failed to retrieve expired subscriptions. HTTP status: {status_code}")
        return []

    async def get_last_subscription_payment(self, profile_id: int) -> tuple[str, str] | None:
        url = f"{self.backend_url}api/v1/payments/"
        data = {"profile": profile_id, "payment_type": "subscription"}

        status_code, payments_data = await self._api_request(
            "get", url, data=data, headers={"Authorization": f"Api-Key {self.api_key}"}
        )

        if status_code == 200:
            payments = payments_data.get("results", [])
            if payments:
                last_payment = sorted(payments, key=lambda x: x["created_at"], reverse=True)[0]
                return last_payment["shop_order_number"], last_payment["shop_bill_id"]

        return None


payment_service = PaymentService()
