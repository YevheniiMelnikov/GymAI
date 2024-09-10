from django.contrib.auth.models import User
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from .models import Payment, Profile, Program, Subscription


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("username", "email")


class ProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    assigned_to = serializers.ListField(child=serializers.IntegerField(), required=False, allow_null=True, default=list)

    class Meta:
        model = Profile
        fields = "__all__"
        extra_kwargs = {"user": {"read_only": True}}

    def update(self, instance, validated_data):
        validated_data.pop("user", None)
        return super().update(instance, validated_data)


class ProgramSerializer(serializers.ModelSerializer):
    class Meta:
        model = Program
        fields = "__all__"


class SubscriptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Subscription
        fields = "__all__"

    def validate(self, data):
        user = self.context["request"].user

        if Subscription.objects.filter(user=user, enabled=True).exists():
            raise ValidationError("User already has an active subscription")

        return data


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = "__all__"

    def update(self, instance, validated_data):
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance
