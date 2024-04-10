from accounts.models import Person
from rest_framework import permissions, viewsets
from rest_framework.generics import ListAPIView, RetrieveUpdateDestroyAPIView, UpdateAPIView
from rest_framework_api_key.permissions import HasAPIKey

from . import serializers
from .serializers import PersonSerializer


class PersonViewSet(viewsets.ModelViewSet):
    serializer_class = serializers.PersonSerializer
    queryset = Person.objects.all()
    # permission_classes = [HasAPIKey | permissions.IsAuthenticated]
    # filter_backends = [DjangoFilterBackend]
    # filterset_fields = ["name", "enabled", "status", "start", "end"]
