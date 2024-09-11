import base64
import binascii
import gzip
import hashlib
import hmac
import json
import os
import uuid
import datetime

import loguru
import requests

from services.backend_service import BackendService
from common.models import Payment
from common.settings import PROGRAM_PRICE, SUBSCRIPTION_PRICE, FIRST_NAME, LAST_NAME, ADDRESS

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

    def transfer_to_card(self, card_number: str, amount: str, order_number: str, recipient_info: dict) -> dict | None:
        dt = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        signature = self.generate_signature(dt, self.login, self.payee_id, order_number, amount, self.key)

        payload = {
            "paymentType": "a2c_1",
            "description": card_number,
            "billAmount": amount,
            "payeeId": self.payee_id,
            "shopOrderNumber": order_number,
            "dt": dt,
            "signature": signature,
            "mode": "1101",
            "sender": "1101",
            "identification": {
                "sender": {
                    "firstName": FIRST_NAME,
                    "lastName": LAST_NAME,
                    "account_number": os.getenv("ACCOUNT_NUMBER"),
                },
                "senderAddress": {
                    "countryCode": "UKR",
                    "city": "Kyiv",
                    "address": ADDRESS,
                },
                "recipient": {
                    "dstFirstName": recipient_info["dstFirstName"],
                    "dstLastName": recipient_info["dstLastName"],
                    "tax_id": recipient_info["tax_id"],
                },
            },
        }

        response = requests.post(self.gateway_url, json=payload)
        if response.status_code == 200:
            response_data = response.json()
            if response_data.get("result") == "PAYED":
                return response_data
            else:
                logger.error(f"Transfer failed. Response: {response_data}")
                return None
        else:
            logger.error(f"Failed to transfer money. HTTP status: {response.status_code}, response: {response.text}")
            return None

    @staticmethod
    def generate_signature(dt, login: str, payee_id: str, shop_order_number: str, bill_amount: str, key: str) -> str:
        str_to_sign = payee_id + dt + binascii.hexlify(shop_order_number.encode()).decode().upper() + bill_amount
        str_to_sign = str_to_sign.upper() + binascii.hexlify(login.encode()).decode().upper()
        return hmac.new(key.encode(), str_to_sign.encode(), hashlib.sha256).hexdigest().upper()

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
