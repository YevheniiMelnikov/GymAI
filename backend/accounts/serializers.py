from rest_framework import serializers

from .models import Profile


class ProfileSerializer(serializers.ModelSerializer):
    user = serializers.HiddenField(default=serializers.CurrentUserDefault())
    assigned_to = serializers.ListField(child=serializers.IntegerField(), required=False, allow_null=True, default=list)

    class Meta:
        model = Profile
        fields = "__all__"
        extra_kwargs = {"user": {"read_only": True}}

    def update(self, instance, validated_data):
        validated_data.pop("user", None)
        return super().update(instance, validated_data)
