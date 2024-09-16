from django.contrib.auth.models import User
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Model


class Profile(Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    status = models.CharField(max_length=50, default="client")
    language = models.CharField(max_length=50, null=True, blank=True)
    assigned_to = ArrayField(models.IntegerField(), default=list, blank=True)
    current_tg_id = models.BigIntegerField(blank=True)
    name = models.CharField(max_length=50, null=True, blank=True)

    class Meta:
        verbose_name = "profile"
        verbose_name_plural = "profiles"
        constraints = [models.UniqueConstraint(fields=["user", "current_tg_id"], name="unique_tg_id_per_user")]
        app_label = "accounts"


class ClientProfile(Model):
    profile = models.OneToOneField(Profile, on_delete=models.CASCADE, related_name="client_profile")
    coach = models.ForeignKey("CoachProfile", on_delete=models.SET_NULL, null=True, blank=True, related_name="clients")
    gender = models.CharField(max_length=50, null=True, blank=True)
    born_in = models.IntegerField(null=True, blank=True)
    weight = models.IntegerField(null=True, blank=True)
    health_notes = models.CharField(max_length=250, null=True, blank=True)
    workout_experience = models.CharField(max_length=50, null=True, blank=True)
    workout_goals = models.CharField(max_length=250, null=True, blank=True)

    class Meta:
        verbose_name = "client profile"
        verbose_name_plural = "client profiles"
        app_label = "accounts"


class CoachProfile(Model):
    profile = models.OneToOneField(Profile, on_delete=models.CASCADE, related_name="coach_profile")
    surname = models.CharField(max_length=50, null=True, blank=True)
    additional_info = models.CharField(max_length=250, null=True, blank=True)
    profile_photo = models.CharField(max_length=250, null=True, blank=True)
    payment_details = models.CharField(max_length=250, null=True, blank=True)
    subscription_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    program_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    verified = models.BooleanField(default=False)

    class Meta:
        verbose_name = "coach profile"
        verbose_name_plural = "coach profiles"
        app_label = "accounts"
