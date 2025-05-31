from typing import Sequence, Type, cast, Any

from django_filters.rest_framework import DjangoFilterBackend
from loguru import logger
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.filters import BaseFilterBackend
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet
from rest_framework_api_key.permissions import HasAPIKey

from apps.profiles.models import ClientProfile
from apps.workout_plans.models import Program, Subscription
from apps.workout_plans.serializers import ProgramSerializer, SubscriptionSerializer


class ProgramViewSet(ModelViewSet):
    queryset = Program.objects.all().select_related("client_profile")  # type: ignore[assignment]
    serializer_class = ProgramSerializer
    permission_classes = [HasAPIKey]

    def _filter_by_client(self, qs: Any) -> Any:
        client_id = self.request.query_params.get("client_profile")
        if client_id:
            logger.debug(f"Filtering Program queryset by client_profile_id={client_id}")
            qs = qs.filter(client_profile_id=client_id)
        return qs

    def get_queryset(self) -> Any:
        base_qs = super().get_queryset().select_related("client_profile")
        return self._filter_by_client(base_qs)

    @staticmethod
    def _get_client(client_id: int) -> ClientProfile:
        logger.debug(f"Fetching ClientProfile pk={client_id}")
        try:
            return ClientProfile.objects.get(pk=client_id)  # type: ignore[return-value]
        except ClientProfile.DoesNotExist:
            logger.error(f"ClientProfile pk={client_id} not found")
            raise NotFound(f"ClientProfile pk={client_id} not found")

    def _create_or_update(self, client_id: int, exercises: Any, instance: Program | None = None) -> Program:
        client = self._get_client(client_id)

        if instance:
            logger.info(f"Updating Program id={getattr(instance, 'id', None)} for client_profile pk={client_id}")
            instance.exercises_by_day = exercises
            instance.save()
            return instance

        existing = Program.objects.filter(client_profile=client).first()
        if existing:  # type: ignore[truthy-function]
            logger.info(
                f"Patching existing Program id={getattr(existing, 'id', None)} for client_profile pk={client_id}"
            )
            existing = cast(Program, existing)
            existing.exercises_by_day = exercises
            existing.save()
            return existing

        logger.info(f"Creating Program for client_profile pk={client_id}")
        return Program.objects.create(  # type: ignore[return-value]
            client_profile=client, exercises_by_day=exercises
        )

    def create(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        client_id = request.data.get("client_profile")
        exercises = request.data.get("exercises_by_day")

        if not client_id:
            logger.error("client_profile is required in request data")
            return Response({"error": "client_profile is required"}, status=status.HTTP_400_BAD_REQUEST)

        program = self._create_or_update(int(client_id), exercises)
        status_code = (
            status.HTTP_201_CREATED
            if getattr(program, "created_at", None) == getattr(program, "updated_at", None)
            else status.HTTP_200_OK
        )
        logger.info(f"Program id={getattr(program, 'id', None)} processed (status_code={status_code})")
        return Response(ProgramSerializer(program).data, status=status_code)

    def update(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        partial = kwargs.pop("partial", False)
        instance: Program = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        client_id_raw = request.data.get("client_profile") or getattr(instance, "client_profile_id", None)
        if client_id_raw is None:
            logger.error("client_profile is required")
            return Response({"error": "client_profile is required"}, status=status.HTTP_400_BAD_REQUEST)

        exercises = serializer.validated_data.get("exercises_by_day", instance.exercises_by_day)

        program = self._create_or_update(int(client_id_raw), exercises, instance=instance)
        logger.info(f"Program id={getattr(program, 'id', None)} updated")
        return Response(self.get_serializer(program).data, status=status.HTTP_200_OK)


class SubscriptionViewSet(ModelViewSet):
    queryset = Subscription.objects.all().select_related("client_profile")  # type: ignore[assignment]
    serializer_class = SubscriptionSerializer
    permission_classes = [HasAPIKey]
    filter_backends: Sequence[Type[BaseFilterBackend]] = [DjangoFilterBackend]  # type: ignore[assignment]
    filterset_fields = ["enabled", "payment_date"]

    def get_queryset(self) -> Any:
        qs = super().get_queryset().select_related("client_profile")
        client_id = self.request.query_params.get("client_profile")
        if client_id:
            qs = qs.filter(client_profile_id=client_id)
        return qs
