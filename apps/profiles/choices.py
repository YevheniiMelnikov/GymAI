from django.db import models


class ClientStatus(models.TextChoices):
    waiting_for_text = "waiting_for_text"
    default = "default"
    waiting_for_subscription = "waiting_for_subscription"
    waiting_for_program = "waiting_for_program"
    initial = "initial"
