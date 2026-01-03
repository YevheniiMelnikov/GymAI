import base64
import hashlib

from apps.payments import views as payment_views
from apps.payments.views import PaymentWebhookView


def test_verify_signature(monkeypatch):
    monkeypatch.setattr(payment_views.settings, "PAYMENT_PRIVATE_KEY", "key", raising=False)

    payload = b"keydatakey"
    expected = base64.b64encode(hashlib.sha3_256(payload).digest()).decode("ascii")

    assert PaymentWebhookView._verify_signature("data", expected) is True
    assert PaymentWebhookView._verify_signature("data", "bad") is False
