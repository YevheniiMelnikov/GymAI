from django.db import models
from django.db.models import Model

from django.contrib.postgres.fields import ArrayField

from apps.profiles.fields import EncryptedField


class Profile(Model):
    status = models.CharField(max_length=50, default="client")
    language = models.CharField(max_length=50, null=True, blank=True)
    tg_id = models.BigIntegerField(blank=True, null=True, unique=True)

    class Meta:
        verbose_name = "profile"
        verbose_name_plural = "profiles"


class ClientProfile(Model):
    profile = models.OneToOneField(Profile, on_delete=models.CASCADE, related_name="client_profile")
    name = models.CharField(max_length=50, null=True, blank=True)
    gender = models.CharField(max_length=50, null=True, blank=True)
    born_in = models.IntegerField(null=True, blank=True)
    weight = models.IntegerField(null=True, blank=True)
    health_notes = models.CharField(max_length=250, null=True, blank=True)
    workout_experience = models.CharField(max_length=50, null=True, blank=True)
    workout_goals = models.CharField(max_length=250, null=True, blank=True)
    assigned_to = ArrayField(models.IntegerField(), default=list, blank=True)

    class Meta:
        verbose_name = "ClientProfile"
        verbose_name_plural = "ClientProfiles"


class CoachProfile(Model):
    profile = models.OneToOneField(Profile, on_delete=models.CASCADE, related_name="coach_profile")
    name = models.CharField(max_length=50, null=True, blank=True)
    surname = models.CharField(max_length=50, null=True, blank=True)
    additional_info = models.CharField(max_length=250, null=True, blank=True)
    profile_photo = models.CharField(max_length=250, null=True, blank=True)
    payment_details = EncryptedField(max_length=250, null=True, blank=True)
    subscription_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    program_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    verified = models.BooleanField(default=False)
    assigned_to = ArrayField(models.IntegerField(), default=list, blank=True)

    class Meta:
        verbose_name = "CoachProfile"
        verbose_name_plural = "CoachProfiles"
