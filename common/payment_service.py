import base64
import gzip
import json
import os
import uuid
import datetime

import httpx
import loguru

from common.settings import PROGRAM_PRICE, SUBSCRIPTION_PRICE

logger = loguru.logger


class PaymentService:
    def __init__(self):
        self.payee_id = os.environ.get("PORTMONE_PAYEE_ID")
        self.login = os.environ.get("PORTMONE_LOGIN")
        self.password = os.environ.get("PORTMONE_PASSWORD")
        self.gateway_url = os.environ.get("PAYMENT_GATEWAY_URL")
        self.key = os.environ.get("PORTMONE_KEY")
        self.client = httpx.AsyncClient()

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


payment_service = PaymentService()
