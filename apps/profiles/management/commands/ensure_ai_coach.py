from django.core.management.base import BaseCommand
from apps.profiles.models import Profile, CoachProfile
from config.env_settings import settings
from apps.profiles.choices import Role, CoachType


class Command(BaseCommand):
    """Ensure at least one AI coach exists."""

    def handle(self, *args, **options):
        if CoachProfile.objects.filter(coach_type=CoachType.AI).exists():
            self.stdout.write("AI coach already exists")
            return

        profile = Profile.objects.create(role=Role.COACH, language=settings.DEFAULT_LANG)
        CoachProfile.objects.create(
            profile=profile,
            coach_type=CoachType.AI,
            verified=True,
        )
        self.stdout.write(self.style.SUCCESS("AI coach created"))
