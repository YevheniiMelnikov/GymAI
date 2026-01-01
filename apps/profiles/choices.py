from django.db import models


class ProfileStatus(models.TextChoices):
    created = "created"
    completed = "completed"
    deleted = "deleted"


class WorkoutExperience(models.TextChoices):
    beginner = "beginner", "Beginner"
    amateur = "amateur", "Amateur"
    advanced = "advanced", "Advanced"
    pro = "pro", "Pro"
