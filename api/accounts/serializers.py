from rest_framework import serializers
from .models import Profile, ClientProfile, CoachProfile


class ProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = Profile
        fields = "__all__"


class ClientProfileSerializer(serializers.ModelSerializer):
    profile_data = ProfileSerializer(source="profile", read_only=True)

    class Meta:
        model = ClientProfile
        fields = "__all__"


class CoachProfileSerializer(serializers.ModelSerializer):
    profile_data = ProfileSerializer(source="profile", read_only=True)

    class Meta:
        model = CoachProfile
        fields = "__all__"
