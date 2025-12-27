from django.db import migrations, models


def _clamp_split_number(value: int) -> int:
    return max(1, min(7, value))


def add_split_number(apps, schema_editor) -> None:
    Subscription = apps.get_model("workout_plans", "Subscription")
    for subscription in Subscription.objects.all().iterator():
        split_number = 0
        workout_days = getattr(subscription, "workout_days", None)
        if isinstance(workout_days, list):
            split_number = len(workout_days)
        if not split_number:
            exercises = getattr(subscription, "exercises", None) or []
            if isinstance(exercises, list):
                labels = []
                for day in exercises:
                    if isinstance(day, dict):
                        label = day.get("day")
                        if label:
                            labels.append(str(label))
                split_number = len(set(labels))
        if not split_number:
            split_number = 3
        subscription.split_number = _clamp_split_number(int(split_number))
        subscription.save(update_fields=["split_number"])


def noop(apps, schema_editor) -> None:
    return None


class Migration(migrations.Migration):
    dependencies = [
        ("workout_plans", "0009_add_subscription_location_wishes"),
    ]

    operations = [
        migrations.AddField(
            model_name="subscription",
            name="split_number",
            field=models.IntegerField(default=3),
        ),
        migrations.RunPython(add_split_number, noop),
        migrations.RemoveField(
            model_name="subscription",
            name="workout_days",
        ),
    ]
