from rest_framework.generics import ListAPIView, UpdateAPIView, RetrieveUpdateDestroyAPIView

from accounts.models import Person
from rest_framework import permissions, viewsets
from rest_framework_api_key.permissions import HasAPIKey

from . import serializers
from .serializers import PersonSerializer


class PersonAPIList(ListAPIView):
    queryset = Person.objects.all()
    serializer_class = PersonSerializer


class PersonAPIUpdate(UpdateAPIView):
    queryset = Person.objects.all()
    serializer_class = PersonSerializer


class PersonAPIDetailView(RetrieveUpdateDestroyAPIView):
    queryset = Person.objects.all()
    serializer_class = PersonSerializer


    #
    # def delete(self, request, *args, **kwargs) -> Response:
    #     user_id = kwargs.get("id")
    #     if not user_id:
    #         return Response({"error": "Method DELETE not allowed"}, status=status.HTTP_400_BAD_REQUEST)
    #
    #     try:
    #         instance = Person.objects.get(pk=user_id)
    #     except Exception:
    #         return Response({"error": "Object not found"}, status=status.HTTP_400_BAD_REQUEST)
    #
    #     instance.delete()
    #     return Response({"delete": "OK"}, status=status.HTTP_200_OK)


class PersonViewSet(viewsets.ModelViewSet):
    permission_classes = [HasAPIKey | permissions.IsAuthenticated]
    serializer_class = serializers.PersonSerializer
    queryset = Person.objects.all()
    # filter_backends = [DjangoFilterBackend]
    # filterset_fields = ["name", "enabled", "status", "start", "end"]
