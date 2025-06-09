from __future__ import annotations

from typing import Optional, cast, Dict, Any

from django.core.cache import cache
from django.db.models import QuerySet
from rest_framework.exceptions import NotFound

from apps.payments.models import Payment
from apps.payments.serializers import PaymentSerializer
from config.env_settings import settings


class PaymentRepository:
    @staticmethod
    def _key(pk: int) -> str:
        return f"payment:{pk}"

    @staticmethod
    def base_qs() -> QuerySet[Payment]:
        return Payment.objects.all()  # type: ignore[return-value]

    @staticmethod
    def get_model(pk: int) -> Payment:
        try:
            payment = Payment.objects.get(pk=pk)
            return cast(Payment, payment)
        except Payment.DoesNotExist:
            raise NotFound(f"Payment pk={pk} not found")

    @staticmethod
    def get(pk: int) -> Payment:
        def fetch_payment() -> Dict[str, Any]:
            instance = PaymentRepository.get_model(pk)
            return PaymentSerializer(instance).data

        cached = cache.get_or_set(
            PaymentRepository._key(pk),
            fetch_payment,
            settings.CACHE_TTL,
        )

        if isinstance(cached, dict):
            payment = Payment(**cached)
            payment.pk = cached.get("id")
            payment._state.adding = False
            return payment

        return cast(Payment, cached)

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
