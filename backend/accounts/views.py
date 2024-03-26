from rest_framework import status, permissions, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_api_key.permissions import HasAPIKey

from . import models, serializers
from .serializers import PersonSerializer


class RegisterUser(APIView):
    def post(self, request):
        serializer = PersonSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            if user:
                return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class PersonViewSet(viewsets.ModelViewSet):
    permission_classes = [HasAPIKey | permissions.IsAuthenticated]
    serializer_class = serializers.PersonSerializer
    queryset = models.Person.objects.all()
    # filter_backends = [DjangoFilterBackend]
    # filterset_fields = ["name", "enabled", "status", "start", "end"]
