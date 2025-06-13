from typing import Type

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractBaseUser
from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    """Create default superuser if it doesn't exist."""

    def handle(self, *args, **options):
        username = settings.DJANGO_ADMIN
        password = settings.DJANGO_PASSWORD
        User: Type[AbstractBaseUser] = get_user_model()
        if not User.objects.filter(username=username).exists():
            User.objects.create_superuser(username=username, password=password)  # type: ignore[attr-defined]
            self.stdout.write(self.style.SUCCESS("Superuser created"))
        else:
            self.stdout.write("Superuser already exists")
