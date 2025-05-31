import base64
import json
from typing import Any

from loguru import logger
from django.http import JsonResponse
from liqpay import LiqPay
from rest_framework import generics
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView
from rest_framework_api_key.permissions import HasAPIKey

from apps.payments.models import Payment
from apps.payments.serializers import PaymentSerializer
from apps.payments.tasks import process_payment_webhook

from config.env_settings import Settings


class PaymentWebhookView(APIView):
    permission_classes = [AllowAny]

    @staticmethod
    def _verify_signature(raw_data: str, signature: str) -> bool:
        lp = LiqPay(Settings.PAYMENT_PUB_KEY, Settings.PAYMENT_PRIVATE_KEY)
        expected = lp.str_to_sign(f"{Settings.PAYMENT_PRIVATE_KEY}{raw_data}{Settings.PAYMENT_PRIVATE_KEY}")
        return signature == expected

    @staticmethod
    def post(request, *args, **kwargs):
        try:
            raw_data: str | None = request.POST.get("data")
            signature: str | None = request.POST.get("signature")

            if not raw_data or not signature:
                return JsonResponse({"detail": "Missing fields"}, status=400)

            if not PaymentWebhookView._verify_signature(raw_data, signature):
                return JsonResponse({"detail": "Invalid signature"}, status=400)

            payment_info: dict[str, Any] = json.loads(base64.b64decode(raw_data).decode())

            process_payment_webhook.delay(
                order_id=payment_info.get("order_id"),
                status=payment_info.get("status"),
                err_description=payment_info.get("err_description", ""),
            )

            return JsonResponse({"result": "OK"}, status=200)

        except Exception as exc:
            logger.exception("Webhook processing error")
            return JsonResponse({"detail": str(exc)}, status=400)


class PaymentListView(generics.ListAPIView):
    queryset = Payment.objects.all()  # type: ignore[attr-defined]
    serializer_class = PaymentSerializer
    permission_classes = [HasAPIKey]

    def get_queryset(self):
        qs = super().get_queryset()
        status_param = self.request.GET.get("status")
        if status_param:
            qs = qs.filter(status=status_param)

        order_id = self.request.GET.get("order_id")
        if order_id:
            qs = qs.filter(order_id=order_id)

        return qs


class PaymentDetailView(generics.RetrieveUpdateAPIView):
    queryset = Payment.objects.all()  # type: ignore[attr-defined]
    serializer_class = PaymentSerializer
    permission_classes = [HasAPIKey]

    def patch(self, request, *args, **kwargs):
        kwargs["partial"] = True
        logger.debug("Patch request received for PaymentDetailView")
        return self.update(request, *args, **kwargs)

    def put(self, request, *args, **kwargs):
        kwargs["partial"] = True
        logger.debug("Put request received for PaymentDetailView")
        return self.update(request, *args, **kwargs)


class PaymentCreateView(generics.CreateAPIView):
    queryset = Payment.objects.all()  # type: ignore[attr-defined]
    serializer_class = PaymentSerializer
    permission_classes = [HasAPIKey]
