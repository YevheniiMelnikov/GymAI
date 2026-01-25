from typing import Any, Optional, cast, List
import datetime

"""Repositories for workout plan models."""

# pyrefly: ignore-file
# ruff: noqa

from django.db.models import QuerySet
from django.core.cache import cache
from rest_framework.exceptions import NotFound

from apps.workout_plans.models import Program, Subscription, SubscriptionProgressSnapshot
from apps.workout_plans.progress_types import ProgressSnapshotPayload
from config.app_settings import settings


class ProgramRepository:
    """Provide cached access helpers for workout programs."""

    @staticmethod
    def _key(pk: int) -> str:
        return f"program:{pk}"

    @staticmethod
    def _list_key(profile_id: Optional[int] = None) -> str:
        return f"program:list:{profile_id or 'all'}"

    @staticmethod
    def base_qs() -> QuerySet[Program]:  # pyrefly: ignore[bad-specialization]
        return Program.objects.all().select_related("profile")  # type: ignore[return-value,missing-attribute]

    @staticmethod
    def filter_by_profile(
        qs: QuerySet[Program],  # pyrefly: ignore[bad-specialization]
        profile_id: Optional[int],
    ) -> QuerySet[Program]:  # pyrefly: ignore[bad-specialization]
        if profile_id:
            key = ProgramRepository._list_key(profile_id)
            ids = cast(
                List[int],
                cache.get_or_set(
                    key,
                    lambda: list(qs.filter(profile_id=profile_id).values_list("id", flat=True)),
                    settings.CACHE_TTL,
                ),
            )
            return cast(QuerySet[Program], Program.objects.filter(id__in=ids))  # pyrefly: ignore[bad-specialization]

        key = ProgramRepository._list_key()
        ids = cast(
            List[int],
            cache.get_or_set(
                key,
                lambda: list(qs.values_list("id", flat=True)),
                settings.CACHE_TTL,
            ),
        )
        return cast(QuerySet[Program], Program.objects.filter(id__in=ids))  # pyrefly: ignore[bad-specialization]

    @staticmethod
    def create_or_update(profile_id: int, exercises: Any, instance: Optional[Program] = None) -> Program:
        program: Program

        if instance:
            instance.exercises_by_day = exercises  # type: ignore[attr-defined]
            instance.save()  # type: ignore[attr-defined]
            program = cast(Program, instance)
        else:
            program = cast(Program, Program.objects.create(profile_id=profile_id, exercises_by_day=exercises))

        cache.delete_many(
            [
                ProgramRepository._key(program.id),  # type: ignore[attr-defined]
                ProgramRepository._list_key(),
                ProgramRepository._list_key(profile_id),
            ]
        )
        return program

    @staticmethod
    def get_latest(profile_id: int) -> Program | None:
        return ProgramRepository.base_qs().filter(profile_id=profile_id).order_by("-created_at").first()

    @staticmethod
    def get_all(profile_id: int) -> list[Program]:
        return list(ProgramRepository.base_qs().filter(profile_id=profile_id).order_by("-created_at"))

    @staticmethod
    def get_by_id(profile_id: int, program_id: int) -> Program | None:
        return ProgramRepository.base_qs().filter(profile_id=profile_id, id=program_id).first()


class SubscriptionRepository:
    """Provide query helpers for workout subscriptions."""

    @staticmethod
    def base_qs() -> QuerySet[Subscription]:  # pyrefly: ignore[bad-specialization]
        return Subscription.objects.all().select_related("profile")  # type: ignore[return-value,missing-attribute]

    @staticmethod
    def filter_by_profile(
        qs: QuerySet[Subscription],  # pyrefly: ignore[bad-specialization]
        profile_id: Optional[int],
    ) -> QuerySet[Subscription]:  # pyrefly: ignore[bad-specialization]
        if profile_id:
            return qs.filter(profile_id=profile_id)
        return qs

    @staticmethod
    def get_latest(profile_id: int) -> Subscription | None:
        return SubscriptionRepository.base_qs().filter(profile_id=profile_id).order_by("-updated_at").first()

    @staticmethod
    def get_by_id(profile_id: int, subscription_id: int) -> Subscription | None:
        return SubscriptionRepository.base_qs().filter(profile_id=profile_id, id=subscription_id).first()

    @staticmethod
    def get_all(profile_id: int) -> list[Subscription]:
        return list(SubscriptionRepository.base_qs().filter(profile_id=profile_id).order_by("-updated_at"))

    @staticmethod
    def update_exercises(profile_id: int, exercises: Any, instance: Subscription) -> Subscription:
        Subscription.objects.filter(id=instance.id, profile_id=profile_id).update(exercises=exercises)
        instance.exercises = exercises  # type: ignore[attr-defined]
        return cast(Subscription, instance)


class SubscriptionProgressSnapshotRepository:
    """Persist weekly subscription progress snapshots."""

    @staticmethod
    def upsert_week_snapshot(
        *,
        profile_id: int,
        subscription_id: int,
        week_start: datetime.date,
        payload: ProgressSnapshotPayload,
    ) -> SubscriptionProgressSnapshot:
        snapshot, _ = SubscriptionProgressSnapshot.objects.update_or_create(
            subscription_id=subscription_id,
            week_start=week_start,
            defaults={
                "profile_id": profile_id,
                "payload": payload,
            },
        )
        return snapshot

    @staticmethod
    def get_recent_payloads(subscription_id: int, limit: int) -> list[ProgressSnapshotPayload]:
        snapshots = (
            SubscriptionProgressSnapshot.objects.filter(subscription_id=subscription_id)
            .order_by("-week_start")
            .values_list("payload", flat=True)[:limit]
        )
        return cast(list[ProgressSnapshotPayload], list(snapshots))

    @staticmethod
    def trim_old(subscription_id: int, keep_weeks: int) -> int:
        if keep_weeks <= 0:
            deleted, _ = SubscriptionProgressSnapshot.objects.filter(subscription_id=subscription_id).delete()
            return deleted
        ids = list(
            SubscriptionProgressSnapshot.objects.filter(subscription_id=subscription_id)
            .order_by("-week_start")
            .values_list("id", flat=True)[keep_weeks:]
        )
        if not ids:
            return 0
        deleted, _ = SubscriptionProgressSnapshot.objects.filter(id__in=ids).delete()
        return deleted
