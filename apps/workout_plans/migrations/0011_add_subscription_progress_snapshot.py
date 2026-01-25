from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("workout_plans", "0010_add_subscription_split_number"),
    ]

    operations = [
        migrations.CreateModel(
            name="SubscriptionProgressSnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("week_start", models.DateField()),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "profile",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="subscription_progress_snapshots",
                        to="profiles.profile",
                    ),
                ),
                (
                    "subscription",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="progress_snapshots",
                        to="workout_plans.subscription",
                    ),
                ),
            ],
            options={
                "verbose_name": "Subscription progress snapshot",
                "verbose_name_plural": "Subscription progress snapshots",
            },
        ),
        migrations.AddIndex(
            model_name="subscriptionprogresssnapshot",
            index=models.Index(fields=["subscription", "-week_start"], name="sub_progress_week_idx"),
        ),
        migrations.AddIndex(
            model_name="subscriptionprogresssnapshot",
            index=models.Index(fields=["profile", "-week_start"], name="sub_progress_profile_week_idx"),
        ),
        migrations.AddConstraint(
            model_name="subscriptionprogresssnapshot",
            constraint=models.UniqueConstraint(
                fields=("subscription", "week_start"),
                name="sub_progress_unique_week",
            ),
        ),
    ]
