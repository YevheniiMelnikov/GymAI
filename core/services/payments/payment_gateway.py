# Compatibility shim for moved module
# Old path: core.services.payments.payment_gateway
# New path: core.payment.providers.payment_gateway

from core.payment.providers.payment_gateway import (
    PaymentGateway,  # noqa: F401
)
