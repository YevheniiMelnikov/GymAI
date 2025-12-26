from typing import Any, Optional

from django.core.cache import cache
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status, serializers
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet
from rest_framework_api_key.permissions import HasAPIKey

from apps.workout_plans.serializers import ProgramSerializer, SubscriptionSerializer
from apps.workout_plans.repos import ProgramRepository, SubscriptionRepository
from apps.workout_plans.models import Subscription


def _parse_profile_id(profile_id_str: Optional[str]) -> Optional[int]:
    if profile_id_str is None:
        return None
    try:
        return int(profile_id_str)
    except (ValueError, TypeError):
        return None


class ProgramViewSet(ModelViewSet):
    queryset = ProgramRepository.base_qs()  # type: ignore[assignment]
    serializer_class = ProgramSerializer  # pyrefly: ignore[bad-override]
    permission_classes = [HasAPIKey]  # pyrefly: ignore[bad-override]

    def get_queryset(self):  # pyrefly: ignore[bad-override]
        qs = ProgramRepository.base_qs()
        profile_id_str = self.request.query_params.get("profile")
        profile_id = _parse_profile_id(profile_id_str)
        return ProgramRepository.filter_by_profile(qs, profile_id)

    def create(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        profile_raw = request.data.get("profile")
        exercises = request.data.get("exercises_by_day")
        if not profile_raw:
            return Response({"error": "profile is required"}, status=status.HTTP_400_BAD_REQUEST)

        profile_id = int(profile_raw)
        program = ProgramRepository.create_or_update(profile_id, exercises)

        cache.delete_many(
            [
                "program:list",
                f"program:list:{profile_id}",
                f"program:{program.id}",  # type: ignore[attr-defined]
            ]
        )

        status_code = (
            status.HTTP_201_CREATED
            if getattr(program, "created_at", None) == getattr(program, "updated_at", None)
            else status.HTTP_200_OK
        )
        return Response(ProgramSerializer(program).data, status=status_code)

    def update(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        profile_raw = request.data.get("profile") or instance.profile_id
        profile_id = int(profile_raw)
        exercises = serializer.validated_data.get("exercises_by_day", instance.exercises_by_day)
        program = ProgramRepository.create_or_update(profile_id, exercises, instance=instance)

        cache.delete_many(
            [
                "program:list",
                f"program:list:{profile_id}",
                f"program:{program.id}",  # type: ignore[attr-defined]
            ]
        )
        return Response(self.get_serializer(program).data, status=status.HTTP_200_OK)


class SubscriptionViewSet(ModelViewSet):
    queryset = SubscriptionRepository.base_qs()  # type: ignore[assignment]
    serializer_class = SubscriptionSerializer  # pyrefly: ignore[bad-override]
    permission_classes = [HasAPIKey]  # pyrefly: ignore[bad-override]
    filter_backends = [DjangoFilterBackend]  # type: ignore[assignment]
    filterset_fields = ["enabled", "payment_date"]

    def get_queryset(self):  # pyrefly: ignore[bad-override]
        qs = SubscriptionRepository.base_qs()
        profile_id_str = self.request.query_params.get("profile")
        profile_id = _parse_profile_id(profile_id_str)
        return SubscriptionRepository.filter_by_profile(qs, profile_id)

    def perform_create(self, serializer: serializers.BaseSerializer) -> None:  # pyrefly: ignore[bad-override]
        sub = serializer.save()
        cache.delete_many(
            [
                "subscriptions:list",
                f"subscriptions:list:profile:{sub.profile_id}",  # pyrefly: ignore[missing-attribute]
            ]
        )

    def perform_update(self, serializer: serializers.BaseSerializer) -> None:  # pyrefly: ignore[bad-override]
        sub = serializer.save()
        cache.delete_many(
            [
                "subscriptions:list",
                f"subscriptions:list:profile:{sub.profile_id}",  # pyrefly: ignore[missing-attribute]
            ]
        )

    def perform_destroy(self, instance: Subscription) -> None:  # pyrefly: ignore[bad-override]
        profile_id = instance.profile_id  # pyrefly: ignore[missing-attribute]
        super().perform_destroy(instance)
        cache.delete_many(
            [
                "subscriptions:list",
                f"subscriptions:list:profile:{profile_id}",
            ]
        )
