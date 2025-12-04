from django.db import models


class ProfileStatus(models.TextChoices):
    created = "created"
    completed = "completed"
