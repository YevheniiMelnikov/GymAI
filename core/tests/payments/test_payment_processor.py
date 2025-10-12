from __future__ import annotations

import asyncio
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Awaitable, Callable

from core.enums import CoachType, PaymentStatus
from core.payment import PaymentProcessor
from core.payment.types import CoachResolver, CreditService, PaymentNotifier


class DummyCreditService(CreditService):
    def __init__(self) -> None:
        self.requested: list[Decimal] = []

    def credits_for_amount(self, amount: Decimal) -> int:
        self.requested.append(amount)
        return int(amount)


class DummyCoachResolver(CoachResolver):
    def __init__(self, coach: Any | None = None) -> None:
        self.coach = coach
        self.calls: list[tuple[Any, Any | None]] = []

    async def get_assigned_coach(self, client: Any, *, coach_type: Any | None = None) -> Any | None:
        self.calls.append((client, coach_type))
        return self.coach


class DummyNotifier(PaymentNotifier):
    def __init__(self) -> None:
        self.success_calls: list[tuple[int, str]] = []
        self.failure_calls: list[tuple[int, str]] = []

    def success(self, client_id: int, language: str) -> None:
        self.success_calls.append((client_id, language))

    def failure(self, client_id: int, language: str) -> None:
        self.failure_calls.append((client_id, language))


class DummyStrategy:
    def __init__(self) -> None:
        self.called: list[tuple[Any, Any]] = []

    async def handle(self, payment: Any, client: Any) -> None:
        self.called.append((payment, client))


def run(coro_factory: Callable[[], Awaitable[None]]) -> None:
    asyncio.run(coro_factory())


