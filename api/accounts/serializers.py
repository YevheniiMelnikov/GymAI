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
        fields = [
            "id",
            "profile_data",
            "gender",
            "born_in",
            "weight",
            "health_notes",
            "workout_experience",
            "workout_goals",
            "coach",
        ]


class CoachProfileSerializer(serializers.ModelSerializer):
    profile_data = ProfileSerializer(source="profile", read_only=True)

    class Meta:
        model = CoachProfile
        fields = [
            "id",
            "profile_data",
            "surname",
            "additional_info",
            "profile_photo",
            "payment_details",
            "subscription_price",
            "program_price",
            "verified",
        ]
