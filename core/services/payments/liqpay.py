from core.payment.providers import liqpay as _providers

LiqPay = _providers.LiqPay
ParamValidationError = _providers.ParamValidationError


class LiqPayGateway(_providers.LiqPayGateway):
    def __init__(self, public_key: str, private_key: str) -> None:
        self.client: _providers.LiqPay = LiqPay(public_key, private_key)
