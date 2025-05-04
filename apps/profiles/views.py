from django.shortcuts import get_object_or_404

from rest_framework import generics, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
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
            serializer = self.serializer_class(profile)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Profile.DoesNotExist:
            logger.info(f"Profile not found for tg_id: {telegram_id}")
            return Response({"error": "Profile not found"}, status=status.HTTP_404_NOT_FOUND)


class ProfileAPIUpdate(APIView):
    serializer_class = ProfileSerializer
    permission_classes = [HasAPIKey]

    def get_object(self):
        profile_id = self.kwargs.get("profile_id")
        return get_object_or_404(Profile, pk=profile_id)

    def get(self, request: Request, profile_id: int) -> Response:
        profile = self.get_object()
        serializer = self.serializer_class(profile)
        return Response(serializer.data)

    def put(self, request: Request, profile_id: int) -> Response:
        logger.debug(f"PUT request for ProfileAPIUpdate with profile_id: {profile_id}")
        profile = self.get_object()
        serializer = self.serializer_class(profile, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            logger.info(f"Profile id={profile_id} updated successfully")
            return Response(serializer.data)
        logger.error(f"Error updating Profile id={profile_id}: {serializer.errors}")
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ProfileAPIDestroy(generics.RetrieveDestroyAPIView):
    serializer_class = ProfileSerializer
    queryset = Profile.objects.all()
    permission_classes = [HasAPIKey]
    lookup_field = "id"


class ProfileAPIList(generics.ListCreateAPIView):
    serializer_class = ProfileSerializer
    queryset = Profile.objects.all()
    permission_classes = [HasAPIKey]


class CoachProfileView(generics.ListAPIView):
    queryset = CoachProfile.objects.all()
    serializer_class = CoachProfileSerializer
    permission_classes = [HasAPIKey]


class CoachProfileUpdate(generics.RetrieveUpdateAPIView):
    queryset = CoachProfile.objects.all()
    serializer_class = CoachProfileSerializer
    permission_classes = [HasAPIKey]
    lookup_field = "id"

    def get_object(self):
        profile_id = self.kwargs.get("profile_id")
        profile = get_object_or_404(Profile, id=profile_id)

        if profile.status != "coach":
            return Response({"error": "Profile status is not 'coach'"}, status=status.HTTP_400_BAD_REQUEST)

        coach_profile, _ = CoachProfile.objects.get_or_create(profile=profile)
        return coach_profile


class ClientProfileView(generics.ListAPIView):
    queryset = ClientProfile.objects.all()
    serializer_class = ClientProfileSerializer
    permission_classes = [HasAPIKey]


class ClientProfileUpdate(generics.RetrieveUpdateAPIView):
    queryset = ClientProfile.objects.all()
    serializer_class = ClientProfileSerializer
    permission_classes = [HasAPIKey]
    lookup_field = "id"

    def get_object(self):
        profile_id = self.kwargs.get("profile_id")
        profile = get_object_or_404(Profile, id=profile_id)

        if profile.status != "client":
            return Response({"error": "Profile status is not 'client'"}, status=status.HTTP_400_BAD_REQUEST)

        client_profile, _ = ClientProfile.objects.get_or_create(profile=profile)
        return client_profile
