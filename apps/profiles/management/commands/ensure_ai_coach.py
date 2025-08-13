from django.core.management.base import BaseCommand
from django.db import transaction
from apps.profiles.models import Profile, CoachProfile
from config.app_settings import settings
from apps.profiles.choices import Role, CoachType


class Command(BaseCommand):
    """Create AI coach if it doesn't exist."""

    @transaction.atomic
    def handle(self, *args, **options):  # pyrefly: ignore[bad-override]
        if CoachProfile.objects.filter(coach_type=CoachType.AI).exists():  # pyrefly: ignore[missing-attribute]
            self.stdout.write(self.style.NOTICE("AI coach already exists"))  # pyrefly: ignore[missing-attribute]
            return

        profile, _ = Profile.objects.get_or_create(  # pyrefly: ignore[missing-attribute]
            role=Role.COACH,
            language=settings.DEFAULT_LANG,
        )

        CoachProfile.objects.create(  # pyrefly: ignore[missing-attribute]
            profile=profile,
            coach_type=CoachType.AI,
            verified=True,
        )
        self.stdout.write(self.style.SUCCESS("AI coach created"))  # pyrefly: ignore[missing-attribute]
