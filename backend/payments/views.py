from xml.etree import ElementTree as ET

from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status, generics
from rest_framework.exceptions import PermissionDenied, NotFound
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet
from rest_framework_api_key.permissions import HasAPIKey

from payments.models import Program, Subscription, Payment
from payments.serializers import ProgramSerializer, SubscriptionSerializer, PaymentSerializer


class ProgramViewSet(ModelViewSet):
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
            raise PermissionDenied("API Key must be provided")

        existing_program = Program.objects.filter(client_profile_id=client_profile_id).first()
        if existing_program:
            existing_program.exercises_by_day = exercises
            existing_program.save()
            return existing_program
        else:
            return serializer.save(client_profile_id=client_profile_id, exercises_by_day=exercises)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        client_profile_id = request.data.get("client_profile")
        exercises = request.data.get("exercises_by_day")

        if not client_profile_id:
            raise PermissionDenied("Client profile ID must be provided.")

        instance = self.perform_create_or_update(serializer, client_profile_id, exercises)
        headers = self.get_success_headers(serializer.data)
        return Response(ProgramSerializer(instance).data, status=status.HTTP_201_CREATED, headers=headers)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        profile_id = request.data.get("profile")
        exercises = request.data.get("exercises_by_day")

        self.perform_create_or_update(serializer, profile_id, exercises)
        return Response(serializer.data)


class SubscriptionViewSet(ModelViewSet):
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
        if request.content_type == "application/json":
            return self.handle_json(request)
        elif request.content_type == "application/xml" or request.content_type == "text/xml":
            return self.handle_xml(request)
        else:
            return Response({"detail": "Unsupported content type"}, status=status.HTTP_400_BAD_REQUEST)

    def handle_json(self, request):
        try:
            data = request.data

            if "shopBillId" not in data or "status" not in data or "shopOrderNumber" not in data:
                return Response({"detail": "Missing required fields."}, status=status.HTTP_400_BAD_REQUEST)

            bill_id = data.get("shopBillId")
            order_number = data.get("shopOrderNumber")
            payment_status = data.get("status")
            error_message = data.get("errorMessage", "")

            self.process_payment(order_number, bill_id, payment_status, error_message)

            if payment_status == "PAYED":
                return Response({"result": "OK"}, status=status.HTTP_200_OK)
            else:
                return Response({"result": "FAILURE"}, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({"detail": f"Invalid webhook data: {e}"}, status=status.HTTP_400_BAD_REQUEST)

    def handle_xml(self, request):
        try:
            xml_data = request.body.decode("utf-8")
            root = ET.fromstring(xml_data)

            bill_id = root.findtext("shopBillId")
            order_number = root.findtext("shopOrderNumber")
            payment_status = root.findtext("status")
            error_message = root.findtext("errorMessage", "")

            if not bill_id or not order_number or not payment_status:
                return Response({"detail": "Missing required fields in XML."}, status=status.HTTP_400_BAD_REQUEST)

            self.process_payment(order_number, bill_id, payment_status, error_message)

            if payment_status == "PAYED":
                return Response({"result": "OK"}, status=status.HTTP_200_OK)
            else:
                return Response({"result": "FAILURE"}, status=status.HTTP_200_OK)

        except ET.ParseError as e:
            return Response({"detail": f"Invalid XML data: {e}"}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"detail": f"Error processing payment: {e}"}, status=status.HTTP_400_BAD_REQUEST)

    @staticmethod
    def process_payment(order_number: str, bill_id: str, payment_status: str, error_message: str = "") -> None:
        try:
            payment = get_object_or_404(Payment, shop_order_number=order_number)
            payment.shop_bill_id = bill_id
            payment.status = payment_status
            payment.error = error_message
            payment.handled = False
            payment.save()

        except Payment.DoesNotExist:
            raise NotFound(detail="Payment not found", code=status.HTTP_404_NOT_FOUND)


class PaymentListView(generics.ListAPIView):
    queryset = Payment.objects.all()
    serializer_class = PaymentSerializer
    permission_classes = [IsAuthenticated | HasAPIKey]

    def get_queryset(self):
        queryset = super().get_queryset()
        status = self.request.query_params.get("status", None)
        if status:
            queryset = queryset.filter(status=status)
        return queryset


class PaymentDetailView(generics.RetrieveUpdateAPIView):
    queryset = Payment.objects.all()
    serializer_class = PaymentSerializer
    permission_classes = [IsAuthenticated | HasAPIKey]

    def patch(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def put(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)


class PaymentCreateView(generics.CreateAPIView):
    queryset = Payment.objects.all()
    serializer_class = PaymentSerializer
    permission_classes = [IsAuthenticated | HasAPIKey]
