import base64
import json
from types import SimpleNamespace

from apps.payments.views import PaymentWebhookView


def test_webhook_view_valid(monkeypatch):
    data = base64.b64encode(json.dumps({"order_id": "1", "status": "success"}).encode()).decode()
    request = SimpleNamespace(POST={"data": data, "signature": "sig"})

    monkeypatch.setattr(PaymentWebhookView, "_verify_signature", staticmethod(lambda d, s: True))
    called = {}
    monkeypatch.setattr(
        "apps.payments.views.process_payment_webhook.delay",
        lambda **kwargs: called.update(kwargs),
    )

    response = PaymentWebhookView.post(request)

    assert response.status_code == 200
    assert called["order_id"] == "1"


def test_webhook_view_bad_signature(monkeypatch):
    data = base64.b64encode(json.dumps({"order_id": "1"}).encode()).decode()
    request = SimpleNamespace(POST={"data": data, "signature": "bad"})

    monkeypatch.setattr(PaymentWebhookView, "_verify_signature", staticmethod(lambda d, s: False))

    response = PaymentWebhookView.post(request)
    assert response.status_code == 400
