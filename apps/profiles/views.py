from loguru import logger
from rest_framework import generics, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_api_key.permissions import HasAPIKey

from apps.profiles.serializers import ProfileSerializer
from apps.profiles.repos import ProfileRepository


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


class ProfileAPIList(generics.ListCreateAPIView):
    serializer_class = ProfileSerializer  # pyrefly: ignore[bad-override]
    queryset = ProfileRepository  # type: ignore[assignment]
    permission_classes = [HasAPIKey]  # pyrefly: ignore[bad-override]
