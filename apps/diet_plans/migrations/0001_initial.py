from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("profiles", "0017_profile_workout_experience_levels"),
    ]

    operations = [
        migrations.CreateModel(
            name="DietPlan",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("request_id", models.CharField(max_length=64, unique=True)),
                ("plan", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "profile",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="diet_plans",
                        to="profiles.profile",
                    ),
                ),
            ],
            options={
                "verbose_name": "Diet plan",
                "verbose_name_plural": "Diet plans",
            },
        ),
        migrations.AddIndex(
            model_name="dietplan",
            index=models.Index(fields=["profile", "-created_at"], name="diet_plan_profile_created_idx"),
        ),
        migrations.AddIndex(
            model_name="dietplan",
            index=models.Index(fields=["request_id"], name="diet_plan_request_idx"),
        ),
    ]
