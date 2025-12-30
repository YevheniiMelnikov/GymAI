from types import SimpleNamespace

import pytest

from core.tasks import billing


def test_charge_due_subscriptions_handles_low_and_sufficient_credits(monkeypatch: pytest.MonkeyPatch) -> None:
    sub_low = SimpleNamespace(id=1, profile=1, price=10, period="1m")
    sub_ok = SimpleNamespace(id=2, profile=2, price=5, period="1m")
    profile_records = {
        1: SimpleNamespace(id=101, credits=5),
        2: SimpleNamespace(id=202, credits=10),
    }

    async def get_expired_subscriptions(_today: str):
        return [sub_low, sub_ok]

    api_calls: list[tuple[str, int, dict]] = []
    cache_calls: list[tuple[str, int, dict]] = []
    adjust_calls: list[tuple[int, int]] = []
    reset_calls: list[tuple[int, str]] = []

    async def workout_update(sub_id: int, payload: dict) -> None:
        api_calls.append(("workout_update", sub_id, dict(payload)))

    async def profile_adjust(profile_id: int, delta: int) -> None:
        adjust_calls.append((profile_id, delta))

    async def cache_workout_update(profile_id: int, payload: dict) -> None:
        cache_calls.append(("workout_update", profile_id, dict(payload)))

    async def cache_payment_reset(profile_id: int, status: str) -> None:
        reset_calls.append((profile_id, status))

    async def cache_profile_get(profile_id: int):
        return profile_records[profile_id]

    async def cache_profile_update(profile_id: int, payload: dict) -> None:
        cache_calls.append(("profile_update", profile_id, dict(payload)))

    api_stub = SimpleNamespace(
        payment=SimpleNamespace(get_expired_subscriptions=get_expired_subscriptions),
        workout=SimpleNamespace(update_subscription=workout_update),
        profile=SimpleNamespace(adjust_credits=profile_adjust),
    )
    cache_stub = SimpleNamespace(
        workout=SimpleNamespace(update_subscription=cache_workout_update),
        payment=SimpleNamespace(reset_status=cache_payment_reset),
        profile=SimpleNamespace(get_record=cache_profile_get, update_record=cache_profile_update),
    )

    monkeypatch.setattr(billing, "APIService", api_stub)
    monkeypatch.setattr(billing, "Cache", cache_stub)
    monkeypatch.setattr(billing, "_next_payment_date", lambda _period: "next-date")

    billing.charge_due_subscriptions()

    assert ("workout_update", 1, {"enabled": False, "profile": 1}) in api_calls
    assert ("workout_update", 1, {"enabled": False}) in cache_calls
    assert reset_calls == [(1, "subscription")]
    assert adjust_calls == [(202, -5)]
    assert ("profile_update", 202, {"credits": 5}) in cache_calls
    assert ("workout_update", 2, {"payment_date": "next-date"}) in api_calls
    assert ("workout_update", 2, {"payment_date": "next-date"}) in cache_calls


def test_warn_low_credits_sends_message_for_low_balance(monkeypatch: pytest.MonkeyPatch) -> None:
    sub_low = SimpleNamespace(id=1, profile=1, price=10)
    sub_ok = SimpleNamespace(id=2, profile=2, price=5)
    profile_records = {
        1: SimpleNamespace(id=101, credits=3),
        2: SimpleNamespace(id=202, credits=10),
    }

    async def get_expired_subscriptions(_tomorrow: str):
        return [sub_low, sub_ok]

    async def cache_profile_get(profile_id: int):
        return profile_records[profile_id]

    async def get_profile(_profile_id: int):
        return SimpleNamespace(language="ru")

    sent: list[tuple[int, str]] = []

    class _DelayStub:
        def __call__(self, profile_id: int, text: str) -> None:
            sent.append((profile_id, text))

    api_stub = SimpleNamespace(
        payment=SimpleNamespace(get_expired_subscriptions=get_expired_subscriptions),
        profile=SimpleNamespace(get_profile=get_profile),
    )
    cache_stub = SimpleNamespace(profile=SimpleNamespace(get_record=cache_profile_get))

    monkeypatch.setattr(billing, "APIService", api_stub)
    monkeypatch.setattr(billing, "Cache", cache_stub)
    monkeypatch.setattr(billing, "translate", lambda _key, _lang: "msg")
    monkeypatch.setattr(billing.send_payment_message, "delay", _DelayStub())

    billing.warn_low_credits()

    assert sent == [(1, "msg")]


def test_deactivate_expired_subscriptions_disables_and_resets(monkeypatch: pytest.MonkeyPatch) -> None:
    sub = SimpleNamespace(id=1, profile=10)

    async def get_expired_subscriptions(_today: str):
        return [sub]

    api_calls: list[tuple[int, dict]] = []
    cache_calls: list[tuple[int, dict]] = []
    reset_calls: list[tuple[int, str]] = []

    async def workout_update(sub_id: int, payload: dict) -> None:
        api_calls.append((sub_id, dict(payload)))

    async def cache_workout_update(profile_id: int, payload: dict) -> None:
        cache_calls.append((profile_id, dict(payload)))

    async def cache_payment_reset(profile_id: int, status: str) -> None:
        reset_calls.append((profile_id, status))

    api_stub = SimpleNamespace(
        payment=SimpleNamespace(get_expired_subscriptions=get_expired_subscriptions),
        workout=SimpleNamespace(update_subscription=workout_update),
    )
    cache_stub = SimpleNamespace(
        workout=SimpleNamespace(update_subscription=cache_workout_update),
        payment=SimpleNamespace(reset_status=cache_payment_reset),
    )

    monkeypatch.setattr(billing, "APIService", api_stub)
    monkeypatch.setattr(billing, "Cache", cache_stub)

    billing.deactivate_expired_subscriptions()

    assert api_calls == [(1, {"enabled": False, "profile": 10})]
    assert cache_calls == [(10, {"enabled": False})]
    assert reset_calls == [(10, "subscription")]
