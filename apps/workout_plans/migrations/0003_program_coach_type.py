from django.db import migrations, models

from apps.profiles.choices import CoachType


class Migration(migrations.Migration):
    dependencies = [
        ("workout_plans", "0002_subscription_period"),
    ]

    operations = [
        migrations.AddField(
            model_name="program",
            name="coach_type",
            field=models.CharField(max_length=10, choices=CoachType.choices, default=CoachType.HUMAN),
        ),
    ]
