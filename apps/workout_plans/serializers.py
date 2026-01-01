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
    drop_set = serializers.BooleanField(required=False)
    superset_id = serializers.IntegerField(required=False, allow_null=True)
    superset_order = serializers.IntegerField(required=False, allow_null=True)
    sets_detail = ExerciseSetDetailSerializer(many=True, required=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        superset_id = attrs.get("superset_id")
        superset_order = attrs.get("superset_order")
        set_id = attrs.get("set_id")
        if superset_id is not None:
            if set_id is None:
                raise ValidationError("set_id is required when superset_id is provided")
            if superset_order is None:
                raise ValidationError("superset_order is required when superset_id is provided")
        if superset_order is not None and superset_id is None:
            raise ValidationError("superset_id is required when superset_order is provided")
        if superset_order is not None and superset_order < 1:
            raise ValidationError("superset_order must be >= 1")
        return attrs


class DayExercisesSerializer(serializers.Serializer):
    day = serializers.CharField()
    exercises = ExerciseSerializer(many=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        exercises = attrs.get("exercises", [])
        if not isinstance(exercises, list):
            return attrs
        set_ids = {item.get("set_id") for item in exercises if item.get("set_id") is not None}
        superset_counts: dict[int, int] = {}
        superset_orders: dict[int, set[int]] = {}
        for item in exercises:
            superset_id = item.get("superset_id")
            if superset_id is None:
                continue
            if superset_id not in set_ids:
                raise ValidationError("superset_id must reference an existing set_id within the same day")
            superset_counts[superset_id] = superset_counts.get(superset_id, 0) + 1
            order = item.get("superset_order")
            if order is None:
                continue
            orders = superset_orders.setdefault(superset_id, set())
            if order in orders:
                raise ValidationError("superset_order must be unique within the same superset_id")
            orders.add(order)
        for superset_id, count in superset_counts.items():
            if count < 2:
                raise ValidationError("superset_id must group at least two exercises")
        return attrs


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
