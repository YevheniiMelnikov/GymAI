from rest_framework import generics
from rest_framework.permissions import IsAdminUser, IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_api_key.permissions import HasAPIKey

from .models import Person
from .serializers import PersonSerializer

# class PersonViewSet(
#     mixins.CreateModelMixin,
#     mixins.ListModelMixin,
#     mixins.RetrieveModelMixin,
#     viewsets.GenericViewSet,
#     mixins.UpdateModelMixin,
# ):
#     serializer_class = PersonSerializer
#     queryset = Person.objects.all()
#     permission_classes = [HasAPIKey | IsAuthenticated]


class CreateUserView(APIView):
    def post(self, request, format=None) -> Response:
        username = request.data.get("username")
        password = request.data.get("password")
        status = request.data.get("status", "client")
        gender = request.data.get("gender")
        email = request.data.get("email")
        birth_date = request.data.get("birth_date")
        language = request.data.get("language")

        if not password or not username or not email:
            return Response({"error": "Required fields are missing"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            Person.objects.create(
                username=username,
                password=password,
                status=status,
                gender=gender,
                email=email,
                birth_date=birth_date,
                language=language,
            )
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"message": "User created successfully"}, status=status.HTTP_201_CREATED)


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
