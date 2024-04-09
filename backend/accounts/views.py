from accounts.models import Person
from rest_framework import permissions, status, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_api_key.permissions import HasAPIKey

from . import serializers
from .serializers import PersonSerializer


class PersonAPIView(APIView):
    def get(self, request) -> Response:
        persons = Person.objects.all()
        return Response({"persons": PersonSerializer(persons, many=True).data}, status=status.HTTP_200_OK)

    def post(self, request) -> Response:
        serializer = PersonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"post": serializer.data}, status=status.HTTP_201_CREATED)

    def put(self, request, *args, **kwargs) -> Response:
        user_id = kwargs.get("id")
        if not user_id:
            return Response({"error": "Method PUT not allowed"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            instance = Person.objects.get(pk=user_id)
        except Exception:
            return Response({"error": "Object not found"}, status=status.HTTP_400_BAD_REQUEST)

        serializer = PersonSerializer(data=request.data, instance=instance)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"put": serializer.data}, status=status.HTTP_201_CREATED)

    def delete(self, request, *args, **kwargs) -> Response:
        user_id = kwargs.get("id")
        if not user_id:
            return Response({"error": "Method DELETE not allowed"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            instance = Person.objects.get(pk=user_id)
        except Exception:
            return Response({"error": "Object not found"}, status=status.HTTP_400_BAD_REQUEST)

        instance.delete()
        return Response({"delete": "OK"}, status=status.HTTP_200_OK)


class PersonViewSet(viewsets.ModelViewSet):
    permission_classes = [HasAPIKey | permissions.IsAuthenticated]
    serializer_class = serializers.PersonSerializer
    queryset = Person.objects.all()
    # filter_backends = [DjangoFilterBackend]
    # filterset_fields = ["name", "enabled", "status", "start", "end"]
