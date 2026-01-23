import base64
import hashlib
import json
from typing import Any

from django.core.cache import cache
from django.http import JsonResponse, HttpRequest
from loguru import logger
from rest_framework import generics, status, serializers
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView
from rest_framework_api_key.permissions import HasAPIKey

from apps.payments.models import Payment
from apps.payments.repos import PaymentRepository
from apps.payments.serializers import PaymentSerializer
from apps.payments.tasks import process_payment_webhook
from config.app_settings import settings


class PaymentWebhookView(APIView):
    permission_classes = [AllowAny]  # pyrefly: ignore[bad-override]

    @staticmethod
    def _verify_signature(raw_data: str, signature: str) -> bool:
        payload = f"{settings.PAYMENT_PRIVATE_KEY}{raw_data}{settings.PAYMENT_PRIVATE_KEY}".encode("utf-8")
        expected_sha3 = base64.b64encode(hashlib.sha3_256(payload).digest()).decode("ascii")
        if signature == expected_sha3:
            return True
        expected_sha1 = base64.b64encode(hashlib.sha1(payload).digest()).decode("ascii")
        return signature == expected_sha1

    @staticmethod
    def post(request: HttpRequest, *args, **kwargs) -> JsonResponse:
        try:
            raw_data_val = request.POST.get("data")
            signature_val = request.POST.get("signature")

            if not isinstance(raw_data_val, str) or not isinstance(signature_val, str):
                logger.warning("payment_webhook_missing_fields")
                return JsonResponse({"detail": "Missing fields"}, status=status.HTTP_400_BAD_REQUEST)

            if not PaymentWebhookView._verify_signature(raw_data_val, signature_val):
                logger.warning("payment_webhook_invalid_signature")
                return JsonResponse({"detail": "Invalid signature"}, status=status.HTTP_400_BAD_REQUEST)

            try:
                decoded = base64.b64decode(raw_data_val).decode()
                payment_info: dict[str, Any] = json.loads(decoded)
            except Exception:
                logger.warning("Failed to decode or parse payment data")
                return JsonResponse({"detail": "Invalid payload format"}, status=status.HTTP_400_BAD_REQUEST)

            order_id = payment_info.get("order_id")

            logger.info(
                "payment_webhook_received "
                f"order_id={order_id} status={payment_info.get('status')} payment_id={payment_info.get('payment_id')}"
            )

            process_payment_webhook.delay(  # pyrefly: ignore[not-callable]
                order_id=order_id,
                status=payment_info.get("status"),
                err_description=payment_info.get("err_description", ""),
            )

            return JsonResponse({"result": "OK"}, status=status.HTTP_200_OK)

        except Exception:
            logger.exception("Unexpected webhook error")
            return JsonResponse({"detail": "Webhook handling error"}, status=status.HTTP_400_BAD_REQUEST)


class PaymentListView(generics.ListAPIView):
    serializer_class = PaymentSerializer  # pyrefly: ignore[bad-override]
    permission_classes = [HasAPIKey]  # pyrefly: ignore[bad-override]

    def get_queryset(self):  # pyrefly: ignore[bad-override]
        qs = PaymentRepository.base_qs()
        return PaymentRepository.filter(
            qs,
            status=self.request.GET.get("status"),
            order_id=self.request.GET.get("order_id"),
        )


class PaymentDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = PaymentSerializer  # pyrefly: ignore[bad-override]
    permission_classes = [HasAPIKey]  # pyrefly: ignore[bad-override]

    def get_queryset(self):  # pyrefly: ignore[bad-override]
        return PaymentRepository.base_qs()

    def perform_update(self, serializer: serializers.BaseSerializer) -> None:  # pyrefly: ignore[bad-override]
        instance: Payment = serializer.save()
        cache.delete(f"payment:{instance.id}")  # type: ignore[attr-defined]


class PaymentCreateView(generics.CreateAPIView):
    serializer_class = PaymentSerializer  # pyrefly: ignore[bad-override]
    permission_classes = [HasAPIKey]  # pyrefly: ignore[bad-override]

    def get_queryset(self):  # pyrefly: ignore[bad-override]
        return PaymentRepository.base_qs()

    def perform_create(self, serializer: serializers.BaseSerializer) -> None:  # pyrefly: ignore[bad-override]
        payment: Payment = serializer.save()
        logger.debug(f"Payment id={payment.id} created")  # type: ignore[attr-defined]
