import os

from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.db import transaction
from django.shortcuts import get_object_or_404, render
from rest_framework import generics
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import (
    BasePermission,
    IsAdminUser,
    IsAuthenticated,
    IsAuthenticatedOrReadOnly,
)
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.status import (
    HTTP_200_OK,
    HTTP_201_CREATED,
    HTTP_204_NO_CONTENT,
    HTTP_400_BAD_REQUEST,
    HTTP_404_NOT_FOUND,
    HTTP_500_INTERNAL_SERVER_ERROR,
)
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet
from rest_framework_api_key.permissions import HasAPIKey

from .models import Profile, Program, Subscription
from .serializers import ProfileSerializer, ProgramSerializer, SubscriptionSerializer


class CreateUserView(APIView):
    permission_classes = [HasAPIKey | IsAuthenticated]

    def post(self, request: Request) -> Response:
        username = request.data.get("username")
        password = request.data.get("password")
        email = request.data.get("email")
        status = request.data.get("status")
        language = request.data.get("language")
        tg_id = request.data.get("current_tg_id")

        if not password or not username or not email:
            return Response({"error": "Required fields are missing"}, status=HTTP_400_BAD_REQUEST)

        if User.objects.filter(email=email).exists():
            return Response({"error": "This email already taken"}, status=HTTP_400_BAD_REQUEST)

        try:
            with transaction.atomic():
                user = User.objects.create_user(username=username, password=password, email=email)
                profile_data = {"status": status, "language": language, "current_tg_id": tg_id}
                Profile.objects.create(user=user, **profile_data)
        except Exception as e:
            return Response({"error": str(e)}, status=HTTP_400_BAD_REQUEST)

        user_data = {"id": user.id, "username": user.username, "email": user.email, "current_tg_id": tg_id}
        return Response(user_data, status=HTTP_201_CREATED)


class UserProfileView(APIView):
    permission_classes = [HasAPIKey | IsAuthenticated]
    serializer_class = ProfileSerializer

    def get(self, request: Request, username) -> Response:
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            return Response({"error": "User not found"}, status=HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=HTTP_404_NOT_FOUND)

        profile = getattr(user, "profile", None)
        if profile:
            serializer = self.serializer_class(profile)
            return Response(serializer.data)
        else:
            return Response({"error": "Profile not found"}, status=HTTP_404_NOT_FOUND)


class CurrentUserView(APIView):
    permission_classes = [HasAPIKey | IsAuthenticated]

    def get(self, request):
        user = request.user
        profile = getattr(user, "profile", None)
        if profile:
            serializer = ProfileSerializer(profile)
            data = serializer.data
            return Response(
                {"username": user.username, "email": user.email, "current_tg_id": data.get("current_tg_id")}
            )
        else:
            return Response({"error": "User not found"}, status=HTTP_404_NOT_FOUND)


class SendFeedbackAPIView(APIView):
    permission_classes = [HasAPIKey | IsAuthenticated]

    def post(self, request: Request, *args, **kwargs) -> Response:
        email = request.data.get("email")
        username = request.data.get("username")
        feedback = request.data.get("feedback")

        subject = f"New Feedback from {username}"
        message = f"User {username} with email {email} sent the following feedback:\n\n{feedback}"

        try:
            send_mail(subject, message, os.getenv("EMAIL_HOST_USER"), [os.getenv("EMAIL_HOST_USER")])
        except Exception:
            return Response({"message": "Failed to send feedback"}, status=HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({"message": "Feedback sent successfully"}, status=HTTP_200_OK)


class IsAuthenticatedButAllowInactive(BasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated


class ProfileAPIUpdate(APIView):
    serializer_class = ProfileSerializer
    permission_classes = [HasAPIKey | IsAuthenticatedButAllowInactive]

    def get_object(self) -> Profile:
        profile_id = self.kwargs.get("profile_id")
        return get_object_or_404(Profile, pk=profile_id)

    def get(self, request: Request, profile_id: int, format=None) -> Response:
        profile = self.get_object()
        serializer = ProfileSerializer(profile)
        return Response(serializer.data)

    def put(self, request: Request, profile_id: int, format=None) -> Response:
        profile = self.get_object()
        serializer = ProfileSerializer(profile, data=request.data, context={"request": request})
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=HTTP_400_BAD_REQUEST)


def reset_password_request_view(request, uidb64: str, token: str) -> render:
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


class ProgramViewSet(ModelViewSet):
    queryset = Program.objects.all().select_related("profile")
    serializer_class = ProgramSerializer
    permission_classes = [HasAPIKey]

    def get_queryset(self):
        queryset = super().get_queryset().select_related("profile")
        profile = self.request.query_params.get("profile")
        exercises = self.request.query_params.getlist("exercises")

        if profile is not None:
            queryset = queryset.filter(profile_id=profile)
        if exercises:
            queryset = queryset.filter(exercises__overlap=exercises)

        return queryset

    def perform_create_or_update(self, serializer, profile_id, exercises):
        api_key = self.request.headers.get("Authorization")
        if not api_key or not HasAPIKey().has_permission(self.request, self):
            raise PermissionDenied("API Key must be provided")

        existing_program = Program.objects.filter(profile_id=profile_id).first()
        if existing_program:
            existing_program.exercises = exercises
            existing_program.save()
            return existing_program
        else:
            return serializer.save(profile_id=profile_id)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        profile_id = request.data.get("profile")
        exercises = request.data.get("exercises")

        if not profile_id:
            raise PermissionDenied("Profile ID must be provided.")

        instance = self.perform_create_or_update(serializer, profile_id, exercises)
        headers = self.get_success_headers(serializer.data)
        return Response(ProgramSerializer(instance).data, status=HTTP_201_CREATED, headers=headers)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        profile_id = request.data.get("profile")
        exercises = request.data.get("exercises")

        self.perform_create_or_update(serializer, profile_id, exercises)
        return Response(serializer.data)

    @action(detail=False, methods=["delete"], url_path="delete_by_profile/(?P<profile_id>[^/.]+)")
    def delete_by_profile(self, request, profile_id=None):
        program = Program.objects.filter(profile_id=profile_id).first()
        if program:
            program.delete()
            return Response(status=HTTP_204_NO_CONTENT)
        return Response(status=HTTP_404_NOT_FOUND)


class SubscriptionViewSet(ModelViewSet):
    queryset = Subscription.objects.all().select_related("user")
    serializer_class = SubscriptionSerializer
    permission_classes = [IsAuthenticated | HasAPIKey]

    def get_queryset(self):
        queryset = super().get_queryset().select_related("user")
        user = self.request.query_params.get("user")

        if user is not None:
            queryset = queryset.filter(user_id=user)

        return queryset

    @action(detail=False, methods=["delete"], url_path="delete_by_user/(?P<user_id>[^/.]+)")
    def delete_by_user(self, request, user_id=None):
        subscriptions = Subscription.objects.filter(user_id=user_id)
        if subscriptions.exists():
            subscriptions.delete()
            return Response(status=HTTP_204_NO_CONTENT)
        return Response(status=HTTP_404_NOT_FOUND)
