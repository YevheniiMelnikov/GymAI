from rest_framework import serializers
from .models import Profile, ClientProfile


class ProfileSerializer(serializers.ModelSerializer):
    class Meta:  # pyrefly: ignore[bad-override]
        model = Profile
        fields = "__all__"


class ClientProfileSerializer(serializers.ModelSerializer):
    profile_data = ProfileSerializer(source="profile", read_only=True)

    class Meta:  # pyrefly: ignore[bad-override]
        model = ClientProfile
        fields = "__all__"
