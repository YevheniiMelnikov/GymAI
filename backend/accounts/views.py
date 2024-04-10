from accounts.models import Person
from rest_framework import mixins, permissions, viewsets
from rest_framework_api_key.permissions import HasAPIKey

from .serializers import PersonSerializer


class PersonViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
    mixins.UpdateModelMixin,
):
    serializer_class = PersonSerializer
    queryset = Person.objects.all()
    # permission_classes = [HasAPIKey | permissions.IsAuthenticated]
    # filter_backends = [DjangoFilterBackend]
    # filterset_fields = ["name", "enabled", "status", "start", "end"]
