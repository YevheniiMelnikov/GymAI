from django.core.management.base import BaseCommand
from django.db import transaction
from apps.profiles.models import Profile, CoachProfile
from config.app_settings import settings
from apps.profiles.choices import Role, CoachType


class Command(BaseCommand):
    """Create AI coach if it doesn't exist."""

    @transaction.atomic
    def handle(self, *args, **options):
        if CoachProfile.objects.filter(coach_type=CoachType.AI).exists():
            self.stdout.write(self.style.NOTICE("AI coach already exists"))
            return

        profile, _ = Profile.objects.get_or_create(
            role=Role.COACH,
            language=settings.DEFAULT_LANG,
        )

        CoachProfile.objects.create(
            profile=profile,
            coach_type=CoachType.AI,
            verified=True,
        )
        self.stdout.write(self.style.SUCCESS("AI coach created"))
