from django.db import models
from django.db.models import Model

from apps.profiles.choices import ProfileStatus


class Profile(Model):
    language = models.CharField(max_length=50, null=True, blank=True)
    tg_id = models.BigIntegerField(blank=True, null=True, unique=True)
    status = models.CharField(
        max_length=50,
        choices=ProfileStatus.choices,
        default=ProfileStatus.created,
    )
    gender = models.CharField(max_length=50, null=True, blank=True)
    born_in = models.IntegerField(null=True, blank=True)
    weight = models.IntegerField(null=True, blank=True)
    health_notes = models.CharField(max_length=250, null=True, blank=True)
    workout_experience = models.CharField(max_length=50, null=True, blank=True)
    workout_goals = models.CharField(max_length=250, null=True, blank=True)
    workout_location = models.CharField(
        max_length=32,
        choices=[("gym", "gym"), ("home", "home")],
        null=True,
        blank=True,
    )
    credits = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "profile"
        verbose_name_plural = "profiles"

    def __str__(self) -> str:
        return f"Profile(id={self.id}, tg_id={self.tg_id})"
