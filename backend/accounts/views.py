from django.contrib.auth.models import User
from django.db import transaction
from rest_framework import generics
from rest_framework.permissions import IsAdminUser, IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.status import HTTP_201_CREATED, HTTP_400_BAD_REQUEST
from rest_framework.views import APIView
from rest_framework_api_key.permissions import HasAPIKey

from .models import Profile
from .serializers import ProfileSerializer


class CreateUserView(APIView):
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


class CurrentUserView(APIView):
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get(self, request) -> Response:
        if request.user.is_authenticated:
            return Response({"user_id": request.user.id})
        else:
            return Response({"user_id": None})


class ProfileAPIList(generics.ListCreateAPIView):
    serializer_class = ProfileSerializer
    queryset = Profile.objects.all()
    permission_classes = [IsAuthenticatedOrReadOnly]


class ProfileAPIUpdate(generics.RetrieveUpdateAPIView):
    serializer_class = ProfileSerializer
    queryset = Profile.objects.all()
    permission_classes = [IsAuthenticated | HasAPIKey]


class ProfileAPIDestroy(generics.RetrieveDestroyAPIView):
    serializer_class = ProfileSerializer
    queryset = Profile.objects.all()
    permission_classes = [IsAdminUser | HasAPIKey]
