from typing import Optional, cast, Dict, Any

from django.core.cache import cache
from django.db.models import QuerySet
from rest_framework.exceptions import NotFound

from apps.payments.models import Payment
from apps.payments.serializers import PaymentSerializer
from config.app_settings import settings


class PaymentRepository:
    @staticmethod
    def _key(pk: int) -> str:
        return f"payment:{pk}"

    @staticmethod
    def base_qs() -> QuerySet[Payment]:  # pyrefly: ignore[bad-specialization]
        return Payment.objects.all()  # type: ignore[return-value,missing-attribute]

    @staticmethod
    def get_model(pk: int) -> Payment:
        try:
            return Payment.objects.get(pk=pk)  # pyrefly: ignore[missing-attribute]
        except Payment.DoesNotExist:  # pyrefly: ignore[missing-attribute]
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
            pk_value = cached.get("id")
            if pk_value is not None:
                payment.pk = int(pk_value)
            payment._state.adding = False
            return payment

        return cast(Payment, cached)

    @staticmethod
    def filter(
        qs: QuerySet[Payment],  # pyrefly: ignore[bad-specialization]
        *,
        status: Optional[str] = None,
        order_id: Optional[str] = None,
    ) -> QuerySet[Payment]:  # pyrefly: ignore[bad-specialization]
        if status:
            qs = qs.filter(status=status)
        if order_id:
            qs = qs.filter(order_id=order_id)
        return qs

    @staticmethod
    def get_by_order_id(order_id: str) -> Payment:
        try:
            return Payment.objects.get(order_id=order_id)  # pyrefly: ignore[missing-attribute]
        except Payment.DoesNotExist:  # pyrefly: ignore[missing-attribute]
            raise NotFound(f"Payment order_id={order_id} not found")
