import types
import asyncio

import pytest  # pyrefly: ignore[import-error]

from core.infra.payment_repository import HTTPPaymentRepository
from core.enums import PaymentStatus


def _settings() -> types.SimpleNamespace:
    return types.SimpleNamespace(
        API_URL="http://api/",
        API_KEY="key",
        API_MAX_RETRIES=1,
        API_RETRY_INITIAL_DELAY=0,
        API_RETRY_BACKOFF_FACTOR=1,
        API_RETRY_MAX_DELAY=0,
        API_TIMEOUT=5,
    )


class _Client:
    pass


def test_update_payment_status_maps_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def runner() -> None:
        repo = HTTPPaymentRepository(_Client(), _settings())  # pyrefly: ignore[bad-argument-type]
        calls: list[tuple[str, dict]] = []

        async def fake_handle(method, endpoint, data=None):
            if method == "get":
                return 200, {
                    "results": [
                        {
                            "id": 1,
                            "profile": 1,
                            "payment_type": "credits",
                            "order_id": "order",
                            "amount": "10.00",
                            "status": "PENDING",
                            "created_at": 0,
                            "updated_at": 0,
                            "processed": False,
                        }
                    ]
                }
            if method == "patch":
                calls.append((endpoint, data or {}))
                return 200, {}
            return 400, {}

        monkeypatch.setattr(repo, "_handle_payment_api_request", fake_handle)
        payment = await repo.update_payment_status("order", "success")
        assert payment is not None
        assert payment.status == PaymentStatus.SUCCESS
        assert calls[0][0] == "api/v1/payments/1/"
        assert calls[0][1]["status"] == PaymentStatus.SUCCESS.value

    asyncio.run(runner())
