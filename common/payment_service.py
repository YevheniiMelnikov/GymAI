import asyncio
import base64
import datetime
import hashlib
import hmac
import os
from datetime import datetime
from typing import Any

import httpx
import loguru
from aiogram.fsm.context import FSMContext

from common.models import Profile
from common.settings import SUBSCRIPTION_PRICE, PROGRAM_PRICE
from common.user_service import user_service, UserService

logger = loguru.logger


class PaymentService:
    def __init__(self, user_service: UserService):
        self.user_service = user_service
        self.payee_id = os.environ.get("PORTMONE_PAYEE_ID")
        self.login = os.environ.get("PORTMONE_LOGIN")
        self.password = os.environ.get("PORTMONE_PASSWORD")
        self.gateway_url = os.environ.get("PAYMENT_GATEWAY_URL")
        self.key = os.environ.get("PORTMONE_KEY")
        self.client = httpx.AsyncClient()

    async def close(self) -> None:
        await self.client.aclose()

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

    async def process_subscription_payment(self, data: dict[str, Any], profile: Profile) -> bool:
        try:
            subscription_id = await self.user_service.create_subscription(
                profile.id, SUBSCRIPTION_PRICE, data.get("workout_days")
            )
            subscription_data = {
                "id": subscription_id,
                "payment_date": datetime.today().isoformat(),
                "enabled": True,
                "price": SUBSCRIPTION_PRICE,
                "workout_days": data.get("workout_days"),
            }
            self.user_service.storage.save_subscription(str(profile.id), subscription_data)
            self.user_service.storage.set_payment_status(str(profile.id), True, "subscription")
            return True
        except Exception as e:
            logger.error(f"Subscription not created for profile_id {profile.id}: {e}")
            return False

    async def process_program_payment(self, profile: Profile) -> bool:
        try:
            self.user_service.storage.set_payment_status(str(profile.id), True, "program")
            return True
        except Exception as e:
            logger.error(f"Program payment failed for profile_id {profile.id}: {e}")
            return False

    async def payment_status(self, order_id: str, amount: str) -> tuple[int, Any]:
        url = f"{self.gateway_url}status"
        signature = self.generate_signature(order_id, amount)
        data = {
            "payee_id": self.payee_id,
            "shop_order_number": order_id,
            "login": self.login,
            "password": self.password,
            "sign": signature,
        }

        response = await self.client.post(url, json=data)
        if response.status_code == 200:
            return response.status_code, response.json()
        else:
            return response.status_code, response.text

    async def process_webhook(self, data: dict, profile: Profile) -> bool:
        order_id = data.get("shopOrderNumber")
        try:
            data["status"] = "PAYED"  # TODO: REMOVE AFTER TESTING
            payment_status = data.get("status")
            if payment_status == "PAYED":
                if data.get("payment_options") == "subscription":
                    return await payment_service.process_subscription_payment(data, profile)
                return await payment_service.process_program_payment(profile)
            else:
                logger.warning(f"Payment for order {order_id} was not successful. Status: {payment_status}")
                return False
        except Exception as e:
            logger.error(f"Error processing webhook for order {order_id}: {e}")
            return False

    async def check_payments_periodically(self):
        while True:
            try:
                # Step 1: Fetch pending payments (mocked for now)
                pending_payments = self.get_pending_payments()

                for payment in pending_payments:
                    order_id = payment["order_id"]
                    status_code, payment_status = await self.payment_status(order_id)

                    if status_code == 200 and payment_status.get("RESULT") == "APPROVED":
                        # Update status in PostgreSQL and Redis
                        profile_id = payment["profile_id"]
                        service_type = payment["service_type"]
                        await self.update_payment_status(profile_id, service_type, True)

                await asyncio.sleep(30)  # Wait for 30 seconds before checking again

            except Exception as e:
                logger.error(f"Error in periodic payment check: {e}")

    def get_pending_payments(self):
        # Mocked method: Fetch pending payments from a database or other source
        return [
            {"order_id": "order123", "profile_id": "profile1", "service_type": "subscription"},
            {"order_id": "order456", "profile_id": "profile2", "service_type": "program"},
        ]

    async def update_payment_status(self, profile_id: str, service_type: str, status: bool):
        self.user_service.storage.set_payment_status(profile_id, status, service_type)
        logger.info(f"Payment status for profile_id {profile_id} updated to {status}")


payment_service = PaymentService(user_service)
