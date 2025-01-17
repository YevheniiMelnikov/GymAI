import os
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.db import transaction
from django.contrib.auth.models import User
from django.core.mail import EmailMultiAlternatives, send_mail

from rest_framework import status
from rest_framework.views import APIView
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.request import Request
from rest_framework_api_key.permissions import HasAPIKey

from .models import Profile, ClientProfile, CoachProfile
from .serializers import (
    ProfileSerializer,
    CoachProfileSerializer,
    ClientProfileSerializer,
)


class IsAuthenticatedButAllowInactive(BasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated


class CreateUserView(APIView):
    permission_classes = [HasAPIKey | IsAuthenticated]

    async def post(self, request: Request) -> Response:
        username = request.data.get("username")
        password = request.data.get("password")
        email = request.data.get("email")
        user_status = request.data.get("status")
        language = request.data.get("language")
        tg_id = request.data.get("current_tg_id")

        if not password or not username or not email:
            return Response({"error": "Required fields are missing"}, status=status.HTTP_400_BAD_REQUEST)

        if await User.objects.filter(email=email).aexists():
            return Response({"error": "This email already taken"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            async with transaction.atomic():
                user = await User.objects.acreate_user(username=username, password=password, email=email)
                profile = await Profile.objects.acreate(
                    user=user, status=user_status, language=language, current_tg_id=tg_id
                )

                if user_status == "client":
                    await ClientProfile.objects.acreate(profile=profile)
                elif user_status == "coach":
                    await CoachProfile.objects.acreate(profile=profile)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        user_data = {"id": user.id, "username": user.username, "email": user.email, "current_tg_id": tg_id}
        return Response(user_data, status=status.HTTP_201_CREATED)


class UserProfileView(APIView):
    permission_classes = [HasAPIKey | IsAuthenticated]

    async def get(self, request: Request, username) -> Response:
        try:
            user = await User.objects.aget(username=username)
        except User.DoesNotExist:
            return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)

        profile = getattr(user, "profile", None)
        if not profile:
            return Response({"error": "Profile not found"}, status=status.HTTP_404_NOT_FOUND)

        if hasattr(profile, "client_profile"):
            serializer = ClientProfileSerializer(profile.client_profile)
        elif hasattr(profile, "coach_profile"):
            serializer = CoachProfileSerializer(profile.coach_profile)
        else:
            return Response({"error": "Profile type not found"}, status=status.HTTP_404_NOT_FOUND)

        return Response(serializer.data)


class CurrentUserView(APIView):
    permission_classes = [HasAPIKey | IsAuthenticated]

    async def get(self, request):
        user = request.user
        profile = getattr(user, "profile", None)
        if not profile:
            return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)

        if hasattr(profile, "client_profile"):
            serializer = ProfileSerializer(profile.client_profile)
        elif hasattr(profile, "coach_profile"):
            serializer = ProfileSerializer(profile.coach_profile)
        else:
            return Response({"error": "Profile type not found"}, status=status.HTTP_404_NOT_FOUND)

        data = serializer.data
        return Response({"username": user.username, "email": user.email, "current_tg_id": data.get("current_tg_id")})


class ProfileByTelegramIDView(APIView):
    permission_classes = [HasAPIKey | IsAuthenticated]
    serializer_class = ProfileSerializer

    async def get(self, request: Request, telegram_id: int) -> Response:
        try:
            profile = await Profile.objects.aget(current_tg_id=telegram_id)
        except Profile.DoesNotExist:
            return Response({"error": "Profile not found"}, status=status.HTTP_404_NOT_FOUND)

        serializer = self.serializer_class(profile)
        return Response(serializer.data)


class ResetTelegramIDView(APIView):
    permission_classes = [HasAPIKey | IsAuthenticated]

    async def post(self, request: Request, profile_id: int) -> Response:
        try:
            profile = await Profile.objects.aget(id=profile_id)
            await Profile.objects.filter(user=profile.user).exclude(id=profile_id).aupdate(current_tg_id=None)
            profile.current_tg_id = request.data.get("telegram_id")
            await profile.asave()
            return Response({"status": "success"}, status=status.HTTP_200_OK)
        except Profile.DoesNotExist:
            return Response({"error": "Profile not found"}, status=status.HTTP_404_NOT_FOUND)


class SendFeedbackAPIView(APIView):
    permission_classes = [HasAPIKey | IsAuthenticated]

    async def post(self, request: Request, *args, **kwargs) -> Response:
        email = request.data.get("email")
        username = request.data.get("username")
        feedback = request.data.get("feedback")

        subject = f"New feedback from {username}"
        message = f"User {username} with email {email} sent the following feedback:\n\n{feedback}"

        try:
            send_mail(subject, message, os.getenv("EMAIL_HOST_USER"), [os.getenv("EMAIL_HOST_USER")])
        except Exception:
            return Response({"message": "Failed to send feedback"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({"message": "Feedback sent successfully"}, status=status.HTTP_200_OK)


class SendWelcomeEmailAPIView(APIView):
    permission_classes = [HasAPIKey | IsAuthenticated]

    async def post(self, request, *args, **kwargs):
        email = request.data.get("email")
        username = request.data.get("username")
        html_content = render_to_string("email/welcome_email.html", {"username": username})
        text_content = strip_tags(html_content)

        try:
            subject = "Вітаємо в AchieveTogether 👋"
            msg = EmailMultiAlternatives(subject, text_content, os.getenv("EMAIL_HOST_USER"), [email])
            msg.attach_alternative(html_content, "text/html")
            msg.send()
        except Exception:
            return Response({"message": "Failed to send welcome email"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({"message": "Welcome email sent successfully"}, status=status.HTTP_200_OK)
