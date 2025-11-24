from django.db import migrations, models

COACH_CHOICES = [("human", "Human"), ("ai_coach", "Ai")]


class Migration(migrations.Migration):
    dependencies = [
        ("workout_plans", "0002_subscription_period"),
    ]

    operations = [
        migrations.AddField(
            model_name="program",
            name="coach_type",
            field=models.CharField(max_length=10, choices=COACH_CHOICES, default="human"),
        ),
    ]
