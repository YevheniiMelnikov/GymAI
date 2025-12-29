from typing import Any

from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from apps.profiles.models import Profile
from apps.profiles.serializers import ProfileSerializer
from apps.workout_plans.models import Subscription, Program


class ExerciseSetDetailSerializer(serializers.Serializer):
    reps = serializers.IntegerField()
    weight = serializers.FloatField()
    weight_unit = serializers.CharField(required=False, allow_null=True, allow_blank=True)


class ExerciseSerializer(serializers.Serializer):
    name = serializers.CharField()
    sets = serializers.CharField()
    reps = serializers.CharField()
    weight = serializers.CharField(required=False, allow_null=True)
    set_id = serializers.IntegerField(required=False, allow_null=True)
    sets_detail = ExerciseSetDetailSerializer(many=True, required=False)


class DayExercisesSerializer(serializers.Serializer):
    day = serializers.CharField()
    exercises = ExerciseSerializer(many=True)


class ProgramSerializer(serializers.ModelSerializer):
    profile = ProfileSerializer(read_only=True)
    exercises_by_day = DayExercisesSerializer(many=True)

    class Meta:  # pyrefly: ignore[bad-override]
        model = Program
        fields = "__all__"

    def update(self, instance, validated_data: dict[str, Any]) -> Program:
        instance.exercises_by_day = validated_data.get("exercises_by_day", instance.exercises_by_day)
        instance.split_number = validated_data.get("split_number", instance.split_number)
        instance.wishes = validated_data.get("wishes", instance.wishes)
        instance.save()
        return instance


class SubscriptionSerializer(serializers.ModelSerializer):
    profile = ProfileSerializer(read_only=True)
    profile_id = serializers.PrimaryKeyRelatedField(
        queryset=Profile.objects.all(),
        source="profile",
        write_only=True,
    )
    exercises = DayExercisesSerializer(many=True)

    class Meta:  # pyrefly: ignore[bad-override]
        model = Subscription
        fields = "__all__"

    def validate_split_number(self, value: int) -> int:
        if value < 1 or value > 7:
            raise ValidationError("split_number must be between 1 and 7")
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        request = self.context["request"]
        user = request.user
        auth_header = request.headers.get("Authorization", "")
        has_api_key = auth_header.startswith("Api-Key ")

        if not user.is_authenticated and not has_api_key:
            raise ValidationError(["User is not authenticated"])

        if "profile" not in attrs:
            if self.instance is not None:
                return attrs
            if user.is_authenticated and hasattr(user, "profile"):
                attrs["profile"] = user.profile
            else:
                raise ValidationError(["User profile not found"])

        if self.instance is None:
            if "workout_location" not in attrs:
                raise ValidationError(["Workout location is required"])
            if "wishes" not in attrs:
                raise ValidationError(["Wishes are required"])
            if "split_number" not in attrs:
                raise ValidationError(["Split number is required"])

        return attrs
