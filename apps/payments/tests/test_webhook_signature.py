from core.services.payments.liqpay import LiqPay
from apps.payments.views import PaymentWebhookView


def test_verify_signature(monkeypatch):
    def fake_str_to_sign(data):
        return "sig"

    monkeypatch.setattr(LiqPay, "str_to_sign", staticmethod(fake_str_to_sign), raising=False)

    assert PaymentWebhookView._verify_signature("data", "sig") is True
    assert PaymentWebhookView._verify_signature("data", "bad") is False
