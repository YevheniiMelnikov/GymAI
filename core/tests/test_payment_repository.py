import types
from decimal import Decimal

import pytest  # pyrefly: ignore[import-error]

from core.infra.payment_repository import HTTPPaymentRepository


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


@pytest.mark.asyncio
async def test_create_payment_success(monkeypatch):
    repo = HTTPPaymentRepository(_Client(), _settings())  # pyrefly: ignore[bad-argument-type]

    async def fake_handle(method, endpoint, data=None):
        return 201, {}

    monkeypatch.setattr(repo, "_handle_payment_api_request", fake_handle)
    ok = await repo.create_payment(1, "type", "order", Decimal("10"))
    assert ok is True


@pytest.mark.asyncio
async def test_create_payment_failure(monkeypatch):
    repo = HTTPPaymentRepository(_Client(), _settings())  # pyrefly: ignore[bad-argument-type]

    async def fake_handle(method, endpoint, data=None):
        return 400, {}

    monkeypatch.setattr(repo, "_handle_payment_api_request", fake_handle)
    ok = await repo.create_payment(1, "type", "order", Decimal("10"))
    assert ok is False
