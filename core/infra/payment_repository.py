from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from urllib.parse import urljoin

import httpx
from loguru import logger
from pydantic import ValidationError

from core.enums import PaymentStatus
from core.schemas import Payment, Subscription
from core.services.internal.api_client import (
    APIClient,
    APIClientHTTPError,
    APIClientTransportError,
    APISettings,
)


class HTTPPaymentRepository(APIClient):
    API_BASE_PATH = "api/v1/payments/"
    SUBSCRIPTIONS_PATH = "api/v1/subscriptions/"

    def __init__(self, client: httpx.AsyncClient, settings: APISettings) -> None:
        super().__init__(client, settings)
        self.use_default_auth = False

    async def _handle_payment_api_request(
        self, method: str, endpoint: str, data: dict | None = None
    ) -> tuple[int, dict[str, Any]]:
        url = urljoin(self.api_url, endpoint)
        try:
            logger.debug(f"Sending {method.upper()} request to {url} with data: {data}")
            status_code, response = await self._api_request(
                method=method,
                url=url,
                data=data or {},
                headers={"Authorization": f"Api-Key {self.api_key}"},
            )
            return status_code, response if response is not None else {}
        except APIClientHTTPError as exc:
            logger.error(f"API {method.upper()} request to {endpoint} failed: {exc}")
            return (exc.status if exc.status else 500), {}
        except APIClientTransportError as exc:
            logger.error(f"API {method.upper()} transport failure to {endpoint}: {exc}")
            return 503, {}

    async def create_payment(self, profile_id: int, service_type: str, order_id: str, amount: Decimal) -> bool:
        status_code, _ = await self._handle_payment_api_request(
            method="post",
            endpoint=urljoin(self.API_BASE_PATH, "create/"),
            data={
                "profile": profile_id,
                "order_id": order_id,
                "payment_type": service_type,
                "amount": str(amount.quantize(Decimal("0.01"), ROUND_HALF_UP)),
                "status": PaymentStatus.PENDING,
                "processed": False,
            },
        )
        return status_code == 201

    async def update_payment(self, payment_id: int, data: dict) -> bool:
        status_code, _ = await self._handle_payment_api_request(
            method="put", endpoint=f"{self.API_BASE_PATH}{payment_id}/", data=data
        )
        return status_code in {200, 204}

    async def get_expired_subscriptions(self, expired_before: str) -> list[Subscription]:
        status_code, response = await self._handle_payment_api_request(
            method="get",
            endpoint=self.SUBSCRIPTIONS_PATH,
            data={"enabled": "True", "payment_date__lte": expired_before},
        )
        if status_code != 200:
            logger.error(f"Failed to get expired subscriptions: HTTP {status_code}")
            return []
        results = response.get("results", [])
        return [Subscription.model_validate(item) for item in results]

    async def update_payment_status(self, order_id: str, status_: str, error: str = "") -> Payment | None:
        payment, payment_id = await self._get_payment_by_order_id(order_id)
        if payment_id is None or payment is None:
            logger.error(f"Payment {order_id} not found")
            return None
        try:
            new_status = PaymentStatus(status_)
        except Exception as exc:  # noqa: BLE001
            logger.error(f"Invalid payment status '{status_}' for order_id={order_id}: {exc}")
            return None

        if payment.status == new_status:
            if error and error != payment.error:
                ok = await self.update_payment(payment_id, {"error": error})
                if not ok:
                    logger.error(f"Failed to update payment error for {order_id}")
                    return None
                payment.error = error
            return payment

        ok = await self.update_payment(
            payment_id,
            {
                "status": new_status,
                "error": error,
                "processed": False,
            },
        )
        if not ok:
            logger.error(f"Failed to update payment {order_id}")
            return None

        logger.info(f"Payment {order_id} set to '{new_status}'")
        payment.status = new_status
        payment.error = error
        payment.processed = False
        return payment

    async def _get_payment_by_order_id(self, order_id: str) -> tuple[Payment | None, int | None]:
        status_code, response = await self._handle_payment_api_request(
            method="get", endpoint=self.API_BASE_PATH, data={"order_id": order_id}
        )
        if status_code == 200 and response.get("results"):
            raw = response["results"][0]
            try:
                payment = Payment.model_validate(raw)
                return payment, raw["id"]
            except ValidationError as e:
                logger.error(f"Invalid payment data from API for order_id={order_id}: {e}")
        return None, None

    async def get_latest_payment(self, profile_id: int, payment_type: str) -> Payment | None:
        status_code, response = await self._handle_payment_api_request(
            method="get",
            endpoint=self.API_BASE_PATH,
            data={
                "profile": profile_id,
                "payment_type": payment_type,
                "ordering": "-created_at",
                "limit": 1,
            },
        )
        if status_code != 200 or not response.get("results"):
            return None
        try:
            return Payment.model_validate(response["results"][0])
        except ValidationError as e:
            logger.error(f"Invalid payment data for profile_id={profile_id}: {e}")
            return None
