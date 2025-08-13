from __future__ import annotations

# ruff: noqa: E402

import sys
import types
from decimal import Decimal

import pytest

sys.modules.setdefault("apps.payments.tasks", types.ModuleType("apps.payments.tasks"))
sys.modules["apps.payments.tasks"].send_payment_message = types.SimpleNamespace(delay=lambda *a, **k: None)
sys.modules.setdefault(
    "bot.texts.text_manager",
    types.SimpleNamespace(msg_text=lambda *a, **k: ""),
)
settings_mod = types.ModuleType("config.app_settings")
settings_mod.settings = types.SimpleNamespace(EMAIL="e", TG_SUPPORT_CONTACT="t")
sys.modules["config.app_settings"] = settings_mod

sys.modules.setdefault("core.services", types.ModuleType("core.services"))
sys.modules["core.services"].WorkoutService = object
sys.modules["core.services"].ProfileService = object
sys.modules["core.services"].APIService = types.SimpleNamespace(
    payment=object(), profile=object(), workout=object(), ai_coach=object()
)
gsheets_mod = types.ModuleType("core.services.gsheets_service")
gsheets_mod.GSheetsService = types.SimpleNamespace(create_new_payment_sheet=lambda *a, **k: None)
sys.modules["core.services.gsheets_service"] = gsheets_mod
payment_mod = types.ModuleType("core.services.internal.payment_service")
payment_mod.PaymentService = type("PaymentService", (), {})
sys.modules["core.services.internal.payment_service"] = payment_mod
sys.modules.setdefault("bot.utils.profiles", types.ModuleType("bot.utils.profiles"))
sys.modules["bot.utils.profiles"].get_assigned_coach = lambda *a, **k: None

from core.enums import PaymentStatus
from core.payment_processor import PaymentProcessor


class DummyStrategy:
    def __init__(self) -> None:
        self.called: list[tuple[types.SimpleNamespace, types.SimpleNamespace]] = []

    async def handle(self, payment: types.SimpleNamespace, client: types.SimpleNamespace) -> None:
        self.called.append((payment, client))


class DummyNotifier:
    def success(self, client_id: int, language: str) -> None:  # pragma: no cover - stub
        pass

    def failure(self, client_id: int, language: str) -> None:  # pragma: no cover - stub
        pass


@pytest.mark.asyncio
async def test_process_payment_invokes_strategy() -> None:
    strategy = DummyStrategy()
    client = types.SimpleNamespace(id=1, profile=1)

    async def get_client(profile_id: int):
        assert profile_id == 1
        return client

    cache = types.SimpleNamespace(client=types.SimpleNamespace(get_client=get_client))

    update_called = False

    async def update_payment(payment_id: int, data: dict) -> bool:
        nonlocal update_called
        update_called = True
        assert payment_id == 1
        assert data == {"processed": True}
        return True

    payment_service = types.SimpleNamespace(update_payment=update_payment)

    processor = PaymentProcessor(
        cache=cache,
        payment_service=payment_service,
        profile_service=object(),
        workout_service=object(),
        notifier=DummyNotifier(),
        strategies={PaymentStatus.SUCCESS: strategy},
    )

    payment = types.SimpleNamespace(
        id=1,
        client_profile=1,
        payment_type="credits",
        order_id="o1",
        amount=Decimal("1"),
        status=PaymentStatus.SUCCESS,
        created_at=0.0,
        updated_at=0.0,
        processed=False,
    )

    await processor._process_payment(payment)
    assert strategy.called == [(payment, client)]
    assert update_called


@pytest.mark.asyncio
async def test_process_payment_skips_when_processed() -> None:
    called = False

    async def get_client(profile_id: int):  # pragma: no cover - should not run
        nonlocal called
        called = True
        return types.SimpleNamespace(id=1, profile=1)

    cache = types.SimpleNamespace(client=types.SimpleNamespace(get_client=get_client))

    payment_service = types.SimpleNamespace(update_payment=lambda *a, **k: True)

    processor = PaymentProcessor(
        cache=cache,
        payment_service=payment_service,
        profile_service=object(),
        workout_service=object(),
        notifier=DummyNotifier(),
        strategies={PaymentStatus.SUCCESS: DummyStrategy()},
    )

    payment = types.SimpleNamespace(
        id=2,
        client_profile=1,
        payment_type="credits",
        order_id="o2",
        amount=Decimal("1"),
        status=PaymentStatus.SUCCESS,
        created_at=0.0,
        updated_at=0.0,
        processed=True,
    )

    await processor._process_payment(payment)
    assert not called


@pytest.mark.asyncio
async def test_process_payment_no_strategy() -> None:
    client = types.SimpleNamespace(id=1, profile=1)

    async def get_client(profile_id: int):
        return client

    cache = types.SimpleNamespace(client=types.SimpleNamespace(get_client=get_client))

    update_called = False

    async def update_payment(payment_id: int, data: dict) -> bool:
        nonlocal update_called
        update_called = True
        return True

    payment_service = types.SimpleNamespace(update_payment=update_payment)

    processor = PaymentProcessor(
        cache=cache,
        payment_service=payment_service,
        profile_service=object(),
        workout_service=object(),
        notifier=DummyNotifier(),
        strategies={},
    )

    payment = types.SimpleNamespace(
        id=3,
        client_profile=1,
        payment_type="credits",
        order_id="o3",
        amount=Decimal("1"),
        status=PaymentStatus.CLOSED,
        created_at=0.0,
        updated_at=0.0,
        processed=False,
    )

    await processor._process_payment(payment)
    assert not update_called
