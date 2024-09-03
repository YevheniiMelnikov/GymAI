import hashlib
import hmac
import os
from datetime import datetime
from typing import Any

import httpx
import loguru

from common.settings import PROGRAM_PRICE

logger = loguru.logger


class PaymentService:
    def __init__(self):
        self.payee_id = os.environ.get("PORTMONE_PAYEE_ID")
        self.login = os.environ.get("PORTMONE_LOGIN")
        self.password = os.environ.get("PORTMONE_PASSWORD")
        self.gateway_url = os.environ.get("PAYMENT_GATEWAY_URL")
        self.key = os.environ.get("PORTMONE_KEY")
        self.client = httpx.AsyncClient()

    def generate_signature(self, shop_order_number: str, bill_amount: str) -> tuple[str, str]:
        dt = datetime.now().strftime("%Y%m%d%H%M%S")
        message = f"{self.payee_id}{dt}{shop_order_number}{bill_amount}"
        message += self.login
        signature = hmac.new(self.key.encode(), message.encode(), hashlib.sha256).hexdigest().upper()
        return signature, dt

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
            "id": "1",
        }

        response = await self.client.post(self.gateway_url, json=payload)
        if response.status_code == 200:
            response_data = response.json()
            return response_data.get("result").get("linkInvoice")
        else:
            logger.error(f"Failed to get program link. HTTP status: {response.status_code}, response: {response.text}")
            return None

    async def get_subscription_link(self, order_number: str) -> str | None:
        return "www.example.com"  # TODO: REPLACE WITH ACTUAL URL

    async def check_status(self, order_id: str) -> tuple[int, Any]:  # TODO: COMPARE WITH DOCS
        return 200, {"RESULT": "APPROVED"}
        # url = f"{self.gateway_url}status"
        # signature, dt = self.generate_signature(order_id, amount)
        # data = {
        #     "payee_id": self.payee_id,
        #     "shop_order_number": order_id,
        #     "login": self.login,
        #     "password": self.password,
        #     "sign": signature,
        #     "time": dt,
        # }
        #
        # response = await self.client.post(url, json=data)
        # if response.status_code == 200:
        #     return response.status_code, response.json()
        # else:
        #     return response.status_code, response.text


payment_service = PaymentService()
