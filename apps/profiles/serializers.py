from decimal import Decimal

from rest_framework import serializers
from .models import Profile, ClientProfile, CoachProfile


class ProfileSerializer(serializers.ModelSerializer):
    class Meta:  # pyre-ignore[bad-override]
        model = Profile
        fields = "__all__"


class ClientProfileSerializer(serializers.ModelSerializer):
    profile_data = ProfileSerializer(source="profile", read_only=True)

    class Meta:  # pyre-ignore[bad-override]
        model = ClientProfile
        fields = "__all__"


class CoachProfileSerializer(serializers.ModelSerializer):
    profile_data = ProfileSerializer(source="profile", read_only=True)

    subscription_price = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0.01"))
    program_price = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0.01"))

    class Meta:  # pyre-ignore[bad-override]
        model = CoachProfile
        fields = "__all__"
