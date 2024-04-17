from django.contrib.auth.models import User
from rest_framework import generics
from rest_framework.permissions import IsAdminUser, IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.status import HTTP_400_BAD_REQUEST, HTTP_201_CREATED
from rest_framework.views import APIView
from rest_framework_api_key.permissions import HasAPIKey

from .models import Person
from .serializers import PersonSerializer


class CreateUserView(APIView):
    def post(self, request: Request) -> Response:
        username = request.data.get("username")
        password = request.data.get("password")
        email = request.data.get("email")

        if not password or not username or not email:
            return Response({"error": "Required fields are missing"}, status=HTTP_400_BAD_REQUEST)

        try:
            User.objects.create_user(
                username=username,
                password=password,
                email=email
            )
        except Exception as e:
            return Response({"error": str(e)}, status=HTTP_400_BAD_REQUEST)

        return Response({"message": "User created successfully"}, status=HTTP_201_CREATED)


class PersonAPIList(generics.ListCreateAPIView):
    serializer_class = PersonSerializer
    queryset = Person.objects.all()
    permission_classes = [IsAuthenticatedOrReadOnly]


class PersonAPIUpdate(generics.RetrieveUpdateAPIView):
    serializer_class = PersonSerializer
    queryset = Person.objects.all()
    permission_classes = [IsAuthenticated | HasAPIKey]


class PersonAPIDestroy(generics.RetrieveDestroyAPIView):
    serializer_class = PersonSerializer
    queryset = Person.objects.all()
    permission_classes = [IsAdminUser | HasAPIKey]
