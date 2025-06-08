import datetime
from collections.abc import Sequence
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from urllib.parse import urlencode, urljoin

from liqpay import LiqPay
from loguru import logger
from pydantic_core._pydantic_core import ValidationError

from config.env_settings import settings
from core.enums import PaymentStatus
from core.schemas import Payment, Subscription
from core.services.api_client import APIClient


class PaymentService(APIClient):
    API_BASE_PATH = "api/v1/payments/"
    SUBSCRIPTIONS_PATH = "api/v1/subscriptions/"
    payment_client = LiqPay(settings.PAYMENT_PUB_KEY, settings.PAYMENT_PRIVATE_KEY)

    @classmethod
    def _build_payment_params(
        cls,
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

        if action == "subscribe":
            params.update(
                {
                    "subscribe_date_start": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d %H:%M:%S"),
                    "subscribe_periodicity": "month",
                }
            )
        return params

    @classmethod
    async def get_payment_link(
        cls,
        action: str,
        amount: Decimal,
        order_id: str,
        payment_type: str,
        client_id: int,
    ) -> str:
        params = cls._build_payment_params(
            action=action,
            amount=amount,
            order_id=order_id,
            payment_type=payment_type,
            client_id=client_id,
            emails=[settings.EMAIL],
        )

        data = cls.payment_client.cnb_data(params)
        signature = cls.payment_client.cnb_signature(params)
        query_string = urlencode({"data": data, "signature": signature})
        return urljoin(settings.CHECKOUT_URL, f"?{query_string}")

    @classmethod
    async def unsubscribe(cls, order_id: str) -> bool:
        try:
            response = cls.payment_client.api(
                "request",
                {"action": "unsubscribe", "version": "3", "order_id": order_id},
            )
            if response.get("status") == "unsubscribed":
                logger.info(f"Successfully unsubscribed order {order_id}")
                return True
            logger.error(f"Unsubscribe failed for order {order_id}: {response}")
            return False
        except Exception as e:
            logger.error(f"Unsubscribe error for {order_id}: {e}")
            return False

    @classmethod
    async def _handle_payment_api_request(
        cls, method: str, endpoint: str, data: dict | None = None
    ) -> tuple[int, dict[str, Any]]:
        url = urljoin(cls.api_url, endpoint)
        try:
            logger.debug(f"Sending {method.upper()} request to {url} with data: {data}")
            status_code, response = await cls._api_request(
                method=method,
                url=url,
                data=data or {},
                headers={"Authorization": f"Api-Key {cls.api_key}"},
            )
            return status_code, response if response is not None else {}
        except Exception as e:
            logger.error(f"API {method.upper()} request to {endpoint} failed: {e}")
            return 500, {}

    @classmethod
    async def create_payment(cls, client_id: int, service_type: str, order_id: str, amount: Decimal) -> bool:
        status_code, _ = await cls._handle_payment_api_request(
            method="post",
            endpoint=urljoin(cls.API_BASE_PATH, "create/"),
            data={
                "client_profile": client_id,
                "order_id": order_id,
                "payment_type": service_type,
                "amount": str(amount.quantize(Decimal("0.01"), ROUND_HALF_UP)),
                "status": PaymentStatus.PENDING,
                "processed": False,
                "payout_handled": False,
            },
        )
        return status_code == 201

    @classmethod
    async def update_payment(cls, payment_id: int, data: dict) -> bool:
        status_code, _ = await cls._handle_payment_api_request(
            method="put", endpoint=f"{cls.API_BASE_PATH}{payment_id}/", data=data
        )
        return status_code in {200, 204}

    @classmethod
    async def _get_filtered_payments(cls, filter_func) -> list[Payment]:
        status_code, response = await cls._handle_payment_api_request(method="get", endpoint=cls.API_BASE_PATH)
        if status_code != 200:
            return []
        payments = response.get("results", [])
        return [Payment.model_validate(p) for p in payments if filter_func(p)]

    @classmethod
    async def get_unclosed_payments(cls) -> list[Payment]:
        return await cls._get_filtered_payments(
            lambda p: (
                p.get("status") == PaymentStatus.SUCCESS and p.get("processed") is True and not p.get("payout_handled")
            )
        )

    @classmethod
    async def get_expired_subscriptions(cls, expired_before: str) -> list[Subscription]:
        status_code, response = await cls._handle_payment_api_request(
            method="get",
            endpoint=cls.SUBSCRIPTIONS_PATH,
            data={"enabled": "True", "payment_date__lte": expired_before},
        )
        if status_code != 200:
            logger.error(f"Failed to get expired subscriptions: HTTP {status_code}")
            return []
        results: Sequence[dict] = response.get("results", [])
        return [Subscription.model_validate(item) for item in results]

    @classmethod
    async def get_last_subscription_payment(cls, client_id: int) -> str | None:
        status_code, response = await cls._handle_payment_api_request(
            method="get",
            endpoint=cls.API_BASE_PATH,
            data={"client_profile": client_id, "payment_type": "subscription"},
        )
        if status_code != 200 or not response.get("results"):
            logger.error(f"Failed to get last subscription payment: HTTP {status_code}")
            return None
        payments = response["results"]
        last_payment = max(payments, key=lambda x: x.get("created_at") or "")
        return last_payment.get("order_id")

    @classmethod
    async def update_payment_status(cls, order_id: str, status_: str, error: str = "") -> Payment | None:
        payment, payment_id = await cls._get_payment_by_order_id(order_id)
        if payment_id is None or payment is None:
            logger.error(f"Payment {order_id} not found")
            return None

        ok = await cls.update_payment(
            payment_id,
            {
                "status": PaymentStatus(status_),
                "error": error,
                "processed": False,
                "payout_handled": False,
            },
        )
        if not ok:
            logger.error(f"Failed to update payment {order_id}")
            return None

        logger.info(f"Payment {order_id} set to '{PaymentStatus(status_)}'")
        payment.status = PaymentStatus(status_)  # pyre-ignore[bad-assignment]
        payment.error = error
        payment.processed = False
        payment.payout_handled = False
        return payment

    @classmethod
    async def _get_payment_by_order_id(cls, order_id: str) -> tuple[Payment | None, int | None]:
        status_code, response = await cls._handle_payment_api_request(
            method="get", endpoint=cls.API_BASE_PATH, data={"order_id": order_id}
        )
        if status_code == 200 and response.get("results"):
            raw = response["results"][0]
            try:
                payment = Payment.model_validate(raw)
                return payment, raw["id"]
            except ValidationError as e:
                logger.error(f"Invalid payment data from API for order_id={order_id}: {e}")
        return None, None

    @classmethod
    async def get_latest_payment(cls, client_id: int, payment_type: str) -> Payment | None:
        status_code, response = await cls._handle_payment_api_request(
            method="get",
            endpoint=cls.API_BASE_PATH,
            data={
                "client_profile": client_id,
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
            logger.error(f"Invalid payment data for client_id={client_id}: {e}")
            return None
