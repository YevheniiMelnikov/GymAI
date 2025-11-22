import base64
import hashlib
import json
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, NamedTuple
from urllib.parse import urlencode, urljoin

from core.payment.providers.payment_gateway import CheckoutPayload, PaymentGateway


class ParamValidationError(Exception):
    pass


class LiqPay:
    SUPPORTED_PARAMS = [
        "public_key",
        "amount",
        "currency",
        "description",
        "order_id",
        "result_url",
        "server_url",
        "type",
        "signature",
        "language",
        "version",
        "action",
    ]
    SUPPORTED_CURRENCIES = ["EUR", "USD", "UAH"]
    SUPPORTED_LANGS = ["uk", "en"]
    SUPPORTED_VERSION = "3"

    def __init__(self, public_key: str, private_key: str, host: str = "https://www.liqpay.ua/api/"):
        self.public_key = public_key
        self.private_key = private_key
        self.host = host

    def _make_signature(self, *args: str) -> str:
        data = "".join(args).encode("utf-8")
        return base64.b64encode(hashlib.sha1(data).digest()).decode("ascii")

    def _prepare_params(self, params: dict[str, Any] | None) -> dict[str, Any]:
        prepared: dict[str, Any] = deepcopy(params or {})
        prepared["public_key"] = self.public_key
        required_fields: set[str] = {
            "version",
            "amount",
            "currency",
            "action",
            "order_id",
            "description",
        }
        missing: set[str] = required_fields - set(prepared)
        if missing:
            missing_fields = ", ".join(sorted(missing))
            raise ParamValidationError(f"Missing required field(s): {missing_fields}")
        if str(prepared["version"]) != self.SUPPORTED_VERSION:
            raise ParamValidationError("Invalid version")
        if prepared["currency"] not in self.SUPPORTED_CURRENCIES:
            raise ParamValidationError("Invalid currency")
        return prepared

    def get_data_end_signature(self, type: str, params: dict) -> tuple[str, str]:
        json_params = json.dumps(params, sort_keys=True)
        if type == "cnb_form":
            encoded = base64.b64encode(json_params.encode("utf-8")).decode("utf-8")
            sign = self._make_signature(self.private_key, encoded, self.private_key)
            return encoded, sign
        else:
            sign = self._make_signature(self.private_key, json_params, self.private_key)
            return json_params, sign

    def cnb_signature(self, params: dict) -> str:
        prepared = self._prepare_params(params)
        encoded = self.data_to_sign(prepared)
        return self._make_signature(self.private_key, encoded, self.private_key)

    def cnb_data(self, params: dict) -> str:
        prepared = self._prepare_params(params)
        return self.data_to_sign(prepared)

    def data_to_sign(self, params: dict) -> str:
        return base64.b64encode(json.dumps(params, sort_keys=True).encode("utf-8")).decode("utf-8")

    def decode_data_from_str(self, data: str, signature: str | None = None) -> dict[str, Any]:
        decoded_json: str = base64.b64decode(data).decode("utf-8")
        if signature:
            expected: str = self._make_signature(self.private_key, data, self.private_key)
            if expected != signature:
                raise ParamValidationError("Invalid signature")
        return json.loads(decoded_json)


class LiqPayCheckout(NamedTuple):
    data: str
    signature: str
    checkout_url: str


class LiqPayGateway(PaymentGateway):
    def __init__(
        self,
        public_key: str,
        private_key: str,
        *,
        server_url: str | None = None,
        result_url: str | None = None,
        email: str | None = None,
        checkout_url: str | None = None,
    ) -> None:
        self.client = LiqPay(public_key, private_key)
        self._server_url = server_url or ""
        self._result_url = result_url or ""
        self._email = email or ""
        self._checkout_url = checkout_url or ""

    def _build_params(
        self,
        action: str,
        amount: Decimal,
        order_id: str,
        payment_type: str,
        profile_id: int,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "action": action,
            "amount": str(amount.quantize(Decimal("0.01"), ROUND_HALF_UP)),
            "currency": "UAH",
            "description": f"{payment_type} payment from client {profile_id}",
            "order_id": order_id,
            "version": "3",
        }
        if self._server_url:
            params["server_url"] = self._server_url
        if self._result_url:
            params["result_url"] = self._result_url
        if self._email:
            params["rro_info"] = {"delivery_emails": [self._email]}
        return params

    def build_checkout(
        self,
        action: str,
        amount: Decimal,
        order_id: str,
        payment_type: str,
        profile_id: int,
    ) -> CheckoutPayload:
        params = self._build_params(action, amount, order_id, payment_type, profile_id)
        data: str = self.client.cnb_data(params)
        signature: str = self.client.cnb_signature(params)
        checkout_url: str = str(self._checkout_url)
        return LiqPayCheckout(
            data=data,
            signature=signature,
            checkout_url=urljoin(checkout_url, f"?{urlencode({'data': data, 'signature': signature})}"),
        )

    async def get_payment_link(
        self,
        action: str,
        amount: Decimal,
        order_id: str,
        payment_type: str,
        profile_id: int,
    ) -> str:
        checkout = self.build_checkout(action, amount, order_id, payment_type, profile_id)
        return checkout.checkout_url
