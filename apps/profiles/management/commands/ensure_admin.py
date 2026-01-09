from typing import Type

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractBaseUser
from django.core.management.base import BaseCommand
from django.db import transaction

from config.app_settings import settings


class Command(BaseCommand):
    """Create default superuser if it doesn't exist."""

    @transaction.atomic
    def handle(self, *args, **options):  # pyrefly: ignore[bad-override]
        username = settings.DJANGO_ADMIN
        password = settings.DJANGO_PASSWORD
        User: Type[AbstractBaseUser] = get_user_model()
        user = User.objects.filter(username=username).first()  # pyrefly: ignore[missing-attribute]
        if not user:
            User.objects.create_superuser(username=username, password=password)  # type: ignore[attr-defined]
            self.stdout.write(self.style.SUCCESS("Superuser created"))  # pyrefly: ignore[missing-attribute]
            return

        updated = False
        if getattr(user, "is_superuser", False) is not True:
            setattr(user, "is_superuser", True)
            updated = True
        if getattr(user, "is_staff", False) is not True:
            setattr(user, "is_staff", True)
            updated = True
        if password and not user.check_password(password):
            user.set_password(password)
            updated = True

        if updated:
            user.save(update_fields=["password", "is_staff", "is_superuser"])
            self.stdout.write(self.style.SUCCESS("Superuser updated"))  # pyrefly: ignore[missing-attribute]
        else:
            self.stdout.write("Superuser already exists")
