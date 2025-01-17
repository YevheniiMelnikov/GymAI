import base64
import json
import os

from django.http import JsonResponse
from django_filters.rest_framework import DjangoFilterBackend
from liqpay import LiqPay
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, NotFound
from rest_framework.generics import CreateAPIView, RetrieveUpdateAPIView, ListAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet
from rest_framework_api_key.permissions import HasAPIKey

from models import Program, Payment
from serializers import ProgramSerializer

from accounts.models import ClientProfile

from backend.payments.models import Subscription
from backend.payments.serializers import PaymentSerializer, SubscriptionSerializer


class ProgramViewSet(ModelViewSet):
    queryset = Program.objects.all().select_related("client_profile")
    serializer_class = ProgramSerializer
    permission_classes = [HasAPIKey]

    async def get_queryset(self):
        queryset = await super().get_queryset().select_related("client_profile")
        client_profile_id = self.request.query_params.get("client_profile")

        if client_profile_id is not None:
            queryset = queryset.filter(client_profile_id=client_profile_id)

        return queryset

    async def perform_create_or_update(self, serializer, client_profile_id, exercises):
        api_key = self.request.headers.get("Authorization")
        if not api_key or not HasAPIKey().has_permission(self.request, self):
            raise PermissionDenied("API Key must be provided")

        try:
            client_profile = await ClientProfile.objects.aget(profile__id=client_profile_id)
        except ClientProfile.DoesNotExist:
            raise NotFound(f"ClientProfile with profile_id {client_profile_id} does not exist.")

        existing_program = await Program.objects.filter(client_profile=client_profile).afirst()
        if existing_program:
            existing_program.exercises_by_day = exercises
            await existing_program.asave()
            return existing_program
        else:
            return await serializer.save(client_profile=client_profile, exercises_by_day=exercises)

    async def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        client_profile_id = request.data.get("client_profile")
        exercises = request.data.get("exercises_by_day")

        if not client_profile_id:
            raise PermissionDenied("Client profile ID must be provided.")

        instance = await self.perform_create_or_update(serializer, client_profile_id, exercises)
        headers = self.get_success_headers(serializer.data)
        return Response(ProgramSerializer(instance).data, status=status.HTTP_201_CREATED, headers=headers)

    async def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        profile_id = request.data.get("profile")
        exercises = request.data.get("exercises_by_day")

        await self.perform_create_or_update(serializer, profile_id, exercises)
        return Response(serializer.data)


class PaymentWebhookView(APIView):
    permission_classes = [AllowAny]

    async def post(self, request, *args, **kwargs):
        try:
            data = request.POST.get("data")
            signature = request.POST.get("signature")

            if not data or not signature:
                return JsonResponse({"detail": "Missing data or signature."}, status=status.HTTP_400_BAD_REQUEST)

            liqpay_client = LiqPay(os.getenv("PAYMENT_PUB_KEY"), os.getenv("PAYMENT_PRIVATE_KEY"))
            sign = liqpay_client.str_to_sign(os.getenv("PAYMENT_PRIVATE_KEY") + data + os.getenv("PAYMENT_PRIVATE_KEY"))
            if sign != signature:
                return JsonResponse({"detail": "Invalid signature"}, status=status.HTTP_400_BAD_REQUEST)

            decoded_data = base64.b64decode(data).decode("utf-8")
            payment_info = json.loads(decoded_data)
            order_id = payment_info.get("order_id")
            payment_status = payment_info.get("status")
            error_message = payment_info.get("err_description", "")
            await self.process_payment(order_id, payment_status, error_message)

            if payment_status == "success":
                return JsonResponse({"result": "OK"}, status=status.HTTP_200_OK)
            else:
                return JsonResponse({"result": "FAILURE"}, status=status.HTTP_200_OK)

        except Exception as e:
            return JsonResponse({"detail": f"Error processing payment: {e}"}, status=status.HTTP_400_BAD_REQUEST)

    @staticmethod
    async def process_payment(order_id: str, payment_status: str, error_message: str = "") -> None:
        try:
            payment = await Payment.objects.aget(order_id=order_id)
            payment.status = payment_status
            payment.error = error_message
            payment.handled = False
            await payment.asave()

        except Payment.DoesNotExist:
            raise NotFound(detail=f"Payment {order_id} not found", code=status.HTTP_404_NOT_FOUND)


class SubscriptionViewSet(ModelViewSet):
    queryset = Subscription.objects.all().select_related("client_profile")
    serializer_class = SubscriptionSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["enabled", "payment_date"]

    async def get_queryset(self):
        queryset = await super().get_queryset().select_related("client_profile")
        client_profile_id = self.request.query_params.get("client_profile")

        if client_profile_id is not None:
            queryset = queryset.filter(client_profile_id=client_profile_id)

        return queryset


class PaymentCreateView(CreateAPIView):
    queryset = Payment.objects.all()
    serializer_class = PaymentSerializer
    permission_classes = [IsAuthenticated]

    async def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        await serializer.asave()
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class PaymentListView(ListAPIView):
    queryset = Payment.objects.all()
    serializer_class = PaymentSerializer
    permission_classes = [IsAuthenticated]

    async def get_queryset(self):
        queryset = await super().get_queryset()
        status_filter = self.request.query_params.get("status", None)
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        return queryset


class PaymentDetailView(RetrieveUpdateAPIView):
    queryset = Payment.objects.all()
    serializer_class = PaymentSerializer
    permission_classes = [IsAuthenticated]

    async def patch(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return await self.update(request, *args, **kwargs)

    async def put(self, request, *args, **kwargs):
        kwargs["partial"] = False
        return await self.update(request, *args, **kwargs)
