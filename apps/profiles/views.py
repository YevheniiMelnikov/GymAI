from django.shortcuts import get_object_or_404

from rest_framework import generics, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.exceptions import ValidationError
from rest_framework_api_key.permissions import HasAPIKey
from loguru import logger

from .models import Profile, ClientProfile, CoachProfile
from .serializers import ProfileSerializer, CoachProfileSerializer, ClientProfileSerializer


class ProfileByTelegramIDView(APIView):
    permission_classes = [HasAPIKey]
    serializer_class = ProfileSerializer

    def get(self, request: Request, telegram_id: int) -> Response:
        try:
            profile = Profile.objects.get(tg_id=telegram_id)
            return Response(self.serializer_class(profile).data, status=status.HTTP_200_OK)
        except Profile.DoesNotExist:
            logger.info(f"Profile not found for tg_id={telegram_id}")
            return Response({"error": "Profile not found"}, status=status.HTTP_404_NOT_FOUND)


class ProfileAPIUpdate(APIView):
    serializer_class = ProfileSerializer
    permission_classes = [HasAPIKey]

    def get_object(self):
        profile_id = self.kwargs["profile_id"]
        return get_object_or_404(Profile, pk=profile_id)

    def get(self, request: Request, profile_id: int) -> Response:
        profile = self.get_object()
        return Response(self.serializer_class(profile).data)

    def put(self, request: Request, profile_id: int) -> Response:
        logger.debug(f"PUT Profile id={profile_id}")
        profile = self.get_object()
        serializer = self.serializer_class(profile, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            logger.info(f"Profile id={profile_id} updated")
            return Response(serializer.data)
        logger.error(f"Validation error for Profile id={profile_id}: {serializer.errors}")
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ProfileAPIDestroy(generics.RetrieveDestroyAPIView):
    serializer_class = ProfileSerializer
    queryset = Profile.objects.all()  # type: ignore[assignment]
    permission_classes = [HasAPIKey]


class ProfileAPIList(generics.ListCreateAPIView):
    serializer_class = ProfileSerializer
    queryset = Profile.objects.all()  # type: ignore[assignment]
    permission_classes = [HasAPIKey]


class CoachProfileList(generics.ListAPIView):
    queryset = CoachProfile.objects.all()  # type: ignore[assignment]
    serializer_class = CoachProfileSerializer
    permission_classes = [HasAPIKey]


class ClientProfileList(generics.ListAPIView):
    queryset = ClientProfile.objects.all()  # type: ignore[assignment]
    serializer_class = ClientProfileSerializer
    permission_classes = [HasAPIKey]


class CoachProfileUpdate(generics.RetrieveUpdateAPIView):
    serializer_class = CoachProfileSerializer
    permission_classes = [HasAPIKey]

    def get_object(self):
        if "pk" in self.kwargs:
            coach_profile = get_object_or_404(CoachProfile, pk=self.kwargs["pk"])
            if coach_profile.profile.status != "coach":
                raise ValidationError("Underlying profile status is not 'coach'")
            return coach_profile

        profile_id = self.kwargs["profile_id"]
        profile = get_object_or_404(Profile, id=profile_id)
        if profile.status != "coach":
            raise ValidationError("Profile status is not 'coach'")
        coach_profile, _ = CoachProfile.objects.get_or_create(profile=profile)
        return coach_profile


class ClientProfileUpdate(generics.RetrieveUpdateAPIView):
    serializer_class = ClientProfileSerializer
    permission_classes = [HasAPIKey]

    def get_object(self):
        if "pk" in self.kwargs:
            client_profile = get_object_or_404(ClientProfile, pk=self.kwargs["pk"])
            if client_profile.profile.status != "client":
                raise ValidationError("Underlying profile status is not 'client'")
            return client_profile

        profile_id = self.kwargs["profile_id"]
        profile = get_object_or_404(Profile, id=profile_id)
        if profile.status != "client":
            raise ValidationError("Profile status is not 'client'")
        client_profile, _ = ClientProfile.objects.get_or_create(profile=profile)
        return client_profile


class CoachProfileByProfile(APIView):
    permission_classes = [HasAPIKey]
    serializer_class = CoachProfileSerializer

    def get(self, request: Request, profile_id: int) -> Response:
        coach_profile = get_object_or_404(CoachProfile, profile_id=profile_id)
        return Response(self.serializer_class(coach_profile).data, status=status.HTTP_200_OK)


class ClientProfileByProfile(APIView):
    permission_classes = [HasAPIKey]
    serializer_class = ClientProfileSerializer

    def get(self, request: Request, profile_id: int) -> Response:
        client_profile = get_object_or_404(ClientProfile, profile_id=profile_id)
        return Response(self.serializer_class(client_profile).data, status=status.HTTP_200_OK)
