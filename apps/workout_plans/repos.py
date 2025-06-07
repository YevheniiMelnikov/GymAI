from __future__ import annotations

from typing import Any, Optional, cast
from django.db.models import QuerySet
from django.core.cache import cache
from rest_framework.exceptions import NotFound

from apps.profiles.models import ClientProfile
from apps.workout_plans.models import Program, Subscription
from config.env_settings import Settings


class ProgramRepository:
    @staticmethod
    def _key(pk: int) -> str:
        return f"program:{pk}"

    @staticmethod
    def _list_key(client_id: Optional[int] = None) -> str:
        return f"programs:list:{client_id or 'all'}"

    @staticmethod
    def base_qs() -> QuerySet[Program]:
        return Program.objects.all().select_related("client_profile")  # type: ignore[return-value]

    @staticmethod
    def filter_by_client(qs: QuerySet[Program], client_id: Optional[int]) -> QuerySet[Program]:
        if client_id:
            key = ProgramRepository._list_key(client_id)
            result = cache.get_or_set(key, lambda: qs.filter(client_profile_id=client_id), Settings.CACHE_TTL)
            return cast(QuerySet[Program], result)
        key = ProgramRepository._list_key()
        result = cache.get_or_set(key, lambda: qs, Settings.CACHE_TTL)
        return cast(QuerySet[Program], result)

    @staticmethod
    def get_client(client_id: int) -> ClientProfile:
        try:
            client = ClientProfile.objects.get(pk=client_id)
            return cast(ClientProfile, client)
        except ClientProfile.DoesNotExist:
            raise NotFound(f"ClientProfile pk={client_id} not found")

    @classmethod
    def create_or_update(
        cls, client_profile: ClientProfile, exercises: Any, instance: Optional[Program] = None
    ) -> Program:
        program: Program

        if instance:
            instance.exercises_by_day = exercises  # type: ignore[attr-defined]
            instance.save()  # type: ignore[attr-defined]
            program = cast(Program, instance)
        else:
            existing = Program.objects.filter(client_profile=client_profile).first()
            if existing:
                existing.exercises_by_day = exercises  # type: ignore[attr-defined]
                existing.save()  # type: ignore[attr-defined]
                program = cast(Program, existing)
            else:
                program = cast(
                    Program, Program.objects.create(client_profile=client_profile, exercises_by_day=exercises)
                )

        cache.delete_many(
            [
                cls._key(program.id),  # type: ignore[attr-defined]
                cls._list_key(),
                cls._list_key(client_profile.id),  # type: ignore[attr-defined]
            ]
        )
        return program


class SubscriptionRepository:
    @staticmethod
    def base_qs() -> QuerySet[Subscription]:
        return Subscription.objects.all().select_related("client_profile")  # type: ignore[return-value]

    @staticmethod
    def filter_by_client(qs: QuerySet[Subscription], client_id: Optional[int]) -> QuerySet[Subscription]:
        if client_id:
            return qs.filter(client_profile_id=client_id)
        return qs
