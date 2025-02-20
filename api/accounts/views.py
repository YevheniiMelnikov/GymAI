from django.contrib.auth.models import User
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from djoser.views import TokenDestroyView

from rest_framework import generics, status
from rest_framework.authtoken.models import Token
from rest_framework.generics import ListAPIView, RetrieveUpdateAPIView
from rest_framework.permissions import BasePermission, IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_api_key.permissions import HasAPIKey

from common.constants import WELCOME_MAIL_SUBJECT
from common.settings import settings
from .models import Profile, ClientProfile, CoachProfile
from .serializers import (
    ProfileSerializer,
    CoachProfileSerializer,
    ClientProfileSerializer,
)

import loguru

logger = loguru.logger


class IsAuthenticatedButAllowInactive(BasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated


class CreateUserView(APIView):
    permission_classes = [HasAPIKey | IsAuthenticated]

    def post(self, request: Request) -> Response:
        username = request.data.get("username")
        password = request.data.get("password")
        email = request.data.get("email")
        user_status = request.data.get("status", "client")
        language = request.data.get("language", "ru")
        tg_id = request.data.get("current_tg_id")

        if not all([password, username, email]):
            logger.error("Missing required fields during user creation.")
            return Response({"error": "Required fields are missing"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            with transaction.atomic():
                user = User.objects.create_user(username=username, email=email, password=password, is_active=True)
                profile = Profile.objects.create(user=user, status=user_status, language=language, current_tg_id=tg_id)

                if user_status == "client":
                    ClientProfile.objects.create(profile=profile)
                    logger.info(f"ClientProfile created for user: {username}")
                elif user_status == "coach":
                    CoachProfile.objects.create(profile=profile)
                    logger.info(f"CoachProfile created for user: {username}")

                Token.objects.create(user=user)

        except Exception as e:
            logger.exception("Error occured during user creation.")
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {"id": user.id, "username": user.username, "email": user.email, "auth_token": user.auth_token.key},
            status=status.HTTP_201_CREATED,
        )


class UserProfileView(APIView):
    permission_classes = [HasAPIKey | IsAuthenticated]

    def get(self, request: Request, username) -> Response:
        user = get_object_or_404(User, username=username)
        profile, _ = Profile.objects.get_or_create(user=user)

        if profile.status == "client":
            client_profile, _ = ClientProfile.objects.get_or_create(profile=profile)
            serializer = ClientProfileSerializer(client_profile)
        elif profile.status == "coach":
            coach_profile, _ = CoachProfile.objects.get_or_create(profile=profile)
            serializer = CoachProfileSerializer(coach_profile)
        else:
            logger.error(f"Unknown profile type for user: {username}")
            return Response({"error": "Unknown profile type"}, status=status.HTTP_400_BAD_REQUEST)

        return Response(serializer.data)


class CurrentUserView(APIView):
    permission_classes = [HasAPIKey | IsAuthenticated]

    def get(self, request):
        user = request.user
        profile, created = Profile.objects.get_or_create(user=user)

        if profile.status not in ["client", "coach"]:
            return Response({"error": "Unknown profile type"}, status=status.HTTP_400_BAD_REQUEST)

        if profile.status == "client":
            client_profile, _ = ClientProfile.objects.get_or_create(profile=profile)
            profile_data = ClientProfileSerializer(client_profile).data
        else:
            coach_profile, _ = CoachProfile.objects.get_or_create(profile=profile)
            profile_data = CoachProfileSerializer(coach_profile).data

        return Response(
            {
                "username": user.username,
                "email": user.email,
                "status": profile.status,
                "current_tg_id": profile.current_tg_id,
                "profile_data": profile_data,
            },
            status=status.HTTP_200_OK,
        )


class ProfileByTelegramIDView(APIView):
    permission_classes = [HasAPIKey | IsAuthenticated]
    serializer_class = ProfileSerializer

    def get(self, request: Request, telegram_id: int) -> Response:
        try:
            profile = Profile.objects.get(current_tg_id=telegram_id)
            serializer = self.serializer_class(profile)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Profile.DoesNotExist:
            logger.info(f"Profile not found for tg user: {telegram_id}")
            return Response({"error": "Profile not found"}, status=status.HTTP_404_NOT_FOUND)


class ResetTelegramIDView(APIView):
    permission_classes = [HasAPIKey | IsAuthenticated]

    def post(self, request: Request, profile_id: int) -> Response:
        logger.debug(f"Resetting Telegram ID for profile_id: {profile_id}")
        try:
            profile = get_object_or_404(Profile, id=profile_id)
            Profile.objects.filter(user=profile.user).exclude(id=profile_id).update(current_tg_id=None)
            profile.current_tg_id = request.data.get("telegram_id")
            profile.save()
            logger.info(f"Telegram ID reset for profile_id: {profile_id}")
            return Response({"status": "success"}, status=status.HTTP_200_OK)
        except Profile.DoesNotExist:
            logger.error(f"Profile not found for profile_id: {profile_id} during Telegram ID reset")
            return Response({"error": "Profile not found"}, status=status.HTTP_404_NOT_FOUND)


class ProfileAPIUpdate(APIView):
    serializer_class = ProfileSerializer
    permission_classes = [HasAPIKey | IsAuthenticatedButAllowInactive]

    def get_object(self) -> Profile:
        profile_id = self.kwargs.get("profile_id")
        obj = get_object_or_404(Profile, pk=profile_id)
        self.check_object_permissions(self.request, obj)
        return obj

    def get(self, request: Request, profile_id: int, format=None) -> Response:
        profile = self.get_object()
        serializer = ProfileSerializer(profile)
        return Response(serializer.data)

    def put(self, request: Request, profile_id: int, format=None) -> Response:
        logger.debug(f"PUT request for ProfileAPIUpdate with profile_id: {profile_id}")
        profile = self.get_object()
        serializer = ProfileSerializer(profile, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            logger.info(f"Profile with id: {profile_id} updated successfully")
            return Response(serializer.data)
        logger.error(f"Error updating Profile with id: {profile_id}: {serializer.errors}")
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


def reset_password_request_view(request, uidb64: str, token: str) -> HttpResponse:
    logger.debug(f"Rendering reset-password view for uid: {uidb64}")
    return render(request, "reset-password.html", {"uid": uidb64, "token": token})


class ProfileAPIDestroy(generics.RetrieveDestroyAPIView):
    serializer_class = ProfileSerializer
    queryset = Profile.objects.all()
    permission_classes = [IsAuthenticated | HasAPIKey]
    lookup_field = "id"


class ProfileAPIList(generics.ListCreateAPIView):
    serializer_class = ProfileSerializer
    queryset = Profile.objects.all()
    permission_classes = [IsAuthenticatedOrReadOnly | HasAPIKey]


class CoachProfileView(ListAPIView):
    queryset = CoachProfile.objects.all()
    serializer_class = CoachProfileSerializer
    permission_classes = [IsAuthenticatedOrReadOnly | HasAPIKey]


class CoachProfileUpdate(RetrieveUpdateAPIView):
    queryset = CoachProfile.objects.all()
    serializer_class = CoachProfileSerializer
    permission_classes = [IsAuthenticated | HasAPIKey]

    def get_object(self):
        profile_id = self.kwargs.get("profile_id")
        profile = get_object_or_404(Profile, id=profile_id)

        if profile.status != "coach":
            return Response({"error": "Profile status is not a coach"}, status=status.HTTP_400_BAD_REQUEST)

        coach_profile, _ = CoachProfile.objects.get_or_create(profile=profile)
        self.check_object_permissions(self.request, coach_profile)
        return coach_profile


class ClientProfileView(ListAPIView):
    queryset = ClientProfile.objects.all()
    serializer_class = ClientProfileSerializer
    permission_classes = [IsAuthenticatedOrReadOnly | HasAPIKey]


class ClientProfileUpdate(RetrieveUpdateAPIView):
    queryset = ClientProfile.objects.all()
    serializer_class = ClientProfileSerializer
    permission_classes = [IsAuthenticated | HasAPIKey]

    def get_object(self):
        profile_id = self.kwargs.get("profile_id")
        profile = get_object_or_404(Profile, id=profile_id)

        if profile.status != "client":
            return Response({"error": "Profile status is not a client"}, status=status.HTTP_400_BAD_REQUEST)

        client_profile, _ = ClientProfile.objects.get_or_create(profile=profile)
        self.check_object_permissions(self.request, client_profile)
        return client_profile


class GetUserTokenView(APIView):
    permission_classes = [HasAPIKey]

    def post(self, request, *args, **kwargs):
        profile_id = request.data.get("profile_id")
        profile = get_object_or_404(Profile, id=profile_id)

        token, _ = Token.objects.get_or_create(user=profile.user)

        return Response({"profile_id": profile_id, "username": profile.user.username, "auth_token": token.key})


class SendWelcomeEmailAPIView(APIView):
    permission_classes = [HasAPIKey | IsAuthenticated]

    def post(self, request, *args, **kwargs):
        email = request.data.get("email")
        username = request.data.get("username")
        html_content = render_to_string("email/welcome_email.html", {"username": username})
        text_content = strip_tags(html_content)

        try:
            msg = EmailMultiAlternatives(WELCOME_MAIL_SUBJECT, text_content, settings.EMAIL_HOST_USER, [email])
            msg.attach_alternative(html_content, "text/html")
            msg.send()
            logger.info(f"Welcome email sent to: {email}")
        except Exception:
            logger.exception(f"Failed to send welcome email to: {email}")
            return Response({"message": "Failed to send welcome email"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({"message": "Welcome email sent successfully"}, status=status.HTTP_200_OK)


class CustomTokenDestroyView(TokenDestroyView):
    def post(self, request, *args, **kwargs):
        logger.debug("CustomTokenDestroyView POST request received.")
        if request.user.is_authenticated:
            profiles = Profile.objects.filter(user=request.user, current_tg_id__isnull=False)
            for profile in profiles:
                logger.info(f"Resetting Telegram ID for user: {request.user.username} in profile id: {profile.id}")
                profile.current_tg_id = None
                profile.save()

        return super().post(request, *args, **kwargs)
