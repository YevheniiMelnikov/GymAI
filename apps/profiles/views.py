from loguru import logger
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_api_key.permissions import HasAPIKey

from apps.profiles.models import Profile
from apps.profiles.choices import ProfileStatus
from apps.profiles.serializers import ProfileSerializer
from apps.profiles.repos import ProfileRepository
from apps.metrics.utils import record_event
from core.metrics.constants import METRICS_EVENT_NEW_USER, METRICS_SOURCE_PROFILE


class ProfileByTelegramIDView(APIView):
    permission_classes = [HasAPIKey]  # pyrefly: ignore[bad-override]
    serializer_class = ProfileSerializer

    def get(self, request: Request, tg_id: int) -> Response:
        profile = ProfileRepository.get_by_telegram_id(tg_id)
        return Response(self.serializer_class(profile).data, status=status.HTTP_200_OK)


class ProfileAPIUpdate(APIView):
    serializer_class = ProfileSerializer
    permission_classes = [HasAPIKey]  # pyrefly: ignore[bad-override]

    def get(self, request: Request, profile_id: int) -> Response:
        profile = ProfileRepository.get_by_id(profile_id)
        return Response(self.serializer_class(profile).data)

    def put(self, request: Request, profile_id: int) -> Response:
        logger.debug(f"PUT Profile id={profile_id}")
        profile = ProfileRepository.get_model_by_id(profile_id)
        serializer = self.serializer_class(profile, data=request.data, partial=True)
        if serializer.is_valid():
            saved_profile = serializer.save()
            ProfileRepository.invalidate_cache(
                profile_id=saved_profile.id,
                tg_id=getattr(saved_profile, "tg_id", None),
            )
            logger.info(f"Profile id={profile_id} updated")
            try:
                from core.tasks.ai_coach.maintenance import sync_profile_knowledge

                getattr(sync_profile_knowledge, "delay")(saved_profile.id, reason="profile_updated")
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"Failed to enqueue profile sync profile_id={profile_id}: {exc}")
            return Response(serializer.data)
        logger.error(f"Validation error for Profile id={profile_id}: {serializer.errors}")
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ProfileAPIDestroy(generics.RetrieveDestroyAPIView):
    serializer_class = ProfileSerializer  # pyrefly: ignore[bad-override]
    queryset = ProfileRepository.get_by_id  # type: ignore[assignment]
    permission_classes = [HasAPIKey]  # pyrefly: ignore[bad-override]

    def get_object(self):
        profile_id = self.kwargs.get("pk")
        return ProfileRepository.get_model_by_id(profile_id)

    def perform_destroy(self, instance: Profile) -> None:
        tg_id = getattr(instance, "tg_id", None)
        profile_id = getattr(instance, "pk", None)
        instance.status = ProfileStatus.deleted
        instance.deleted_at = timezone.now()
        instance.gift_credits_granted = True
        instance.gender = None
        instance.born_in = None
        instance.weight = None
        instance.height = None
        instance.health_notes = None
        instance.workout_experience = None
        instance.workout_goals = None
        instance.workout_location = None
        instance.save(
            update_fields=[
                "status",
                "deleted_at",
                "gift_credits_granted",
                "gender",
                "born_in",
                "weight",
                "height",
                "health_notes",
                "workout_experience",
                "workout_goals",
                "workout_location",
            ]
        )
        ProfileRepository.invalidate_cache(profile_id=profile_id or 0, tg_id=tg_id)
        if profile_id is not None:
            try:
                from core.tasks.ai_coach.maintenance import cleanup_profile_knowledge

                getattr(cleanup_profile_knowledge, "delay")(profile_id, reason="profile_deleted")
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"Failed to enqueue profile cleanup profile_id={profile_id}: {exc}")


class ProfileAPIList(generics.ListCreateAPIView):
    serializer_class = ProfileSerializer  # pyrefly: ignore[bad-override]
    queryset = ProfileRepository  # type: ignore[assignment]
    permission_classes = [HasAPIKey]  # pyrefly: ignore[bad-override]

    def create(self, request: Request, *args, **kwargs) -> Response:  # pyrefly: ignore[bad-override]
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tg_id = serializer.validated_data.get("tg_id")
        language = serializer.validated_data.get("language")
        if tg_id is not None:
            existing = Profile.objects.filter(tg_id=tg_id).first()  # pyrefly: ignore[missing-attribute]
        else:
            existing = None
        if existing is not None:
            restored = False
            if existing.status == ProfileStatus.deleted:
                existing.status = ProfileStatus.created
                existing.deleted_at = None
                if language:
                    existing.language = language
                existing.save(update_fields=["status", "deleted_at", "language"])
                restored = True
            ProfileRepository.invalidate_cache(profile_id=existing.id, tg_id=tg_id)
            if restored:
                self._enqueue_profile_init(existing.id, reason="profile_restored")
            response_data = self.get_serializer(existing).data
            return Response(response_data, status=status.HTTP_201_CREATED)
        profile = serializer.save()
        ProfileRepository.invalidate_cache(profile_id=profile.id, tg_id=getattr(profile, "tg_id", None))
        record_event(METRICS_EVENT_NEW_USER, METRICS_SOURCE_PROFILE, str(profile.id))
        self._enqueue_profile_init(profile.id, reason="profile_created")
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    @staticmethod
    def _enqueue_profile_init(profile_id: int, *, reason: str) -> None:
        try:
            from core.tasks.ai_coach.maintenance import sync_profile_knowledge

            getattr(sync_profile_knowledge, "delay")(profile_id, reason=reason)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Failed to enqueue profile sync profile_id={profile_id}: {exc}")
        try:
            from ai_coach.agent.knowledge.utils.memify_scheduler import schedule_profile_memify_sync

            schedule_profile_memify_sync(profile_id, reason=reason)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Failed to schedule memify profile_id={profile_id}: {exc}")
