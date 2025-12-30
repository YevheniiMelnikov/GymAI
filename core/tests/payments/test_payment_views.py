from types import SimpleNamespace

import pytest

from apps.payments.views import PaymentCreateView, PaymentDetailView


def test_payment_detail_update_invalidates_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    delete_calls: list[str] = []
    delete_many_calls: list[list[str]] = []

    monkeypatch.setattr("apps.payments.views.cache.delete", lambda key: delete_calls.append(key))
    monkeypatch.setattr(
        "apps.payments.views.cache.delete_many",
        lambda keys: delete_many_calls.append(list(keys)),
    )

    serializer = SimpleNamespace(save=lambda: SimpleNamespace(id="p1"))
    PaymentDetailView().perform_update(serializer)  # type: ignore[arg-type]

    assert delete_calls == ["payment:p1"]
    assert delete_many_calls == [["payments:list"]]


def test_payment_create_invalidates_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    delete_many_calls: list[list[str]] = []
    monkeypatch.setattr(
        "apps.payments.views.cache.delete_many",
        lambda keys: delete_many_calls.append(list(keys)),
    )

    serializer = SimpleNamespace(save=lambda: SimpleNamespace(id="p2"))
    PaymentCreateView().perform_create(serializer)  # type: ignore[arg-type]

    assert delete_many_calls == [["payments:list"]]
