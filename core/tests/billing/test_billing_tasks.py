from types import SimpleNamespace

import pytest

from core.tasks import billing


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
