import base64
import json

import pytest
from django.test import RequestFactory

from apps.payments.views import PaymentWebhookView


@pytest.mark.django_db
def test_webhook_view_valid(monkeypatch):
    factory = RequestFactory()
    data = base64.b64encode(json.dumps({"order_id": "1", "status": "success"}).encode()).decode()
    request = factory.post("/payment-webhook/", {"data": data, "signature": "sig"})

    monkeypatch.setattr(PaymentWebhookView, "_verify_signature", staticmethod(lambda d, s: True))
    called = {}

    def fake_delay(**kwargs):
        called["args"] = kwargs

    monkeypatch.setattr("apps.payments.views.process_payment_webhook.delay", fake_delay)

    response = PaymentWebhookView.as_view()(request)
    assert response.status_code == 200
    assert called["args"]["order_id"] == "1"


@pytest.mark.django_db
def test_webhook_view_bad_signature(monkeypatch):
    factory = RequestFactory()
    data = base64.b64encode(json.dumps({"order_id": "1"}).encode()).decode()
    request = factory.post("/payment-webhook/", {"data": data, "signature": "bad"})

    monkeypatch.setattr(PaymentWebhookView, "_verify_signature", staticmethod(lambda d, s: False))
    response = PaymentWebhookView.as_view()(request)
    assert response.status_code == 400
