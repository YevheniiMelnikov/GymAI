from typing import Any, cast

from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from loguru import logger
from rest_framework import generics, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_api_key.permissions import HasAPIKey

from apps.profiles.models import ClientProfile, CoachProfile
from apps.profiles.serializers import (
    ProfileSerializer,
    CoachProfileSerializer,
    ClientProfileSerializer,
)
from apps.profiles.repos import (
    ProfileRepository,
    CoachProfileRepository,
    ClientProfileRepository,
)


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
            serializer.save()
            logger.info(f"Profile id={profile_id} updated")
            return Response(serializer.data)
        logger.error(f"Validation error for Profile id={profile_id}: {serializer.errors}")
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ProfileAPIDestroy(generics.RetrieveDestroyAPIView):
    serializer_class = ProfileSerializer  # pyrefly: ignore[bad-override]
    queryset = ProfileRepository.get_by_id  # type: ignore[assignment]
    permission_classes = [HasAPIKey]  # pyrefly: ignore[bad-override]


@method_decorator(cache_page(60), name="dispatch")
class ProfileAPIList(generics.ListCreateAPIView):
    serializer_class = ProfileSerializer  # pyrefly: ignore[bad-override]
    queryset = ProfileRepository  # type: ignore[assignment]
    permission_classes = [HasAPIKey]  # pyrefly: ignore[bad-override]


@method_decorator(cache_page(60), name="dispatch")
class CoachProfileList(generics.ListCreateAPIView):
    serializer_class = CoachProfileSerializer  # pyrefly: ignore[bad-override]
    permission_classes = [HasAPIKey]  # pyrefly: ignore[bad-override]

    def get_queryset(self):
        return CoachProfile.objects.all()  # pyrefly: ignore[missing-attribute]

    def perform_create(self, serializer: CoachProfileSerializer) -> None:  # type: ignore[override]
        raw_id: Any = self.request.data.get("profile")
        profile_id: int = cast(int, raw_id)
        profile = ProfileRepository.get_model_by_id(profile_id)
        if profile.role != "coach":
            raise ValueError("Profile role must be 'coach'")
        serializer.save(profile=profile)


@method_decorator(cache_page(60), name="dispatch")
class ClientProfileList(generics.ListCreateAPIView):
    serializer_class = ClientProfileSerializer  # pyrefly: ignore[bad-override]
    permission_classes = [HasAPIKey]  # pyrefly: ignore[bad-override]

    def get_queryset(self):
        return ClientProfile.objects.all()  # pyrefly: ignore[missing-attribute]

    def perform_create(self, serializer: ClientProfileSerializer) -> None:  # type: ignore[override]
        raw_id: Any = self.request.data.get("profile")
        profile_id: int = cast(int, raw_id)
        profile = ProfileRepository.get_model_by_id(profile_id)
        if profile.role != "client":
            raise ValueError("Profile role must be 'client'")
        serializer.save(profile=profile)


class CoachProfileUpdate(generics.RetrieveUpdateAPIView):
    serializer_class = CoachProfileSerializer  # pyrefly: ignore[bad-override]
    permission_classes = [HasAPIKey]  # pyrefly: ignore[bad-override]

    def get_object(self):
        if "pk" in self.kwargs:
            return CoachProfileRepository.get(self.kwargs["pk"])
        profile = ProfileRepository.get_model_by_id(self.kwargs["profile_id"])
        return CoachProfileRepository.get_or_create_by_profile(profile)


class ClientProfileUpdate(generics.RetrieveUpdateAPIView):
    serializer_class = ClientProfileSerializer  # pyrefly: ignore[bad-override]
    permission_classes = [HasAPIKey]  # pyrefly: ignore[bad-override]

    def get_object(self):
        if "pk" in self.kwargs:
            return ClientProfileRepository.get(self.kwargs["pk"])
        profile = ProfileRepository.get_model_by_id(self.kwargs["profile_id"])
        return ClientProfileRepository.get_or_create_by_profile(profile)


class CoachProfileByProfile(APIView):
    permission_classes = [HasAPIKey]  # pyrefly: ignore[bad-override]
    serializer_class = CoachProfileSerializer

    def get(self, request: Request, profile_id: int) -> Response:
        coach_profile = CoachProfileRepository.get_or_create_by_profile(ProfileRepository.get_model_by_id(profile_id))
        return Response(self.serializer_class(coach_profile).data, status=status.HTTP_200_OK)


class ClientProfileByProfile(APIView):
    permission_classes = [HasAPIKey]  # pyrefly: ignore[bad-override]
    serializer_class = ClientProfileSerializer

    def get(self, request: Request, profile_id: int) -> Response:
        client_profile = ClientProfileRepository.get_or_create_by_profile(ProfileRepository.get_model_by_id(profile_id))
        return Response(self.serializer_class(client_profile).data, status=status.HTTP_200_OK)
