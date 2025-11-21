from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("workout_plans", "0003_program_coach_type"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="program",
            name="coach_type",
        ),
    ]
