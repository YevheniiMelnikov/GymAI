import os

from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.db import transaction
from django.shortcuts import get_object_or_404, render
from rest_framework import generics
from rest_framework.permissions import IsAdminUser, IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.status import (
    HTTP_200_OK,
    HTTP_201_CREATED,
    HTTP_400_BAD_REQUEST,
    HTTP_404_NOT_FOUND,
    HTTP_500_INTERNAL_SERVER_ERROR,
)
from rest_framework.views import APIView
from rest_framework_api_key.permissions import HasAPIKey

from .models import Profile
from .serializers import ProfileSerializer


class CreateUserView(APIView):
    permission_classes = [HasAPIKey | IsAuthenticated]

    def post(self, request: Request) -> Response:
        username = request.data.get("username")
        password = request.data.get("password")
        email = request.data.get("email")
        status = request.data.get("status")
        language = request.data.get("language")

        if not password or not username or not email:
            return Response({"error": "Required fields are missing"}, status=HTTP_400_BAD_REQUEST)

        try:
            with transaction.atomic():
                user = User.objects.create_user(username=username, password=password, email=email)

                profile_data = {}
                if status:
                    profile_data["status"] = status
                if language:
                    profile_data["language"] = language

                Profile.objects.create(user=user, **profile_data)
        except Exception as e:
            return Response({"error": str(e)}, status=HTTP_400_BAD_REQUEST)

        user_data = {
            "id": user.id,
            "username": user.username,
            "email": user.email,
        }
        return Response(user_data, status=HTTP_201_CREATED)


class UserProfileView(APIView):
    permission_classes = [HasAPIKey | IsAuthenticated]
    serializer_class = ProfileSerializer

    def get(self, request: Request, username) -> Response:
        try:
            user = User.objects.get(username=username)
        except Exception as e:
            return Response({"error": e}, status=HTTP_404_NOT_FOUND)

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
        return Response({"username": user.username, "email": user.email})


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


class ProfileAPIUpdate(APIView):
    serializer_class = ProfileSerializer
    permission_classes = [HasAPIKey | IsAuthenticated]

    def get_object(self) -> Profile:
        profile_id = self.kwargs.get("profile_id")
        return get_object_or_404(Profile, pk=profile_id)

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
    permission_classes = [IsAdminUser | HasAPIKey]


class ProfileAPIList(generics.ListCreateAPIView):
    serializer_class = ProfileSerializer
    queryset = Profile.objects.all()
    permission_classes = [IsAuthenticatedOrReadOnly | HasAPIKey]
