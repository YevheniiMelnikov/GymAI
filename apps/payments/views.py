from __future__ import annotations

import base64
import json
from typing import Any

from django.core.cache import cache
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django.http import JsonResponse
from loguru import logger
from rest_framework import generics, status, serializers
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView
from rest_framework_api_key.permissions import HasAPIKey

from apps.payments.models import Payment
from apps.payments.repos import PaymentRepository
from apps.payments.serializers import PaymentSerializer
from apps.payments.tasks import process_payment_webhook
from config.env_settings import settings
from core.services import LiqPay


class PaymentWebhookView(APIView):
    permission_classes = [AllowAny]

    @staticmethod
    def _verify_signature(raw_data: str, signature: str) -> bool:
        lp = LiqPay(settings.PAYMENT_PUB_KEY, settings.PAYMENT_PRIVATE_KEY)
        expected = lp.str_to_sign(f"{settings.PAYMENT_PRIVATE_KEY}{raw_data}{settings.PAYMENT_PRIVATE_KEY}")
        return signature == expected

    @staticmethod
    def post(request, *args, **kwargs):
        try:
            raw_data: str | None = request.POST.get("data")
            signature: str | None = request.POST.get("signature")
            if not raw_data or not signature:
                return JsonResponse({"detail": "Missing fields"}, status=status.HTTP_400_BAD_REQUEST)
            if not PaymentWebhookView._verify_signature(raw_data, signature):
                return JsonResponse({"detail": "Invalid signature"}, status=status.HTTP_400_BAD_REQUEST)
            payment_info: dict[str, Any] = json.loads(base64.b64decode(raw_data).decode())

            cache.delete(f"payment:{payment_info.get('order_id')}")

            process_payment_webhook.delay(
                order_id=payment_info.get("order_id"),
                status=payment_info.get("status"),
                err_description=payment_info.get("err_description", ""),
            )
            return JsonResponse({"result": "OK"}, status=status.HTTP_200_OK)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Webhook processing error")
            return JsonResponse({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


@method_decorator(cache_page(60 * 5), name="dispatch")
class PaymentListView(generics.ListAPIView):
    serializer_class = PaymentSerializer
    permission_classes = [HasAPIKey]

    def get_queryset(self):
        qs = PaymentRepository.base_qs()
        return PaymentRepository.filter(
            qs,
            status=self.request.GET.get("status"),
            order_id=self.request.GET.get("order_id"),
        )


class PaymentDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = PaymentSerializer
    permission_classes = [HasAPIKey]

    def get_queryset(self):
        return PaymentRepository.base_qs()

    def perform_update(self, serializer: serializers.BaseSerializer) -> None:  # pyre-ignore[bad-override]
        instance: Payment = serializer.save()
        cache.delete(f"payment:{instance.id}")  # type: ignore[attr-defined]
        cache.delete_many(["payments:list"])


class PaymentCreateView(generics.CreateAPIView):
    serializer_class = PaymentSerializer
    permission_classes = [HasAPIKey]

    def get_queryset(self):
        return PaymentRepository.base_qs()

    def perform_create(self, serializer: serializers.BaseSerializer) -> None:  # pyre-ignore[bad-override]
        payment: Payment = serializer.save()
        cache.delete_many(["payments:list"])
        logger.debug(f"Payment id={payment.id} created → list cache flushed")  # type: ignore[attr-defined]
