from django.db import models
from django.db.models import Model

from apps.profiles.choices import ClientStatus


class Profile(Model):
    language = models.CharField(max_length=50, null=True, blank=True)
    tg_id = models.BigIntegerField(blank=True, null=True, unique=True)

    class Meta:
        verbose_name = "profile"
        verbose_name_plural = "profiles"


class ClientProfile(Model):
    profile = models.OneToOneField(Profile, on_delete=models.CASCADE, related_name="client_profile")
    name = models.CharField(max_length=50, null=True, blank=True)
    status = models.CharField(
        max_length=50,
        choices=ClientStatus.choices,
        default=ClientStatus.initial,
    )
    gender = models.CharField(max_length=50, null=True, blank=True)
    born_in = models.IntegerField(null=True, blank=True)
    weight = models.IntegerField(null=True, blank=True)
    health_notes = models.CharField(max_length=250, null=True, blank=True)
    workout_experience = models.CharField(max_length=50, null=True, blank=True)
    workout_goals = models.CharField(max_length=250, null=True, blank=True)
    profile_photo = models.CharField(max_length=250, null=True, blank=True)
    credits = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "ClientProfile"
        verbose_name_plural = "ClientProfiles"
