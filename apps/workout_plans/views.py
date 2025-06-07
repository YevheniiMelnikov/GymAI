from __future__ import annotations

from typing import Any

from django.core.cache import cache
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet
from rest_framework_api_key.permissions import HasAPIKey

from apps.workout_plans.serializers import ProgramSerializer, SubscriptionSerializer
from apps.workout_plans.repos import ProgramRepository, SubscriptionRepository


@method_decorator(cache_page(60 * 5), name="list")
class ProgramViewSet(ModelViewSet):
    queryset = ProgramRepository.base_qs()  # type: ignore[assignment]
    serializer_class = ProgramSerializer
    permission_classes = [HasAPIKey]

    def get_queryset(self):
        qs = ProgramRepository.base_qs()
        client_id = self.request.query_params.get("client_profile")
        return ProgramRepository.filter_by_client(qs, client_id)

    def create(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        client_id_raw = request.data.get("client_profile")
        exercises = request.data.get("exercises_by_day")
        if not client_id_raw:
            return Response({"error": "client_profile is required"}, status=status.HTTP_400_BAD_REQUEST)

        client = ProgramRepository.get_client(int(client_id_raw))
        program = ProgramRepository.create_or_update(client, exercises)

        cache.delete_many(
            [
                "programs:list",
                f"programs:list:client:{client.id}",  # type: ignore[attr-defined]
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

        client_id_raw = request.data.get("client_profile") or instance.client_profile_id
        client = ProgramRepository.get_client(int(client_id_raw))
        exercises = serializer.validated_data.get("exercises_by_day", instance.exercises_by_day)
        program = ProgramRepository.create_or_update(client, exercises, instance=instance)

        cache.delete_many(
            [
                "programs:list",
                f"programs:list:client:{client.id}",  # type: ignore[attr-defined]
                f"program:{program.id}",  # type: ignore[attr-defined]
            ]
        )
        return Response(self.get_serializer(program).data, status=status.HTTP_200_OK)


@method_decorator(cache_page(60 * 5), name="list")
class SubscriptionViewSet(ModelViewSet):
    queryset = SubscriptionRepository.base_qs()  # type: ignore[assignment]
    serializer_class = SubscriptionSerializer
    permission_classes = [HasAPIKey]
    filter_backends = [DjangoFilterBackend]  # type: ignore[assignment]
    filterset_fields = ["enabled", "payment_date"]

    def get_queryset(self):
        qs = SubscriptionRepository.base_qs()
        client_id = self.request.query_params.get("client_profile")
        return SubscriptionRepository.filter_by_client(qs, client_id)

    def perform_create(self, serializer):
        sub = serializer.save()
        cache.delete_many(
            [
                "subscriptions:list",
                f"subscriptions:list:client:{sub.client_profile_id}",
            ]
        )

    def perform_update(self, serializer):
        sub = serializer.save()
        cache.delete_many(
            [
                "subscriptions:list",
                f"subscriptions:list:client:{sub.client_profile_id}",
            ]
        )

    def perform_destroy(self, instance):
        client_id = instance.client_profile_id
        super().perform_destroy(instance)
        cache.delete_many(
            [
                "subscriptions:list",
                f"subscriptions:list:client:{client_id}",
            ]
        )
