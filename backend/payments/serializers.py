from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from accounts.serializers import ClientProfileSerializer
from payments.models import Program, Subscription, Payment


class ProgramSerializer(serializers.ModelSerializer):
    client_profile = ClientProfileSerializer(read_only=True)

    class Meta:
        model = Program
        fields = "__all__"

    def update(self, instance, validated_data):
        instance.exercises_by_day = validated_data.get("exercises_by_day", instance.exercises_by_day)
        instance.split_number = validated_data.get("split_number", instance.split_number)
        instance.save()
        return instance


class SubscriptionSerializer(serializers.ModelSerializer):
    client_profile = ClientProfileSerializer(read_only=True)

    class Meta:
        model = Subscription
        fields = "__all__"

    def validate(self, data):
        user = self.context["request"].user
        client_profile = user.profile.client_profile

        if Subscription.objects.filter(client_profile=client_profile, enabled=True).exists():
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