def test_process_payment_invokes_strategy() -> None:
    async def runner() -> None:
        client = type("Client", (), {"id": 1, "profile": 1, "credits": 0})()

        async def get_client(profile_id: int) -> Any:
            assert profile_id == 1
            return client

        updates: list[tuple[int, dict[str, Any]]] = []

        async def update_payment(payment_id: int, data: dict[str, Any]) -> bool:
            updates.append((payment_id, data))
            return True

        cache = SimpleNamespace(client=SimpleNamespace(get_client=get_client), coach=object(), payment=object())
        strategy = DummyStrategy()
        processor = PaymentProcessor(
            cache=cache,
            payment_service=SimpleNamespace(update_payment=update_payment),
            profile_service=object(),
            workout_service=object(),
            notifier=DummyNotifier(),
            credit_service=DummyCreditService(),
            coach_resolver=DummyCoachResolver(),
            strategies={PaymentStatus.SUCCESS: strategy},
        )

        payment = type(
            "Payment",
            (),
            {
                "id": 1,
                "client_profile": 1,
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
        assert strategy.called == [(payment, client)]
        assert updates == [(1, {"processed": True})]

    run(runner)


def test_process_payment_skips_when_processed() -> None:
    async def runner() -> None:
        async def get_client(profile_id: int) -> Any:
            raise AssertionError("should not be called")

        cache = SimpleNamespace(client=SimpleNamespace(get_client=get_client), coach=object(), payment=object())
        processor = PaymentProcessor(
            cache=cache,
            payment_service=SimpleNamespace(update_payment=lambda *_: True),
            profile_service=object(),
            workout_service=object(),
            notifier=DummyNotifier(),
            credit_service=DummyCreditService(),
            coach_resolver=DummyCoachResolver(),
            strategies={PaymentStatus.SUCCESS: DummyStrategy()},
        )

        payment = type(
            "Payment",
            (),
            {
                "id": 2,
                "client_profile": 1,
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
        client = type("Client", (), {"id": 1, "profile": 1, "credits": 0})()

        async def get_client(profile_id: int) -> Any:
            return client

        updates: list[dict[str, Any]] = []

        async def update_payment(payment_id: int, data: dict[str, Any]) -> bool:
            updates.append(data)
            return True

        cache = SimpleNamespace(client=SimpleNamespace(get_client=get_client), coach=object(), payment=object())
        processor = PaymentProcessor(
            cache=cache,
            payment_service=SimpleNamespace(update_payment=update_payment),
            profile_service=object(),
            workout_service=object(),
            notifier=DummyNotifier(),
            credit_service=DummyCreditService(),
            coach_resolver=DummyCoachResolver(),
            strategies={},
        )

        payment = type(
            "Payment",
            (),
            {
                "id": 3,
                "client_profile": 1,
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


def test_process_credit_topup_uses_credit_service_and_updates_profile_and_cache() -> None:
    async def runner() -> None:
        client = SimpleNamespace(profile=11, credits=5)
        amount = Decimal("123.45")
        credit_service = DummyCreditService()

        profile_calls: list[tuple[int, int]] = []

        async def adjust_client_credits(profile_id: int, delta: int) -> None:
            profile_calls.append((profile_id, delta))

        cache_updates: list[tuple[int, dict[str, Any]]] = []

        async def update_client(profile_id: int, data: dict[str, Any]) -> None:
            cache_updates.append((profile_id, data))

        cache = SimpleNamespace(client=SimpleNamespace(update_client=update_client))

        async def update_payment(*_: Any) -> bool:
            return True

        processor = PaymentProcessor(
            cache=cache,
            payment_service=SimpleNamespace(update_payment=update_payment),
            profile_service=SimpleNamespace(adjust_client_credits=adjust_client_credits),
            workout_service=object(),
            notifier=DummyNotifier(),
            credit_service=credit_service,
            coach_resolver=DummyCoachResolver(),
            strategies={PaymentStatus.SUCCESS: DummyStrategy()},
        )

        await processor.process_credit_topup(client, amount)

        assert credit_service.requested == [amount]
        assert profile_calls == [(client.profile, int(amount))]
        assert cache_updates == [(client.profile, {"credits": client.credits + int(amount)})]

    run(runner)


def test__process_payout_marks_handled_and_returns_row_for_human_coach() -> None:
    async def runner() -> None:
        payment = SimpleNamespace(
            id=5,
            client_profile=21,
            amount=Decimal("10.005"),
            order_id="order-123",
        )
        client = SimpleNamespace(assigned_to=34)

        async def get_client(profile_id: int) -> Any:
            assert profile_id == payment.client_profile
            return client

        payment_updates: list[tuple[int, dict[str, Any]]] = []

        async def update_payment(payment_id: int, data: dict[str, Any]) -> bool:
            payment_updates.append((payment_id, data))
            return True

        coach = SimpleNamespace(
            id=99,
            coach_type=CoachType.human,
            name="John",
            surname="Doe",
            payment_details="UA123",
        )
        resolver = DummyCoachResolver(coach)

        cache = SimpleNamespace(
            client=SimpleNamespace(get_client=get_client),
            coach=object(),
            payment=object(),
        )
        processor = PaymentProcessor(
            cache=cache,
            payment_service=SimpleNamespace(update_payment=update_payment),
            profile_service=object(),
            workout_service=object(),
            notifier=DummyNotifier(),
            credit_service=DummyCreditService(),
            coach_resolver=resolver,
            strategies={PaymentStatus.SUCCESS: DummyStrategy()},
        )

        result = await processor._process_payout(payment)

        assert resolver.calls == [(client, CoachType.human)]
        assert payment_updates == [(payment.id, {"payout_handled": True})]
        assert result == ["John", "Doe", "UA123", payment.order_id, "10.01"]

    run(runner)


def test__process_payout_returns_none_for_ai_coach() -> None:
    async def runner() -> None:
        payment = SimpleNamespace(
            id=7,
            client_profile=55,
            amount=Decimal("42.00"),
            order_id="order-ai",
        )
        client = SimpleNamespace(assigned_to=1)

        async def get_client(profile_id: int) -> Any:
            assert profile_id == payment.client_profile
            return client

        payment_updates: list[tuple[int, dict[str, Any]]] = []

        async def update_payment(payment_id: int, data: dict[str, Any]) -> bool:
            payment_updates.append((payment_id, data))
            return True

        coach = SimpleNamespace(
            id=100,
            coach_type=CoachType.ai_coach,
            name="AI",
            surname="Coach",
            payment_details="",
        )
        resolver = DummyCoachResolver(coach)

        cache = SimpleNamespace(
            client=SimpleNamespace(get_client=get_client),
            coach=object(),
            payment=object(),
        )
        processor = PaymentProcessor(
            cache=cache,
            payment_service=SimpleNamespace(update_payment=update_payment),
            profile_service=object(),
            workout_service=object(),
            notifier=DummyNotifier(),
            credit_service=DummyCreditService(),
            coach_resolver=resolver,
            strategies={PaymentStatus.SUCCESS: DummyStrategy()},
        )

        result = await processor._process_payout(payment)

        assert resolver.calls == [(client, CoachType.human)]
        assert result is None
        assert payment_updates == []

    run(runner)
