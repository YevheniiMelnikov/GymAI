from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
import os


class Command(BaseCommand):
    help = "Create default superuser if it doesn't exist"

    def handle(self, *args, **options):
        username = os.environ.get("DJANGO_USER", "admin")
        password = os.environ.get("DJANGO_PASSWORD", "admin")
        User = get_user_model()
        if not User.objects.filter(username=username).exists():
            User.objects.create_superuser(username=username, password=password)
            self.stdout.write(self.style.SUCCESS(f"Superuser '{username}' created"))
        else:
            self.stdout.write("Superuser already exists")
