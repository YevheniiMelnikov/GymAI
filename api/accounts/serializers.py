from django.contrib.auth.models import User
from djoser.serializers import UserCreateSerializer
from rest_framework import serializers

from .models import Profile, ClientProfile, CoachProfile


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("username", "email")


class ProfileSerializer(serializers.ModelSerializer):
    user = serializers.SerializerMethodField()
    current_tg_id = serializers.IntegerField(required=False)

    class Meta:
        model = Profile
        fields = "__all__"

    def get_user(self, obj):
        return {"username": obj.user.username, "email": obj.user.email}

    def update(self, instance, validated_data):
        current_tg_id = validated_data.get("current_tg_id", None)
        if current_tg_id is None:
            validated_data.pop("current_tg_id", None)

        return super().update(instance, validated_data)


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


class UserCreateSerializer(UserCreateSerializer):
    class Meta(UserCreateSerializer.Meta):
        fields = ("id", "username", "email", "password")
