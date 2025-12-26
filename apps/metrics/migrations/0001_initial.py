from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies: list[tuple[str, str]] = []

    operations = [
        migrations.CreateModel(
            name="MetricsEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "event_type",
                    models.CharField(
                        choices=[
                            ("new_user", "new_user"),
                            ("ask_ai_answer", "ask_ai_answer"),
                            ("diet_plan", "diet_plan"),
                            ("workout_plan", "workout_plan"),
                        ],
                        max_length=50,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
            ],
            options={
                "verbose_name": "Metrics event",
                "verbose_name_plural": "Metrics events",
                "indexes": [
                    models.Index(fields=["event_type", "created_at"], name="metrics_event_type_created_idx"),
                ],
            },
        ),
    ]
