import sys
import types
from decimal import Decimal
from typing import Any


import asyncio

sys.modules.setdefault("apps.payments.tasks", types.ModuleType("apps.payments.tasks"))
sys.modules["apps.payments.tasks"].send_payment_message = types.SimpleNamespace(delay=lambda *a, **k: None)


class DummyTextManager:
    messages: dict[str, dict[str, str]] = {}
    buttons: dict[str, dict[str, str]] = {}
    commands: dict[str, dict[str, str]] = {}

    @classmethod
    def load_resources(cls) -> None:
        return None


sys.modules.setdefault(
    "bot.texts.text_manager",
    types.SimpleNamespace(
        TextManager=DummyTextManager,
        translate=lambda *a, **k: "",
    ),
)
settings_mod = types.ModuleType("config.app_settings")
settings_mod.settings = types.SimpleNamespace(EMAIL="e", TG_SUPPORT_CONTACT="t")
sys.modules["config.app_settings"] = settings_mod


class DummyCache:
    def __init__(self) -> None:
        self.payment = types.SimpleNamespace(calls=[])

        async def set_status(profile_id: int, service_type: str, status: Any) -> None:
            self.payment.calls.append((profile_id, service_type, status))

        self.payment.set_status = set_status


class DummyProfileService:
    def __init__(self, profile: object | None = None) -> None:
        self._profile = profile

    async def get_profile(self, profile_id: int) -> object | None:
        return self._profile


class DummyNotifier:
    def __init__(self, log: list[str]) -> None:
        self.log = log
        self.success_calls: list[tuple[int, str, int]] = []
        self.failure_calls: list[tuple[int, str]] = []

    def success(self, profile_id: int, language: str, credits: int) -> None:
        self.log.append("notify")
        self.success_calls.append((profile_id, language, credits))

    def failure(self, profile_id: int, language: str) -> None:
        self.log.append("fail")
        self.failure_calls.append((profile_id, language))


class CreditTopupStub:
    def __init__(self, log: list[str]) -> None:
        self.log = log
        self.calls: list[tuple[Any, Decimal]] = []

    async def __call__(self, profile: Any, amount: Decimal) -> int:
        self.log.append("topup")
        self.calls.append((profile, amount))
        return 500


def test_success_payment_strategy() -> None:
    async def runner() -> None:
        from core.enums import PaymentStatus
        from core.payment.strategies import SuccessPayment

        cache = DummyCache()
        profile_service = DummyProfileService(profile=types.SimpleNamespace(language="eng"))
        log: list[str] = []
        credit_topup = CreditTopupStub(log)
        notifier = DummyNotifier(log)
        strategy = SuccessPayment(cache, profile_service, credit_topup, notifier)
        payment = types.SimpleNamespace(
            id=1,
            profile=1,
            payment_type="credits",
            order_id="o1",
            amount=Decimal("10"),
            status=PaymentStatus.SUCCESS,
            created_at=0.0,
            updated_at=0.0,
        )
        profile = types.SimpleNamespace(id=1, profile=1, language="eng")
        await strategy.handle(payment, profile)
        assert cache.payment.calls == [(1, "credits", PaymentStatus.SUCCESS)]
        assert credit_topup.calls[0][1] == Decimal("10")
        assert notifier.success_calls == [(1, "eng", 500)]
        assert log == ["topup", "notify"]

    asyncio.run(runner())


def test_failure_payment_strategy() -> None:
    async def runner() -> None:
        from core.enums import PaymentStatus
        from core.payment.strategies import FailurePayment

        cache = DummyCache()
        profile_service = DummyProfileService(profile=types.SimpleNamespace(language="eng"))
        log: list[str] = []
        notifier = DummyNotifier(log)
        strategy = FailurePayment(cache, profile_service, notifier)
        payment = types.SimpleNamespace(
            id=2,
            profile=1,
            payment_type="credits",
            order_id="o2",
            amount=Decimal("5"),
            status=PaymentStatus.FAILURE,
            created_at=0.0,
            updated_at=0.0,
        )
        profile = types.SimpleNamespace(id=1, profile=1, language="eng")
        await strategy.handle(payment, profile)
        assert cache.payment.calls == [(1, "credits", PaymentStatus.FAILURE)]
        assert notifier.failure_calls == [(1, "eng")]

    asyncio.run(runner())
