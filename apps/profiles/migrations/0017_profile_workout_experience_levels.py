import re
from typing import Optional

from django.db import migrations, models


def _normalize_workout_experience(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    raw = str(value).strip().lower()
    if not raw:
        return None
    mapping = {
        "0-1": "beginner",
        "1-3": "amateur",
        "3-5": "advanced",
        "5+": "pro",
        "beginner": "beginner",
        "amateur": "amateur",
        "advanced": "advanced",
        "pro": "pro",
    }
    if raw in mapping:
        return mapping[raw]
    if "+" in raw:
        return "pro"
    numbers = re.findall(r"\d+(?:[.,]\d+)?", raw)
    if not numbers:
        return None
    normalized_numbers = []
    for entry in numbers:
        normalized_numbers.append(float(entry.replace(",", ".")))
    years = max(normalized_numbers)
    if years < 1:
        return "beginner"
    if years < 3:
        return "amateur"
    if years < 5:
        return "advanced"
    return "pro"


def normalize_workout_experience(apps, schema_editor) -> None:
    Profile = apps.get_model("profiles", "Profile")
    for profile in Profile.objects.exclude(workout_experience__isnull=True).exclude(workout_experience="").iterator():
        normalized = _normalize_workout_experience(profile.workout_experience)
        if normalized and normalized != profile.workout_experience:
            Profile.objects.filter(id=profile.id).update(workout_experience=normalized)


class Migration(migrations.Migration):
    dependencies = [
        ("profiles", "0016_profile_diet_preferences"),
    ]

    operations = [
        migrations.RunPython(normalize_workout_experience, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="profile",
            name="workout_experience",
            field=models.CharField(
                blank=True,
                choices=[
                    ("beginner", "Beginner"),
                    ("amateur", "Amateur"),
                    ("advanced", "Advanced"),
                    ("pro", "Pro"),
                ],
                max_length=50,
                null=True,
            ),
        ),
    ]
