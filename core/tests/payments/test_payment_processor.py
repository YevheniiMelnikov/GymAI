import asyncio
from decimal import Decimal, ROUND_HALF_UP
from types import SimpleNamespace
from typing import Any, Awaitable, Callable

from core.enums import PaymentStatus
from core.payment import PaymentProcessor
from core.payment.types import PaymentNotifier
from bot.services.pricing import ServiceCatalog
from config.app_settings import settings


class DummyNotifier(PaymentNotifier):
    def __init__(self) -> None:
        self.success_calls: list[tuple[int, str, int]] = []
        self.failure_calls: list[tuple[int, str]] = []

    def success(self, profile_id: int, language: str, credits: int) -> None:
        self.success_calls.append((profile_id, language, credits))

    def failure(self, profile_id: int, language: str) -> None:
        self.failure_calls.append((profile_id, language))


class DummyStrategy:
    def __init__(self) -> None:
        self.called: list[tuple[Any, Any]] = []

    async def handle(self, payment: Any, profile: Any) -> None:
        self.called.append((payment, profile))


def run(coro_factory: Callable[[], Awaitable[None]]) -> None:
    asyncio.run(coro_factory())


def test_process_payment_invokes_strategy() -> None:
    async def runner() -> None:
        profile = type("Profile", (), {"id": 1, "profile": 1, "credits": 0})()

        async def get_profile(profile_id: int) -> Any:
            assert profile_id == 1
            return profile

        updates: list[tuple[int, dict[str, Any]]] = []

        async def update_payment(payment_id: int, data: dict[str, Any]) -> bool:
            updates.append((payment_id, data))
            return True

        cache = SimpleNamespace(profile=SimpleNamespace(get_record=get_profile), payment=object())
        strategy = DummyStrategy()
        processor = PaymentProcessor(
            cache=cache,
            payment_service=SimpleNamespace(update_payment=update_payment),
            profile_service=object(),
            workout_service=object(),
            notifier=DummyNotifier(),
            strategies={PaymentStatus.SUCCESS: strategy},
        )

        payment = type(
            "Payment",
            (),
            {
                "id": 1,
                "profile": 1,
                "payment_type": "credits",
                "order_id": "o1",
                "amount": Decimal("1"),
                "status": PaymentStatus.SUCCESS,
                "created_at": 0.0,
                "updated_at": 0.0,
                "processed": False,
            },
        )()

        await processor._process_payment(payment)
        assert strategy.called == [(payment, profile)]
        assert updates == [(1, {"processed": True})]

    run(runner)


def test_process_payment_skips_when_processed() -> None:
    async def runner() -> None:
        async def get_profile(profile_id: int) -> Any:
            raise AssertionError("should not be called")

        cache = SimpleNamespace(profile=SimpleNamespace(get_record=get_profile), payment=object())
        processor = PaymentProcessor(
            cache=cache,
            payment_service=SimpleNamespace(update_payment=lambda *_: True),
            profile_service=object(),
            workout_service=object(),
            notifier=DummyNotifier(),
            strategies={PaymentStatus.SUCCESS: DummyStrategy()},
        )

        payment = type(
            "Payment",
            (),
            {
                "id": 2,
                "profile": 1,
                "payment_type": "credits",
                "order_id": "o2",
                "amount": Decimal("1"),
                "status": PaymentStatus.SUCCESS,
                "created_at": 0.0,
                "updated_at": 0.0,
                "processed": True,
            },
        )()

        await processor._process_payment(payment)

    run(runner)


def test_process_payment_no_strategy() -> None:
    async def runner() -> None:
        profile = type("Profile", (), {"id": 1, "profile": 1, "credits": 0})()

        async def get_profile(profile_id: int) -> Any:
            return profile

        updates: list[dict[str, Any]] = []

        async def update_payment(payment_id: int, data: dict[str, Any]) -> bool:
            updates.append(data)
            return True

        cache = SimpleNamespace(profile=SimpleNamespace(get_record=get_profile), payment=object())
        processor = PaymentProcessor(
            cache=cache,
            payment_service=SimpleNamespace(update_payment=update_payment),
            profile_service=object(),
            workout_service=object(),
            notifier=DummyNotifier(),
            strategies={},
        )

        payment = type(
            "Payment",
            (),
            {
                "id": 3,
                "profile": 1,
                "payment_type": "credits",
                "order_id": "o3",
                "amount": Decimal("1"),
                "status": PaymentStatus.CLOSED,
                "created_at": 0.0,
                "updated_at": 0.0,
                "processed": False,
            },
        )()

        await processor._process_payment(payment)
        assert updates == []

    run(runner)


def test_process_credit_topup_updates_profile_and_cache() -> None:
    async def runner() -> None:
        profile_id = 11
        profile = SimpleNamespace(id=profile_id, credits=5, tg_id=1, language="en")
        amount = Decimal(settings.PACKAGE_START_PRICE)

        profile_calls: list[tuple[int, int]] = []

        async def adjust_credits(profile_id: int, delta: int) -> None:
            profile_calls.append((profile_id, delta))

        cache_updates: list[tuple[int, dict[str, Any]]] = []

        async def update_record(profile_id: int, data: dict[str, Any]) -> None:
            cache_updates.append((profile_id, data))

        cache = SimpleNamespace(profile=SimpleNamespace(update_record=update_record))

        async def update_payment(*_: Any) -> bool:
            return True

        processor = PaymentProcessor(
            cache=cache,
            payment_service=SimpleNamespace(update_payment=update_payment),
            profile_service=SimpleNamespace(adjust_credits=adjust_credits),
            workout_service=object(),
            notifier=DummyNotifier(),
            strategies={PaymentStatus.SUCCESS: DummyStrategy()},
        )

        await processor.process_credit_topup(profile, amount)

        normalized = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        package_map = {package.price: package.credits for package in ServiceCatalog.credit_packages()}
        expected_credits = package_map[normalized]
        assert profile_calls == [(profile_id, expected_credits)]
        assert cache_updates == [(profile_id, {"credits": profile.credits + expected_credits})]

    run(runner)
