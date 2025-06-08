from apps.payments.views import PaymentWebhookView


def test_verify_signature(monkeypatch):
    def fake_str_to_sign(_data):
        return "sig"

    monkeypatch.setattr("liqpay.LiqPay.str_to_sign", staticmethod(fake_str_to_sign))
    assert PaymentWebhookView._verify_signature("data", "sig") is True
    assert PaymentWebhookView._verify_signature("data", "bad") is False
