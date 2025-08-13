# Compatibility shim for moved module
# Old path: core.services.payments.liqpay
# New path: core.payment.providers.liqpay

from core.payment.providers.liqpay import (
    LiqPay,  # noqa: F401
    LiqPayGateway,  # noqa: F401
    ParamValidationError,  # noqa: F401
)
