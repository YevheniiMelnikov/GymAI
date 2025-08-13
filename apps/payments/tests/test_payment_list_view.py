from types import SimpleNamespace

from apps.payments.repos import PaymentRepository
from apps.payments.views import PaymentListView


def test_payment_list_filters(monkeypatch):
    sample = [
        SimpleNamespace(status="success", order_id="1"),
        SimpleNamespace(status="pending", order_id="2"),
    ]

    monkeypatch.setattr(PaymentRepository, "base_qs", staticmethod(lambda: sample))

    called = {}

    def fake_filter(qs, *, status=None, order_id=None):
        called["status"] = status
        called["order_id"] = order_id
        return [p for p in qs if p.status == status and p.order_id == order_id]

    monkeypatch.setattr(PaymentRepository, "filter", staticmethod(fake_filter))

    view = PaymentListView()
    view.request = SimpleNamespace(GET={"status": "success", "order_id": "1"})

    result = view.get_queryset()

    assert called == {"status": "success", "order_id": "1"}
    assert result == [sample[0]]
