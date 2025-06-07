from __future__ import annotations

from typing import Optional, cast

from django.core.cache import cache
from django.db.models import QuerySet
from rest_framework.exceptions import NotFound

from apps.payments.models import Payment
from config.env_settings import Settings


class PaymentRepository:
    @staticmethod
    def _key(pk: int) -> str:
        return f"payment:{pk}"

    @staticmethod
    def base_qs() -> QuerySet[Payment]:
        return Payment.objects.all()  # type: ignore[return-value]

    @staticmethod
    def get(pk: int) -> Payment:
        def get_payment() -> Payment:
            try:
                payment = Payment.objects.get(pk=pk)
                return cast(Payment, payment)
            except Payment.DoesNotExist:
                raise NotFound(f"Payment pk={pk} not found")

        result = cache.get_or_set(
            PaymentRepository._key(pk),
            get_payment,
            Settings.CACHE_TTL,
        )
        return cast(Payment, result)

    @staticmethod
    def filter(
        qs: QuerySet[Payment],
        *,
        status: Optional[str] = None,
        order_id: Optional[str] = None,
    ) -> QuerySet[Payment]:
        if status:
            qs = qs.filter(status=status)
        if order_id:
            qs = qs.filter(order_id=order_id)
        return qs
