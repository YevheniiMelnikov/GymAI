import os

from django.contrib.auth.models import User
from django.core.mail import EmailMultiAlternatives, send_mail
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.utils.html import strip_tags

from rest_framework import generics, status
from rest_framework.authtoken.models import Token
from rest_framework.generics import ListAPIView, RetrieveUpdateAPIView
from rest_framework.permissions import BasePermission, IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_api_key.permissions import HasAPIKey

from .models import Profile, ClientProfile, CoachProfile
from .serializers import (
    ProfileSerializer,
    CoachProfileSerializer,
    ClientProfileSerializer,
)

# @csrf_exempt
# @require_POST
# def create_api_key_view(request):
#     api_key, key = APIKey.objects.create_key(name="my-key")
#     return JsonResponse({"api_key": key})

class IsAuthenticatedButAllowInactive(BasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated


class CreateUserView(APIView):
    permission_classes = [HasAPIKey | IsAuthenticated]

    def post(self, request: Request) -> Response:
        username = request.data.get("username")
        password = request.data.get("password")
        email = request.data.get("email")
        user_status = request.data.get("status")
        language = request.data.get("language")
        tg_id = request.data.get("current_tg_id")

        if not password or not username or not email:
            return Response({"error": "Required fields are missing"}, status=status.HTTP_400_BAD_REQUEST)

        if User.objects.filter(email=email).exists():
            return Response({"error": "This email already taken"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            with transaction.atomic():
                user = User.objects.create_user(username=username, password=password, email=email)
                profile = Profile.objects.create(user=user, status=user_status, language=language, current_tg_id=tg_id)

                if user_status == "client":
                    ClientProfile.objects.create(profile=profile)
                elif user_status == "coach":
                    CoachProfile.objects.create(profile=profile)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        user_data = {"id": user.id, "username": user.username, "email": user.email, "current_tg_id": tg_id}
        return Response(user_data, status=status.HTTP_201_CREATED)


class UserProfileView(APIView):
    permission_classes = [HasAPIKey | IsAuthenticated]

    def get(self, request: Request, username) -> Response:
        try:
            user = User.objects.get(username=username)
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

    def get(self, request):
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

    def get(self, request: Request, telegram_id: int) -> Response:
        try:
            profile = Profile.objects.get(current_tg_id=telegram_id)
        except Profile.DoesNotExist:
            return Response({"error": "Profile not found"}, status=status.HTTP_404_NOT_FOUND)

        serializer = self.serializer_class(profile)
        return Response(serializer.data)


class ResetTelegramIDView(APIView):
    permission_classes = [HasAPIKey | IsAuthenticated]

    def post(self, request: Request, profile_id: int) -> Response:
        try:
            profile = get_object_or_404(Profile, id=profile_id)
            Profile.objects.filter(user=profile.user).exclude(id=profile_id).update(current_tg_id=None)
            profile.current_tg_id = request.data.get("telegram_id")
            profile.save()
            return Response({"status": "success"}, status=status.HTTP_200_OK)
        except Profile.DoesNotExist:
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
        profile = self.get_object()
        serializer = ProfileSerializer(profile, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


def reset_password_request_view(request, uidb64: str, token: str) -> HttpResponse:
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
        obj = CoachProfile.objects.get(profile_id=self.kwargs.get("profile_id"))
        self.check_object_permissions(self.request, obj)
        return obj


class ClientProfileView(ListAPIView):
    queryset = ClientProfile.objects.all()
    serializer_class = ClientProfileSerializer
    permission_classes = [IsAuthenticatedOrReadOnly | HasAPIKey]


class ClientProfileUpdate(RetrieveUpdateAPIView):
    queryset = ClientProfile.objects.all()
    serializer_class = ClientProfileSerializer
    permission_classes = [IsAuthenticated | HasAPIKey]

    def get_object(self):
        obj = ClientProfile.objects.get(profile_id=self.kwargs.get("profile_id"))
        self.check_object_permissions(self.request, obj)
        return obj


class GetUserTokenView(APIView):
    permission_classes = [HasAPIKey]

    def post(self, request, *args, **kwargs):
        profile_id = request.data.get("profile_id")
        if not profile_id:
            return Response({"error": "Profile ID is required"}, status=400)

        try:
            profile = Profile.objects.get(id=profile_id)
            user = profile.user
            token, created = Token.objects.get_or_create(user=user)
            return Response({"profile_id": profile_id, "username": user.username, "auth_token": token.key})
        except Profile.DoesNotExist:
            return Response({"error": "Profile not found"}, status=404)


class SendFeedbackAPIView(APIView):
    permission_classes = [HasAPIKey | IsAuthenticated]

    def post(self, request: Request, *args, **kwargs) -> Response:
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

    def post(self, request, *args, **kwargs):
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
