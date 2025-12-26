from django.db import migrations, models


def backfill_subscription_fields(apps, schema_editor) -> None:
    Subscription = apps.get_model("workout_plans", "Subscription")
    Profile = apps.get_model("profiles", "Profile")

    profile_locations = {
        profile.id: profile.workout_location
        for profile in Profile.objects.exclude(workout_location__isnull=True).exclude(workout_location="")
    }
    for sub in Subscription.objects.all():
        if sub.wishes is None:
            sub.wishes = ""
        if not sub.workout_location:
            sub.workout_location = profile_locations.get(sub.profile_id, "gym")
        sub.save(update_fields=["wishes", "workout_location"])


class Migration(migrations.Migration):
    dependencies = [
        ("workout_plans", "0008_add_indexes"),
        ("profiles", "0016_profile_diet_preferences"),
    ]

    operations = [
        migrations.AddField(
            model_name="subscription",
            name="workout_location",
            field=models.CharField(
                choices=[("gym", "gym"), ("home", "home")],
                default="gym",
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name="subscription",
            name="wishes",
            field=models.CharField(default="", max_length=500),
        ),
        migrations.RunPython(backfill_subscription_fields, reverse_code=migrations.RunPython.noop),
    ]
