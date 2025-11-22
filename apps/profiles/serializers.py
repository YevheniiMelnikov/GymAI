from rest_framework import serializers
from .models import Profile


class ProfileSerializer(serializers.ModelSerializer):
    class Meta:  # pyrefly: ignore[bad-override]
        model = Profile
        fields = "__all__"
