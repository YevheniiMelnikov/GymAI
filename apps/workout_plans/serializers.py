from typing import Any

from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from apps.profiles.serializers import ClientProfileSerializer
from apps.workout_plans.models import Subscription, Program


class ExerciseSerializer(serializers.Serializer):
    name = serializers.CharField()
    sets = serializers.CharField()
    reps = serializers.CharField()
    gif_link = serializers.CharField(required=False, allow_null=True)
    weight = serializers.CharField(required=False, allow_null=True)


class DayExercisesSerializer(serializers.Serializer):
    day = serializers.CharField()
    exercises = ExerciseSerializer(many=True)


class ProgramSerializer(serializers.ModelSerializer):
    client_profile = ClientProfileSerializer(read_only=True)
    exercises_by_day = DayExercisesSerializer(many=True)

    class Meta:
        model = Program
        fields = "__all__"

    def update(self, instance, validated_data: dict[str, Any]) -> Program:
        instance.exercises_by_day = validated_data.get("exercises_by_day", instance.exercises_by_day)
        instance.split_number = validated_data.get("split_number", instance.split_number)
        instance.wishes = validated_data.get("wishes", instance.wishes)
        instance.save()
        return instance


class SubscriptionSerializer(serializers.ModelSerializer):
    client_profile = ClientProfileSerializer(read_only=True)
    exercises = DayExercisesSerializer(many=True)

    class Meta:
        model = Subscription
        fields = "__all__"

    def validate(self, data: dict[str, Any]) -> dict[str, Any]:
        user = self.context["request"].user

        if not user.is_authenticated:
            raise ValidationError("User is not authenticated")

        if "client_profile" not in data:
            if not hasattr(user, "profile"):
                raise ValidationError("User profile not found")
            data["client_profile"] = user.profile.client_profile

        if not self.instance:
            if Subscription.objects.filter(client_profile=data["client_profile"], enabled=True).exists():
                raise ValidationError("User already has an active subscription")

        return data
