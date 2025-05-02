import base64
import json

from loguru import logger
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from liqpay import LiqPay
from rest_framework import status, generics
from rest_framework.exceptions import PermissionDenied, NotFound
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet
from rest_framework_api_key.permissions import HasAPIKey

from payments.models import Program, Subscription, Payment
from payments.serializers import ProgramSerializer, SubscriptionSerializer, PaymentSerializer

from accounts.models import ClientProfile

from common.settings import Settings


class ProgramViewSet(ModelViewSet):  # TODO: SEPARATE THIS
    queryset = Program.objects.all().select_related("client_profile")
    serializer_class = ProgramSerializer
    permission_classes = [HasAPIKey]

    def get_queryset(self):
        queryset = super().get_queryset().select_related("client_profile")
        client_profile_id = self.request.query_params.get("client_profile")

        if client_profile_id is not None:
            queryset = queryset.filter(client_profile_id=client_profile_id)

        return queryset

    def perform_create_or_update(self, serializer, client_profile_id, exercises):
        api_key = self.request.headers.get("Authorization")
        if not api_key or not HasAPIKey().has_permission(self.request, self):
            logger.error("API Key missing or invalid")
            raise PermissionDenied("API Key must be provided")

        logger.debug(f"Retrieving ClientProfile with profile_id: {client_profile_id}")
        try:
            client_profile = ClientProfile.objects.get(profile__id=client_profile_id)
        except ClientProfile.DoesNotExist:
            logger.error(f"ClientProfile with profile_id {client_profile_id} does not exist.")
            raise NotFound(f"ClientProfile with profile_id {client_profile_id} does not exist.")

        existing_program = Program.objects.filter(client_profile=client_profile).first()
        if existing_program:
            logger.info(f"Updating existing Program for client_profile_id: {client_profile_id}")
            existing_program.exercises_by_day = exercises
            existing_program.save()
            return existing_program
        else:
            logger.info(f"Creating new Program for client_profile_id: {client_profile_id}")
            return serializer.save(client_profile=client_profile, exercises_by_day=exercises)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        client_profile_id = request.data.get("client_profile")
        exercises = request.data.get("exercises_by_day")

        if not client_profile_id:
            logger.error("Client profile ID was not provided in request data.")
            raise PermissionDenied("Client profile ID must be provided.")

        instance = self.perform_create_or_update(serializer, client_profile_id, exercises)
        headers = self.get_success_headers(serializer.data)
        logger.info(f"Program created/updated successfully for client_profile_id: {client_profile_id}")
        return Response(ProgramSerializer(instance).data, status=status.HTTP_201_CREATED, headers=headers)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        profile_id = request.data.get("profile")
        exercises = request.data.get("exercises_by_day")

        self.perform_create_or_update(serializer, profile_id, exercises)
        logger.info(f"Program updated for profile_id: {profile_id}")
        return Response(serializer.data)


class SubscriptionViewSet(ModelViewSet):  # TODO: SEPARATE THIS
    queryset = Subscription.objects.all().select_related("client_profile")
    serializer_class = SubscriptionSerializer
    permission_classes = [IsAuthenticated | HasAPIKey]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["enabled", "payment_date"]

    def get_queryset(self):
        queryset = super().get_queryset().select_related("client_profile")
        client_profile_id = self.request.query_params.get("client_profile")

        if client_profile_id is not None:
            queryset = queryset.filter(client_profile_id=client_profile_id)

        return queryset


class PaymentWebhookView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        try:
            logger.debug("Received payment webhook request")
            data = request.POST.get("data")
            signature = request.POST.get("signature")

            if not data or not signature:
                logger.error("Missing data or signature in payment webhook request")
                return JsonResponse({"detail": "Missing data or signature."}, status=status.HTTP_400_BAD_REQUEST)

            liqpay_client = LiqPay(Settings.PAYMENT_PUB_KEY, Settings.PAYMENT_PRIVATE_KEY)
            sign = liqpay_client.str_to_sign(Settings.PAYMENT_PRIVATE_KEY + data + Settings.PAYMENT_PRIVATE_KEY)
            if sign != signature:
                logger.error("Invalid signature received in payment webhook")
                return JsonResponse({"detail": "Invalid signature"}, status=status.HTTP_400_BAD_REQUEST)

            decoded_data = base64.b64decode(data).decode("utf-8")
            payment_info = json.loads(decoded_data)
            order_id = payment_info.get("order_id")
            payment_status = payment_info.get("status")
            error_message = payment_info.get("err_description", "")

            logger.info(f"Processing payment with order_id: {order_id}, status: {payment_status}")
            self.process_payment(order_id, payment_status, error_message)

            if payment_status == "success":
                logger.info(f"Payment {order_id} processed successfully")
                return JsonResponse({"result": "OK"}, status=status.HTTP_200_OK)
            else:
                logger.warning(f"Payment {order_id} processed with failure status")
                return JsonResponse({"result": "FAILURE"}, status=status.HTTP_200_OK)

        except Exception as e:
            logger.exception("Error processing payment webhook")
            return JsonResponse({"detail": f"Error processing payment: {e}"}, status=status.HTTP_400_BAD_REQUEST)

    @staticmethod
    def process_payment(order_id: str, payment_status: str, error_message: str = "") -> None:
        try:
            logger.debug(f"Attempting to update Payment with order_id: {order_id}")
            payment = get_object_or_404(Payment, order_id=order_id)
            payment.status = payment_status
            payment.error = error_message
            payment.handled = False
            payment.save()
            logger.info(f"Payment {order_id} updated with status: {payment_status}")
        except Payment.DoesNotExist:
            logger.error(f"Payment with order_id {order_id} not found during processing")
            raise NotFound(detail=f"Payment {order_id} not found", code=status.HTTP_404_NOT_FOUND)


class PaymentListView(generics.ListAPIView):
    queryset = Payment.objects.all()
    serializer_class = PaymentSerializer
    permission_classes = [IsAuthenticated | HasAPIKey]

    def get_queryset(self):
        queryset = super().get_queryset()
        status_param = self.request.query_params.get("status", None)
        if status_param:
            logger.debug(f"Filtering payments with status: {status_param}")
            queryset = queryset.filter(status=status_param)
        return queryset


class PaymentDetailView(generics.RetrieveUpdateAPIView):
    queryset = Payment.objects.all()
    serializer_class = PaymentSerializer
    permission_classes = [IsAuthenticated | HasAPIKey]

    def patch(self, request, *args, **kwargs):
        kwargs["partial"] = True
        logger.debug("Patch request received for PaymentDetailView")
        return self.update(request, *args, **kwargs)

    def put(self, request, *args, **kwargs):
        kwargs["partial"] = True
        logger.debug("Put request received for PaymentDetailView")
        return self.update(request, *args, **kwargs)


class PaymentCreateView(generics.CreateAPIView):
    queryset = Payment.objects.all()
    serializer_class = PaymentSerializer
    permission_classes = [IsAuthenticated | HasAPIKey]
