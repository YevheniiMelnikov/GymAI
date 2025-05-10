from django_filters.rest_framework import DjangoFilterBackend
from loguru import logger
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, NotFound
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet
from rest_framework_api_key.permissions import HasAPIKey

from apps.profiles.models import ClientProfile
from apps.workout_plans.models import Program, Subscription
from apps.workout_plans.serializers import ProgramSerializer, SubscriptionSerializer


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


class SubscriptionViewSet(ModelViewSet):
    queryset = Subscription.objects.all().select_related("client_profile")
    serializer_class = SubscriptionSerializer
    permission_classes = [HasAPIKey]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["enabled", "payment_date"]

    def get_queryset(self):
        queryset = super().get_queryset().select_related("client_profile")
        client_profile_id = self.request.query_params.get("client_profile")

        if client_profile_id is not None:
            queryset = queryset.filter(client_profile_id=client_profile_id)

        return queryset
